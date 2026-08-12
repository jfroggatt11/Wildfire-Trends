"""GDELT DOC 2.0 article collection."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Any

import httpx

from ..models import (
    AttentionRecord,
    CollectionRequest,
    ProviderResult,
    Query,
    RequestLog,
    utc_now,
)
from .base import AttentionProvider, ProviderCollectionError


LOGGER = logging.getLogger(__name__)


class GDELTResponseError(RuntimeError):
    pass


class _RequestFailed(RuntimeError):
    def __init__(self, message: str, attempts: int, http_status: int | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class GDELTWindow:
    """One durable unit of GDELT collection work."""

    query: Query
    start: datetime
    end: datetime
    parent_window_id: str | None = None

    @property
    def window_id(self) -> str:
        identity = "|".join(
            [
                "gdelt-window-v1",
                self.query.topic_id,
                self.query.query_id,
                self.query.expression,
                self.query.language or "",
                self.query.geography or "",
                self.start.astimezone(timezone.utc).isoformat(),
                self.end.astimezone(timezone.utc).isoformat(),
            ]
        )
        return sha256(identity.encode("utf-8")).hexdigest()


WindowSink = Callable[
    [str, GDELTWindow, RequestLog | None, list[AttentionRecord], list[GDELTWindow]],
    None,
]


def _format_term(term: str) -> str:
    term = term.strip()
    if term.startswith('"') and term.endswith('"'):
        return term
    return f'"{term}"' if " " in term else term


def build_gdelt_query(query: Query) -> str:
    """Translate a provider-neutral query into GDELT DOC query syntax."""
    parts = [query.expression]
    parts.extend(_format_term(term) for term in query.include_terms)
    parts.extend(f"-{_format_term(term)}" for term in query.exclude_terms)
    if query.language:
        parts.append(f"sourcelang:{query.language}")
    if query.geography:
        parts.append(f"sourcecountry:{query.geography}")
    return " ".join(parts)


def parse_gdelt_datetime(value: str) -> datetime:
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GDELTResponseError(f"invalid GDELT publication timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_article(
    article: dict[str, Any], query: Query, collected_at: datetime
) -> AttentionRecord:
    url = article.get("url")
    if not isinstance(url, str) or not url:
        raise GDELTResponseError("GDELT article is missing a non-empty 'url'")
    seen_date = article.get("seendate")
    if not isinstance(seen_date, str) or not seen_date:
        raise GDELTResponseError(f"GDELT article {url!r} is missing 'seendate'")
    source_record_id = sha256(url.encode("utf-8")).hexdigest()
    identity = "|".join(
        [
            "gdelt",
            query.topic_id,
            query.query_id,
            query.language or "",
            query.geography or "",
            source_record_id,
        ]
    )
    return AttentionRecord(
        record_id=sha256(identity.encode("utf-8")).hexdigest(),
        source="gdelt",
        source_record_id=source_record_id,
        topic_id=query.topic_id,
        query_id=query.query_id,
        query_expression=query.expression,
        url=url,
        title=article.get("title"),
        domain=article.get("domain"),
        published_at=parse_gdelt_datetime(seen_date),
        language=article.get("language") or query.language,
        source_country=article.get("sourcecountry"),
        geography=query.geography,
        collected_at=collected_at,
        metadata=dict(article),
    )


def plan_gdelt_windows(request: CollectionRequest) -> list[GDELTWindow]:
    """Create stable one-day root work units for a collection request."""
    windows: list[GDELTWindow] = []
    for topic in request.topics:
        for query in Query.from_topic(topic):
            for day in _date_range(request.start, request.end):
                windows.append(
                    GDELTWindow(
                        query=query,
                        start=datetime.combine(day, dt_time.min, tzinfo=timezone.utc),
                        end=datetime.combine(day, dt_time.max, tzinfo=timezone.utc),
                    )
                )
    return windows


class GDELTProvider(AttentionProvider):
    """Collect article-level observations from the GDELT DOC 2.0 API."""

    name = "gdelt"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_seconds: float = 30.0,
        request_interval_seconds: float = 6.0,
        max_records: int = 250,
        minimum_window: timedelta = timedelta(minutes=15),
        response_sink: Callable[[dict[str, Any]], None] | None = None,
        window_sink: WindowSink | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must be zero or greater")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must be zero or greater")
        if not 1 <= max_records <= 250:
            raise ValueError("max_records must be between 1 and GDELT's limit of 250")
        if minimum_window <= timedelta(0):
            raise ValueError("minimum_window must be greater than zero")
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "climate-attention/0.1 (+research collection)"},
            follow_redirects=True,
        )
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.request_interval_seconds = request_interval_seconds
        self.max_records = max_records
        self.minimum_window = minimum_window
        self.response_sink = response_sink
        self.window_sink = window_sink
        self.sleep = sleep
        self.monotonic = monotonic
        self._last_request_finished: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def collect(self, request: CollectionRequest) -> ProviderResult:
        return self.collect_windows(plan_gdelt_windows(request))

    def collect_windows(self, windows: list[GDELTWindow]) -> ProviderResult:
        """Collect explicit work units, enabling durable resumption by callers."""
        result = ProviderResult()
        collected_at = utc_now()
        for window in windows:
            records = self._collect_window(window, collected_at, result)
            result.records.extend(records)

        result.records = list({record.record_id: record for record in result.records}.values())
        return result

    def _collect_window(
        self,
        window: GDELTWindow,
        collected_at: datetime,
        result: ProviderResult,
    ) -> list[AttentionRecord]:
        self._emit_window("started", window)
        try:
            payload, attempts, status = self._request_json(
                window.query, window.start, window.end
            )
            raw_articles = payload.get("articles", [])
            if not isinstance(raw_articles, list):
                raise GDELTResponseError("GDELT response field 'articles' is not a list")
            if self.response_sink:
                self.response_sink(
                    {
                        "collected_at": collected_at.isoformat(),
                        "window_id": window.window_id,
                        "query": window.query.model_dump(mode="json"),
                        "start": window.start.isoformat(),
                        "end": window.end.isoformat(),
                        "response": payload,
                    }
                )

            if len(raw_articles) >= self.max_records:
                if window.end - window.start <= self.minimum_window:
                    raise GDELTResponseError(
                        f"GDELT result limit ({self.max_records}) reached for "
                        f"{window.query.query_id} in {window.start.isoformat()} to "
                        f"{window.end.isoformat()}; the interval cannot be split "
                        "further without risking incomplete data"
                    )
                midpoint = (window.start + (window.end - window.start) / 2).replace(
                    microsecond=0
                )
                children = [
                    GDELTWindow(
                        query=window.query,
                        start=window.start,
                        end=midpoint,
                        parent_window_id=window.window_id,
                    ),
                    GDELTWindow(
                        query=window.query,
                        start=midpoint + timedelta(seconds=1),
                        end=window.end,
                        parent_window_id=window.window_id,
                    ),
                ]
                log = self._request_log(
                    window,
                    status="split",
                    attempts=attempts,
                    records_returned=len(raw_articles),
                    http_status=status,
                )
                result.requests.append(log)
                self._emit_window("split", window, log, children=children)
                LOGGER.info(
                    "Splitting saturated GDELT window %s to %s for %s",
                    window.start,
                    window.end,
                    window.query.query_id,
                )
                left = self._collect_window(children[0], collected_at, result)
                right = self._collect_window(children[1], collected_at, result)
                return list(
                    {record.record_id: record for record in [*left, *right]}.values()
                )

            records: list[AttentionRecord] = []
            for article in raw_articles:
                if not isinstance(article, dict):
                    raise GDELTResponseError("GDELT article entries must be objects")
                records.append(parse_article(article, window.query, collected_at))
            log = self._request_log(
                window,
                status="success",
                attempts=attempts,
                records_returned=len(raw_articles),
                http_status=status,
            )
            result.requests.append(log)
            self._emit_window("success", window, log, records=records)
            return records
        except ProviderCollectionError:
            raise
        except _RequestFailed as exc:
            log = self._request_log(
                window,
                status="failed",
                attempts=exc.attempts,
                http_status=exc.http_status,
                error=str(exc),
            )
            result.requests.append(log)
            self._emit_window("failed", window, log)
            raise ProviderCollectionError(str(exc), result) from exc
        except Exception as exc:
            log = self._request_log(
                window,
                status="failed",
                attempts=1,
                error=str(exc),
            )
            result.requests.append(log)
            self._emit_window("failed", window, log)
            raise ProviderCollectionError(str(exc), result) from exc

    @staticmethod
    def _request_log(
        window: GDELTWindow,
        *,
        status: str,
        attempts: int,
        records_returned: int = 0,
        http_status: int | None = None,
        error: str | None = None,
    ) -> RequestLog:
        return RequestLog(
            window_id=window.window_id,
            parent_window_id=window.parent_window_id,
            query_id=window.query.query_id,
            topic_id=window.query.topic_id,
            start=window.start,
            end=window.end,
            status=status,
            attempts=attempts,
            records_returned=records_returned,
            http_status=http_status,
            error=error,
        )

    def _emit_window(
        self,
        event: str,
        window: GDELTWindow,
        log: RequestLog | None = None,
        *,
        records: list[AttentionRecord] | None = None,
        children: list[GDELTWindow] | None = None,
    ) -> None:
        if self.window_sink:
            self.window_sink(event, window, log, records or [], children or [])

    def _request_json(
        self, query: Query, start: datetime, end: datetime
    ) -> tuple[dict[str, Any], int, int]:
        params = {
            "query": build_gdelt_query(query),
            "mode": "artlist",
            "format": "json",
            "sort": "datedesc",
            "maxrecords": str(self.max_records),
            "startdatetime": start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end.strftime("%Y%m%d%H%M%S"),
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
                            "GDELT returned HTTP %s; retrying in %.1fs",
                            response.status_code,
                            delay,
                        )
                        self.sleep(delay)
                        continue
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise GDELTResponseError("GDELT returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise GDELTResponseError("GDELT JSON response is not an object")
                return payload, attempt, response.status_code
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                retryable = status is None or status == 429 or status >= 500
                if retryable and attempt <= self.max_retries:
                    delay = self.backoff_seconds * (2 ** (attempt - 1))
                    LOGGER.warning("GDELT request failed; retrying in %.1fs", delay)
                    self.sleep(delay)
                    continue
                raise _RequestFailed(
                    f"GDELT request failed after {attempt} attempt(s): {exc}",
                    attempt,
                    status,
                ) from exc
        raise _RequestFailed(
            f"GDELT request failed: {last_error}", self.max_retries + 1
        )

    def _wait_for_request_slot(self) -> None:
        if self._last_request_finished is None:
            return
        elapsed = self.monotonic() - self._last_request_finished
        remaining = self.request_interval_seconds - elapsed
        if remaining > 0:
            LOGGER.debug("Pacing GDELT requests: waiting %.1fs", remaining)
            self.sleep(remaining)


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _retry_delay(value: str | None, base: float, attempt: int) -> float:
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                target = parsedate_to_datetime(value)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                return max(0.0, (target - utc_now()).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return base * (2 ** (attempt - 1))
