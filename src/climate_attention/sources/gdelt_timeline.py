"""Canonical daily trend collection from GDELT DOC TimelineVolRaw."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, time as dt_time, timedelta, timezone
from hashlib import sha256
from typing import Any

import httpx

from ..config import Country
from ..models import (
    CollectionRequest,
    DailyTrend,
    Query,
    RequestLog,
    Topic,
    TrendProviderResult,
    utc_now,
)
from .base import ProviderCollectionError
from .gdelt import (
    GDELTProvider,
    GDELTResponseError,
    GDELTWindow,
    _RequestFailed,
    _retry_delay,
    build_gdelt_query,
    parse_gdelt_datetime,
)


LOGGER = logging.getLogger(__name__)

TrendWindowSink = Callable[
    [str, GDELTWindow, RequestLog | None, list[DailyTrend], list[GDELTWindow]], None
]


def compile_topic_queries(topics: list[Topic], countries: list[Country]) -> list[Query]:
    """Compile query alternatives into one deduplicated GDELT theme expression."""
    compiled: list[Query] = []
    for topic in topics:
        specs = [spec for spec in topic.queries if spec.enabled]
        if not specs:
            continue
        if topic.geographies:
            raise ValueError(
                f"topic {topic.id!r} defines geographies; trend countries must be "
                "selected through the country configuration"
            )
        for spec in specs:
            if any(
                value is not None
                for value in (
                    spec.include_terms,
                    spec.exclude_terms,
                    spec.languages,
                    spec.geographies,
                )
            ):
                raise ValueError(
                    f"query-specific filters are not supported for combined trend "
                    f"topic {topic.id!r}; move them to topic level"
                )
        expressions = list(dict.fromkeys(spec.expression for spec in specs))
        expression = (
            expressions[0]
            if len(expressions) == 1
            else f"({' OR '.join(expressions)})"
        )
        languages: list[str | None] = topic.languages or [None]
        for country in countries:
            for language in languages:
                compiled.append(
                    Query(
                        topic_id=topic.id,
                        query_id="topic_combined",
                        expression=expression,
                        include_terms=topic.include_terms,
                        exclude_terms=topic.exclude_terms,
                        language=language,
                        geography=country.id,
                    )
                )
    return compiled


def plan_timeline_windows(
    request: CollectionRequest,
    countries: list[Country],
    *,
    window_days: int = 366,
) -> list[GDELTWindow]:
    """Plan bounded timeline requests covering an inclusive date range."""
    if window_days < 8:
        raise ValueError("timeline window must be at least 8 days for daily resolution")
    windows: list[GDELTWindow] = []
    for query in compile_topic_queries(request.topics, countries):
        current = request.start
        while current <= request.end:
            chunk_end = min(request.end, current + timedelta(days=window_days - 1))
            windows.append(
                GDELTWindow(
                    query=query,
                    start=datetime.combine(current, dt_time.min, tzinfo=timezone.utc),
                    end=datetime.combine(chunk_end, dt_time.max, tzinfo=timezone.utc),
                )
            )
            current = chunk_end + timedelta(days=1)
    return windows


def parse_timeline_response(
    payload: dict[str, Any],
    window: GDELTWindow,
    collected_at: datetime,
    country_labels: dict[str, str],
) -> list[DailyTrend]:
    timelines = payload.get("timeline")
    if not isinstance(timelines, list):
        raise GDELTResponseError("GDELT timeline response is missing a 'timeline' list")
    series = next(
        (
            item
            for item in timelines
            if isinstance(item, dict) and isinstance(item.get("data"), list)
        ),
        None,
    )
    if series is None:
        raise GDELTResponseError("GDELT timeline response contains no data series")

    details = payload.get("query_details")
    metadata = {
        "query_details": details if isinstance(details, dict) else {},
        "series": series.get("series"),
        "geography_label": country_labels.get(
            window.query.geography or "", window.query.geography
        ),
        "normalization_scope": "gdelt_monitoring_volume",
    }
    by_date: dict[date, DailyTrend] = {}
    for point in series["data"]:
        if not isinstance(point, dict):
            raise GDELTResponseError("GDELT timeline data points must be objects")
        raw_date = point.get("date")
        if not isinstance(raw_date, str):
            raise GDELTResponseError("GDELT timeline point is missing 'date'")
        day = parse_gdelt_datetime(raw_date).date()
        if not window.start.date() <= day <= window.end.date():
            continue
        matched = _whole_number(point.get("value"), "value")
        norm_value = point.get("norm")
        monitored = (
            _whole_number(norm_value, "norm") if norm_value is not None else None
        )
        share = matched / monitored if monitored else None
        identity = "|".join(
            [
                "gdelt-timeline-v1",
                window.query.topic_id,
                window.query.query_id,
                window.query.geography or "",
                window.query.language or "",
                day.isoformat(),
            ]
        )
        if day in by_date:
            raise GDELTResponseError(f"duplicate GDELT timeline point for {day}")
        by_date[day] = DailyTrend(
            record_id=sha256(identity.encode("utf-8")).hexdigest(),
            date=day,
            source="gdelt",
            topic_id=window.query.topic_id,
            query_id=window.query.query_id,
            query_expression=window.query.expression,
            geography=window.query.geography,
            language=window.query.language,
            matched_count=matched,
            monitored_count=monitored,
            attention_share=share,
            collected_at=collected_at,
            metadata=metadata,
        )
    expected = (window.end.date() - window.start.date()).days + 1
    if len(by_date) != expected:
        missing = expected - len(by_date)
        raise GDELTResponseError(
            f"GDELT returned {len(by_date)} daily points for an expected {expected} "
            f"day window ({missing} missing); refusing an incomplete trend series"
        )
    return [by_date[day] for day in sorted(by_date)]


def _whole_number(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise GDELTResponseError(f"GDELT timeline {field!r} is not numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GDELTResponseError(f"GDELT timeline {field!r} is not numeric") from exc
    if number < 0 or not number.is_integer():
        raise GDELTResponseError(
            f"GDELT raw timeline {field!r} must be a non-negative whole number"
        )
    return int(number)


class GDELTTimelineProvider(GDELTProvider):
    """Collect complete daily counts without enumerating capped article lists."""

    name = "gdelt_timeline"

    def __init__(
        self,
        *,
        country_labels: dict[str, str],
        timeline_sink: TrendWindowSink | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.country_labels = country_labels
        self.timeline_sink = timeline_sink

    def collect_windows(self, windows: list[GDELTWindow]) -> TrendProviderResult:
        result = TrendProviderResult()
        collected_at = utc_now()
        for window in windows:
            self._emit_timeline("started", window)
            try:
                payload, attempts, status = self._request_timeline(window)
                if self.response_sink:
                    self.response_sink(
                        {
                            "collected_at": collected_at.isoformat(),
                            "window_id": window.window_id,
                            "mode": "timelinevolraw",
                            "query": window.query.model_dump(mode="json"),
                            "start": window.start.isoformat(),
                            "end": window.end.isoformat(),
                            "response": payload,
                        }
                    )
                trends = parse_timeline_response(
                    payload, window, collected_at, self.country_labels
                )
                log = self._request_log(
                    window,
                    status="success",
                    attempts=attempts,
                    records_returned=len(trends),
                    http_status=status,
                )
                result.requests.append(log)
                result.trends.extend(trends)
                self._emit_timeline("success", window, log, trends)
            except _RequestFailed as exc:
                log = self._request_log(
                    window,
                    status="failed",
                    attempts=exc.attempts,
                    http_status=exc.http_status,
                    error=str(exc),
                )
                result.requests.append(log)
                self._emit_timeline("failed", window, log)
                raise ProviderCollectionError(str(exc), result) from exc
            except Exception as exc:
                log = self._request_log(
                    window, status="failed", attempts=1, error=str(exc)
                )
                result.requests.append(log)
                self._emit_timeline("failed", window, log)
                raise ProviderCollectionError(str(exc), result) from exc
        result.trends = list(
            {trend.record_id: trend for trend in result.trends}.values()
        )
        return result

    def _request_timeline(
        self, window: GDELTWindow
    ) -> tuple[dict[str, Any], int, int]:
        params = {
            "query": build_gdelt_query(window.query),
            "mode": "timelinevolraw",
            "format": "json",
            "timelinesmooth": "0",
            "startdatetime": window.start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": window.end.strftime("%Y%m%d%H%M%S"),
        }
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                self._wait_for_request_slot()
                try:
                    response = self.client.get(self.endpoint, params=params)
                finally:
                    self._last_request_finished = self.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt <= self.max_retries:
                        delay = _retry_delay(
                            response.headers.get("Retry-After"),
                            self.backoff_seconds,
                            attempt,
                        )
                        LOGGER.warning(
                            "GDELT timeline returned HTTP %s; retrying in %.1fs",
                            response.status_code,
                            delay,
                        )
                        self.sleep(delay)
                        continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise GDELTResponseError("GDELT timeline JSON is not an object")
                return payload, attempt, response.status_code
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc
                status = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                retryable = status is None or status == 429 or status >= 500
                if retryable and attempt <= self.max_retries:
                    delay = self.backoff_seconds * (2 ** (attempt - 1))
                    self.sleep(delay)
                    continue
                raise _RequestFailed(
                    f"GDELT timeline request failed after {attempt} attempt(s): {exc}",
                    attempt,
                    status,
                ) from exc
        raise _RequestFailed(
            f"GDELT timeline request failed: {last_error}", self.max_retries + 1
        )

    def _emit_timeline(
        self,
        event: str,
        window: GDELTWindow,
        log: RequestLog | None = None,
        trends: list[DailyTrend] | None = None,
    ) -> None:
        if self.timeline_sink:
            self.timeline_sink(event, window, log, trends or [], [])
