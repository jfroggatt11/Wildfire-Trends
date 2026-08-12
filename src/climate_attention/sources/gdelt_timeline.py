"""Canonical daily trends from GDELT DOC country and raw timeline modes."""

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
    DailyCountryCoverage,
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

COUNTRY_COVERAGE_TOPIC_ID = "__country_coverage__"
COUNTRY_COVERAGE_QUERY_ID = "country_coverage"
SOURCE_COUNTRY_QUERY_ID = "topic_combined"
GDELT_COUNTRY_LABEL_ALIASES = {
    "bosniaherzegovina": "bosniaandherzegovina",
    "slovakrepublic": "slovakia",
}
TimelineObservation = DailyTrend | DailyCountryCoverage

TrendWindowSink = Callable[
    [str, GDELTWindow, RequestLog | None, list[TimelineObservation], list[GDELTWindow]],
    None,
]


def compile_topic_queries(topics: list[Topic], countries: list[Country]) -> list[Query]:
    """Compile query alternatives into one deduplicated GDELT theme expression."""
    compiled: list[Query] = []
    for topic in topics:
        expression = _combined_topic_expression(topic)
        if expression is None:
            continue
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


def compile_source_country_queries(
    topics: list[Topic],
    countries: list[Country],
    *,
    batch_size: int | None = None,
) -> list[Query]:
    """Compile global country-breakdown queries or explicit fallback batches."""
    if batch_size is not None and not 1 <= batch_size <= 7:
        raise ValueError("source-country batch size must be between 1 and 7")
    ordered_countries = sorted(countries, key=lambda country: country.id)
    batches = (
        [[]]
        if batch_size is None
        else [
            ordered_countries[index : index + batch_size]
            for index in range(0, len(ordered_countries), batch_size)
        ]
    )
    compiled: list[Query] = []
    for topic in topics:
        expression = _combined_topic_expression(topic)
        if expression is None:
            continue
        languages: list[str | None] = topic.languages or [None]
        for language in languages:
            for batch in batches:
                compiled.append(
                    Query(
                        topic_id=topic.id,
                        query_id=SOURCE_COUNTRY_QUERY_ID,
                        expression=expression,
                        include_terms=topic.include_terms,
                        exclude_terms=topic.exclude_terms,
                        language=language,
                        geographies=[country.id for country in batch],
                    )
                )
    return compiled


def _combined_topic_expression(topic: Topic) -> str | None:
    specs = [spec for spec in topic.queries if spec.enabled]
    if not specs:
        return None
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
    return (
        expressions[0]
        if len(expressions) == 1
        else f"({' OR '.join(expressions)})"
    )


def plan_timeline_windows(
    request: CollectionRequest,
    countries: list[Country],
    *,
    window_days: int = 366,
) -> list[GDELTWindow]:
    """Plan bounded timeline requests covering an inclusive date range."""
    if window_days < 8:
        raise ValueError("timeline window must be at least 8 days for daily resolution")
    topic_queries = compile_topic_queries(request.topics, countries)
    dimensions = sorted(
        {
            (query.geography, query.language)
            for query in topic_queries
            if query.geography is not None
        },
        key=lambda item: (item[0] or "", item[1] or ""),
    )
    coverage_queries = [
        Query(
            topic_id=COUNTRY_COVERAGE_TOPIC_ID,
            query_id=COUNTRY_COVERAGE_QUERY_ID,
            expression="",
            language=language,
            geography=geography,
        )
        for geography, language in dimensions
    ]
    windows: list[GDELTWindow] = []
    # Coverage windows sort first when resumed and provide the denominator once per
    # country/language/date window, rather than repeating it for every topic.
    for query in [*coverage_queries, *topic_queries]:
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


def plan_source_country_windows(
    request: CollectionRequest,
    countries: list[Country],
    *,
    window_days: int = 366,
    batch_size: int | None = None,
) -> list[GDELTWindow]:
    """Plan native country attention, globally by default or in fallback batches."""
    if window_days < 8:
        raise ValueError("timeline window must be at least 8 days for daily resolution")
    windows: list[GDELTWindow] = []
    queries = compile_source_country_queries(
        request.topics, countries, batch_size=batch_size
    )
    for query in queries:
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
        "global_normalization_scope": "all_gdelt_monitored_articles",
        "country_normalization_scope": "source_country_gdelt_monitored_articles",
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
        global_share = matched / monitored if monitored else None
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
            global_monitored_count=monitored,
            global_attention_share=global_share,
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


def parse_country_coverage_response(
    payload: dict[str, Any],
    window: GDELTWindow,
    collected_at: datetime,
    country_labels: dict[str, str],
) -> list[DailyCountryCoverage]:
    """Parse an operator-only source-country timeline into daily denominators."""
    if not _is_country_coverage(window):
        raise ValueError("country coverage parser requires a coverage window")
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

    geography = window.query.geography
    if geography is None:
        raise ValueError("country coverage window is missing geography")
    metadata = {
        "query_details": (
            payload.get("query_details")
            if isinstance(payload.get("query_details"), dict)
            else {}
        ),
        "series": series.get("series"),
        "geography_label": country_labels.get(geography, geography),
        "query_scope": "source_country_all_articles",
    }
    by_date: dict[date, DailyCountryCoverage] = {}
    for point in series["data"]:
        if not isinstance(point, dict):
            raise GDELTResponseError("GDELT timeline data points must be objects")
        raw_date = point.get("date")
        if not isinstance(raw_date, str):
            raise GDELTResponseError("GDELT timeline point is missing 'date'")
        day = parse_gdelt_datetime(raw_date).date()
        if not window.start.date() <= day <= window.end.date():
            continue
        country_count = _whole_number(point.get("value"), "value")
        norm_value = point.get("norm")
        global_count = (
            _whole_number(norm_value, "norm") if norm_value is not None else None
        )
        identity = "|".join(
            [
                "gdelt-country-coverage-v1",
                geography,
                window.query.language or "",
                day.isoformat(),
            ]
        )
        if day in by_date:
            raise GDELTResponseError(f"duplicate GDELT timeline point for {day}")
        by_date[day] = DailyCountryCoverage(
            record_id=sha256(identity.encode("utf-8")).hexdigest(),
            date=day,
            source="gdelt",
            geography=geography,
            language=window.query.language,
            country_monitored_count=country_count,
            global_monitored_count=global_count,
            collected_at=collected_at,
            metadata=metadata,
        )
    expected = (window.end.date() - window.start.date()).days + 1
    if len(by_date) != expected:
        missing = expected - len(by_date)
        raise GDELTResponseError(
            f"GDELT returned {len(by_date)} country coverage points for an expected "
            f"{expected} day window ({missing} missing); refusing an incomplete series"
        )
    return [by_date[day] for day in sorted(by_date)]


def parse_source_country_response(
    payload: dict[str, Any],
    window: GDELTWindow,
    collected_at: datetime,
    country_labels: dict[str, str],
) -> list[DailyTrend]:
    """Parse native within-country percentages from a global or batched response."""
    explicit_batch = bool(window.query.geographies)
    expected_countries = (
        window.query.geographies
        if explicit_batch
        else sorted(country_labels)
    )
    if not expected_countries:
        raise ValueError("source-country timeline requires configured geographies")
    timelines = payload.get("timeline")
    if not isinstance(timelines, list):
        raise GDELTResponseError("GDELT timeline response is missing a 'timeline' list")

    label_keys: dict[str, str] = {}
    for country_id in expected_countries:
        for value in (country_id, country_labels.get(country_id, country_id)):
            key = _country_key(value)
            previous = label_keys.setdefault(key, country_id)
            if previous != country_id:
                raise ValueError(
                    f"country labels are ambiguous after normalization: "
                    f"{previous!r} and {country_id!r}"
                )

    series_by_country: dict[str, dict[str, Any]] = {}
    unexpected: list[str] = []
    for series in timelines:
        if not isinstance(series, dict) or not isinstance(series.get("data"), list):
            raise GDELTResponseError("GDELT source-country series is malformed")
        series_label = series.get("series")
        if not isinstance(series_label, str) or not series_label.strip():
            raise GDELTResponseError("GDELT source-country series has no label")
        series_key = _source_country_series_key(series_label)
        country_id = label_keys.get(series_key)
        if country_id is None:
            alias_id = GDELT_COUNTRY_LABEL_ALIASES.get(series_key)
            if alias_id in expected_countries:
                country_id = alias_id
        if country_id is None:
            if explicit_batch:
                unexpected.append(series_label)
            continue
        if country_id in series_by_country:
            raise GDELTResponseError(
                f"duplicate GDELT source-country series for {country_id!r}"
            )
        series_by_country[country_id] = series
    if unexpected:
        raise GDELTResponseError(
            "GDELT returned unmapped source-country series: "
            + ", ".join(sorted(unexpected))
        )

    details = payload.get("query_details")
    expected_days = (window.end.date() - window.start.date()).days + 1
    trends: list[DailyTrend] = []
    for country_id in expected_countries:
        series = series_by_country.get(country_id)
        percentages: dict[date, float] = {}
        if series is not None:
            for point in series["data"]:
                if not isinstance(point, dict):
                    raise GDELTResponseError(
                        "GDELT source-country data points must be objects"
                    )
                raw_date = point.get("date")
                if not isinstance(raw_date, str):
                    raise GDELTResponseError(
                        "GDELT source-country point is missing 'date'"
                    )
                day = parse_gdelt_datetime(raw_date).date()
                if not window.start.date() <= day <= window.end.date():
                    continue
                if day in percentages:
                    raise GDELTResponseError(
                        f"duplicate GDELT source-country point for {country_id} {day}"
                    )
                percentages[day] = _percentage(point.get("value"), "value")
            if len(percentages) != expected_days:
                missing = expected_days - len(percentages)
                raise GDELTResponseError(
                    f"GDELT returned {len(percentages)} daily source-country points "
                    f"for {country_id!r}, expected {expected_days} ({missing} missing)"
                )

        for offset in range(expected_days):
            day = window.start.date() + timedelta(days=offset)
            percentage = percentages.get(day, 0.0)
            identity = "|".join(
                [
                    "gdelt-timeline-v1",
                    window.query.topic_id,
                    SOURCE_COUNTRY_QUERY_ID,
                    country_id,
                    window.query.language or "",
                    day.isoformat(),
                ]
            )
            metadata = {
                "collection_mode": "timelinesourcecountry",
                "query_details": details if isinstance(details, dict) else {},
                "series": series.get("series") if series is not None else None,
                "geography_label": country_labels.get(country_id, country_id),
                "reported_percentage": percentage,
                "series_omitted_as_zero": series is None,
                "country_query_scope": (
                    "explicit_batch" if explicit_batch else "global_breakdown"
                ),
                "response_series_count": len(timelines),
                "country_normalization_scope": (
                    "source_country_gdelt_monitored_articles"
                ),
            }
            trends.append(
                DailyTrend(
                    record_id=sha256(identity.encode("utf-8")).hexdigest(),
                    date=day,
                    source="gdelt",
                    topic_id=window.query.topic_id,
                    query_id=SOURCE_COUNTRY_QUERY_ID,
                    query_expression=window.query.expression,
                    geography=country_id,
                    language=window.query.language,
                    country_attention_share=percentage / 100.0,
                    collected_at=collected_at,
                    metadata=metadata,
                )
            )
    return trends


def _country_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _source_country_series_key(value: str) -> str:
    """Normalize GDELT labels such as ``Malta Volume Intensity``."""
    key = _country_key(value)
    suffix = _country_key("Volume Intensity")
    return key[: -len(suffix)] if key.endswith(suffix) else key


def _percentage(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise GDELTResponseError(f"GDELT timeline {field!r} is not numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GDELTResponseError(f"GDELT timeline {field!r} is not numeric") from exc
    if not 0 <= number <= 100:
        raise GDELTResponseError(
            f"GDELT source-country {field!r} must be a percentage from 0 to 100"
        )
    return number


def _is_country_coverage(window: GDELTWindow) -> bool:
    return (
        window.query.topic_id == COUNTRY_COVERAGE_TOPIC_ID
        and window.query.query_id == COUNTRY_COVERAGE_QUERY_ID
    )


def build_timeline_query(window: GDELTWindow) -> str:
    """Build either a topic query or an all-articles country baseline query."""
    if not _is_country_coverage(window):
        return build_gdelt_query(window.query)
    if not window.query.geography:
        raise ValueError("country coverage query requires a geography")
    parts = [f"sourcecountry:{window.query.geography}"]
    if window.query.language:
        parts.append(f"sourcelang:{window.query.language}")
    return " ".join(parts)


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
    timeline_mode = "timelinevolraw"

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
        for window in windows:
            self._emit_timeline("started", window)
            try:
                payload, attempts, status = self._request_timeline(window)
                collected_at = utc_now()
                if self.response_sink:
                    self.response_sink(
                        {
                            "collected_at": collected_at.isoformat(),
                            "window_id": window.window_id,
                            "mode": self.timeline_mode,
                            "query": window.query.model_dump(mode="json"),
                            "start": window.start.isoformat(),
                            "end": window.end.isoformat(),
                            "response": payload,
                        }
                    )
                observations = self._parse_window_response(
                    payload, window, collected_at
                )
                log = self._request_log(
                    window,
                    status="success",
                    attempts=attempts,
                    records_returned=len(observations),
                    http_status=status,
                )
                result.requests.append(log)
                result.trends.extend(
                    item for item in observations if isinstance(item, DailyTrend)
                )
                result.country_coverages.extend(
                    item
                    for item in observations
                    if isinstance(item, DailyCountryCoverage)
                )
                self._emit_timeline("success", window, log, observations)
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
        result.country_coverages = list(
            {
                coverage.record_id: coverage
                for coverage in result.country_coverages
            }.values()
        )
        return result

    def _parse_window_response(
        self,
        payload: dict[str, Any],
        window: GDELTWindow,
        collected_at: datetime,
    ) -> list[TimelineObservation]:
        if _is_country_coverage(window):
            return parse_country_coverage_response(
                payload, window, collected_at, self.country_labels
            )
        return parse_timeline_response(
            payload, window, collected_at, self.country_labels
        )

    def _request_timeline(
        self, window: GDELTWindow
    ) -> tuple[dict[str, Any], int, int]:
        params = {
            "query": build_timeline_query(window),
            "mode": self.timeline_mode,
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
        trends: list[TimelineObservation] | None = None,
    ) -> None:
        if self.timeline_sink:
            self.timeline_sink(event, window, log, trends or [], [])


class GDELTSourceCountryProvider(GDELTTimelineProvider):
    """Collect GDELT's native within-country attention percentages."""

    name = "gdelt_source_country"
    timeline_mode = "timelinesourcecountry"

    def _parse_window_response(
        self,
        payload: dict[str, Any],
        window: GDELTWindow,
        collected_at: datetime,
    ) -> list[TimelineObservation]:
        return parse_source_country_response(
            payload, window, collected_at, self.country_labels
        )
