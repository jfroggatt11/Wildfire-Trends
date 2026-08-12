"""Unofficial Google Trends collection through pytrends-modern's HTTP client."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, time as dt_time, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from numbers import Real
from statistics import median
from typing import Any

from ..config import Country
from ..models import (
    CollectionRequest,
    DailyTrend,
    Query,
    RequestLog,
    TrendProviderResult,
    utc_now,
)
from .base import AttentionProvider, ProviderCollectionError, ProviderUnavailableError
from .gdelt import GDELTWindow


LOGGER = logging.getLogger(__name__)
SOURCE = "google_trends_unofficial"


class GoogleTrendsResponseError(RuntimeError):
    """Raised when pytrends-modern returns an unusable result."""


class _RequestFailed(RuntimeError):
    def __init__(self, message: str, attempts: int, http_status: int | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.http_status = http_status


GoogleWindowSink = Callable[
    [str, GDELTWindow, RequestLog | None, list[DailyTrend], list[GDELTWindow]],
    None,
]


def _literal_search_term(expression: str) -> str:
    """Remove GDELT-style outer quotes while preserving the literal phrase."""
    value = expression.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    if not value:
        raise ValueError("Google Trends search term must not be empty")
    return value


def resolve_google_geo(country: Country) -> str:
    """Resolve a configured country to Google's ISO-3166-1 alpha-2 geo code."""
    if country.google_geo:
        return country.google_geo

    aliases = {
        "bolivia": "BO",
        "brunei": "BN",
        "cape verde": "CV",
        "democratic republic of the congo": "CD",
        "ivory coast": "CI",
        "iran": "IR",
        "laos": "LA",
        "moldova": "MD",
        "north korea": "KP",
        "kosovo": "XK",
        "micronesia": "FM",
        "palestine": "PS",
        "russia": "RU",
        "south korea": "KR",
        "syria": "SY",
        "taiwan": "TW",
        "tanzania": "TZ",
        "turkey": "TR",
        "united states": "US",
        "vatican city": "VA",
        "venezuela": "VE",
        "vietnam": "VN",
    }
    mapped = aliases.get(country.label.casefold())
    if mapped:
        return mapped
    try:
        import pycountry

        return str(pycountry.countries.lookup(country.label).alpha_2)
    except (ImportError, LookupError, AttributeError) as exc:
        raise ValueError(
            f"cannot resolve Google geo code for {country.id!r} ({country.label!r}); "
            "set google_geo explicitly in the country configuration"
        ) from exc


def plan_google_trends_windows(
    request: CollectionRequest, countries: list[Country]
) -> tuple[list[GDELTWindow], dict[str, str]]:
    """Plan one independently scaled request per query, country, and date range."""
    country_geos = {country.id: resolve_google_geo(country) for country in countries}
    windows: list[GDELTWindow] = []
    for topic in request.topics:
        for configured_query in Query.from_topic(topic):
            if configured_query.include_terms or configured_query.exclude_terms:
                raise ValueError(
                    f"Google Trends query {configured_query.query_id!r} cannot use "
                    "include_terms or exclude_terms; configure one literal search "
                    "term per query"
                )
            if configured_query.language or configured_query.geography:
                raise ValueError(
                    f"Google Trends query {configured_query.query_id!r} cannot use "
                    "topic language/geography dimensions; use --countries and the "
                    "provider locale options"
                )
            _literal_search_term(configured_query.expression)
            for country in countries:
                query = configured_query.model_copy(
                    update={"geography": country.id, "geographies": []}
                )
                windows.append(
                    GDELTWindow(
                        query=query,
                        start=datetime.combine(
                            request.start, dt_time.min, tzinfo=timezone.utc
                        ),
                        end=datetime.combine(
                            request.end, dt_time.max, tzinfo=timezone.utc
                        ),
                    )
                )
    return windows, country_geos


def _worldwide_windows(request: CollectionRequest) -> list[GDELTWindow]:
    windows: list[GDELTWindow] = []
    for topic in request.topics:
        for query in Query.from_topic(topic):
            if query.include_terms or query.exclude_terms or query.language or query.geography:
                raise ValueError(
                    "worldwide Google Trends collection requires literal queries "
                    "without provider dimensions"
                )
            windows.append(
                GDELTWindow(
                    query=query,
                    start=datetime.combine(request.start, dt_time.min, tzinfo=timezone.utc),
                    end=datetime.combine(request.end, dt_time.max, tzinfo=timezone.utc),
                )
            )
    return windows


class GoogleTrendsUnofficialProvider(AttentionProvider):
    """Collect normalized interest indices without browser or account automation."""

    name = SOURCE

    def __init__(
        self,
        *,
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
        country_geos: dict[str, str] | None = None,
        category: int = 0,
        gprop: str = "",
        hl: str = "en-US",
        tz: int = 0,
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff_seconds: float = 60.0,
        request_interval_seconds: float = 30.0,
        response_sink: Callable[[dict[str, Any]], None] | None = None,
        timeline_sink: GoogleWindowSink | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        **_: Any,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        if backoff_seconds < 0 or request_interval_seconds < 0:
            raise ValueError("pacing values must be zero or greater")
        if category < 0:
            raise ValueError("category must be zero or greater")
        if gprop not in {"", "images", "news", "youtube", "froogle"}:
            raise ValueError(f"unsupported Google Trends property: {gprop!r}")
        self._client = client
        self._owns_client = client is None
        self._client_factory = client_factory or _default_client_factory
        self.country_geos = country_geos or {}
        self.category = category
        self.gprop = gprop
        self.hl = hl
        self.tz = tz
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.request_interval_seconds = request_interval_seconds
        self.response_sink = response_sink
        self.timeline_sink = timeline_sink
        self.sleep = sleep
        self.monotonic = monotonic
        self._last_request_finished: float | None = None

    def close(self) -> None:
        if not self._owns_client or self._client is None:
            return
        session = getattr(self._client, "session", None)
        close = getattr(session, "close", None)
        if callable(close):
            close()

    def collect(self, request: CollectionRequest) -> TrendProviderResult:
        return self.collect_windows(_worldwide_windows(request))

    def collect_windows(self, windows: list[GDELTWindow]) -> TrendProviderResult:
        result = TrendProviderResult()
        for window in windows:
            trends = self._collect_window(window, result)
            result.trends.extend(trends)
        return result

    def _collect_window(
        self, window: GDELTWindow, result: TrendProviderResult
    ) -> list[DailyTrend]:
        self._emit("started", window)
        collected_at = utc_now()
        term = _literal_search_term(window.query.expression)
        geo = self._geo_for(window.query.geography)
        timeframe = f"{window.start.date().isoformat()} {window.end.date().isoformat()}"
        scaling_group_id = _scaling_group_id(window, term, geo, self.category, self.gprop)
        try:
            frame, attempts = self._request_frame(term, timeframe, geo)
            raw_rows = _frame_rows(frame)
            if self.response_sink:
                self.response_sink(
                    {
                        "collected_at": collected_at.isoformat(),
                        "window_id": window.window_id,
                        "source": SOURCE,
                        "library": _library_version(),
                        "query": window.query.model_dump(mode="json"),
                        "request": {
                            "keywords": [term],
                            "timeframe": timeframe,
                            "geo": geo,
                            "category": self.category,
                            "property": self.gprop or "web",
                            "hl": self.hl,
                            "tz": self.tz,
                            "scaling_group_id": scaling_group_id,
                        },
                        "response": raw_rows,
                    }
                )
            trends = _parse_frame(
                frame=frame,
                term=term,
                window=window,
                geo=geo,
                category=self.category,
                gprop=self.gprop,
                scaling_group_id=scaling_group_id,
                collected_at=collected_at,
            )
            log = self._log(
                window,
                status="success",
                attempts=attempts,
                records_returned=len(trends),
                http_status=200,
            )
            result.requests.append(log)
            self._emit("success", window, log, trends)
            return trends
        except _RequestFailed as exc:
            log = self._log(
                window,
                status="failed",
                attempts=exc.attempts,
                http_status=exc.http_status,
                error=str(exc),
            )
            result.requests.append(log)
            self._emit("failed", window, log)
            raise ProviderCollectionError(str(exc), result) from exc
        except Exception as exc:
            log = self._log(window, status="failed", attempts=1, error=str(exc))
            result.requests.append(log)
            self._emit("failed", window, log)
            raise ProviderCollectionError(str(exc), result) from exc

    def _request_frame(self, term: str, timeframe: str, geo: str) -> tuple[Any, int]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                self._wait_for_request_slot()
                try:
                    client = self._get_client()
                    client.build_payload(
                        [term],
                        cat=self.category,
                        timeframe=timeframe,
                        geo=geo,
                        gprop=self.gprop,
                    )
                    return client.interest_over_time(), attempt
                finally:
                    self._last_request_finished = self.monotonic()
            except ProviderUnavailableError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt <= self.max_retries:
                    delay = self.backoff_seconds * (2 ** (attempt - 1))
                    LOGGER.warning(
                        "Google Trends request failed; retrying in %.1fs", delay
                    )
                    self.sleep(delay)
                    continue
                status = _exception_http_status(exc)
                raise _RequestFailed(
                    f"Google Trends request failed after {attempt} attempt(s): {exc}",
                    attempt,
                    status,
                ) from exc
        raise _RequestFailed(
            f"Google Trends request failed: {last_error}", self.max_retries + 1
        )

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(
                hl=self.hl,
                tz=self.tz,
                timeout=(self.timeout, self.timeout),
                retries=0,
                backoff_factor=0,
                rotate_user_agent=False,
            )
        return self._client

    def _geo_for(self, geography: str | None) -> str:
        if geography is None:
            return ""
        try:
            return self.country_geos[geography]
        except KeyError as exc:
            raise ValueError(
                f"missing Google geo mapping for country {geography!r}"
            ) from exc

    def _wait_for_request_slot(self) -> None:
        if self._last_request_finished is None:
            return
        remaining = (
            self.request_interval_seconds
            - (self.monotonic() - self._last_request_finished)
        )
        if remaining > 0:
            LOGGER.debug("Pacing Google Trends requests: waiting %.1fs", remaining)
            self.sleep(remaining)

    @staticmethod
    def _log(
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

    def _emit(
        self,
        event: str,
        window: GDELTWindow,
        log: RequestLog | None = None,
        observations: list[DailyTrend] | None = None,
    ) -> None:
        if self.timeline_sink:
            self.timeline_sink(event, window, log, observations or [], [])


# Compatibility name for callers that imported the earlier placeholder.
GoogleTrendsProvider = GoogleTrendsUnofficialProvider


def _default_client_factory(**kwargs: Any) -> Any:
    try:
        from pytrends_modern.request import TrendReq
    except ImportError as exc:
        raise ProviderUnavailableError(
            "google_trends_unofficial requires pytrends-modern; install the "
            "project dependencies before collecting"
        ) from exc
    return TrendReq(**kwargs)


def _library_version() -> str | None:
    try:
        return version("pytrends-modern")
    except PackageNotFoundError:
        return None


def _frame_rows(frame: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        values = {str(key): _json_value(value) for key, value in row.items()}
        rows.append({"date": _coerce_date(index).isoformat(), **values})
    return rows


def _parse_frame(
    *,
    frame: Any,
    term: str,
    window: GDELTWindow,
    geo: str,
    category: int,
    gprop: str,
    scaling_group_id: str,
    collected_at: datetime,
) -> list[DailyTrend]:
    columns = [str(column) for column in frame.columns]
    value_column = term
    if value_column not in columns:
        candidates = [column for column in columns if column != "isPartial"]
        if len(candidates) != 1:
            raise GoogleTrendsResponseError(
                f"Google Trends response lacks an unambiguous {term!r} column"
            )
        value_column = candidates[0]

    parsed: list[tuple[date, float, bool]] = []
    seen: set[date] = set()
    for index, row in frame.iterrows():
        day = _coerce_date(index)
        if day in seen:
            raise GoogleTrendsResponseError(
                f"Google Trends returned duplicate date {day.isoformat()}"
            )
        seen.add(day)
        raw_value = row[value_column]
        if not isinstance(raw_value, Real):
            raise GoogleTrendsResponseError(
                f"Google Trends returned non-numeric interest value {raw_value!r}"
            )
        value = float(raw_value)
        if not 0 <= value <= 100:
            raise GoogleTrendsResponseError(
                f"Google Trends interest value is outside 0..100: {value}"
            )
        raw_partial = row.get("isPartial", False)
        is_partial = bool(raw_partial) if raw_partial == raw_partial else False
        parsed.append((day, value, is_partial))

    parsed.sort(key=lambda item: item[0])
    resolution = _resolution([item[0] for item in parsed])
    trends: list[DailyTrend] = []
    for day, value, is_partial in parsed:
        identity = "|".join(
            [
                "google-trends-unofficial-v1",
                scaling_group_id,
                window.query.topic_id,
                window.query.query_id,
                window.query.geography or "",
                day.isoformat(),
            ]
        )
        trends.append(
            DailyTrend(
                record_id=sha256(identity.encode("utf-8")).hexdigest(),
                date=day,
                source=SOURCE,
                topic_id=window.query.topic_id,
                query_id=window.query.query_id,
                query_expression=term,
                geography=window.query.geography,
                attention_index=value,
                collected_at=collected_at,
                metadata={
                    "provider_geo": geo or "worldwide",
                    "category": category,
                    "property": gprop or "web",
                    "requested_start": window.start.date().isoformat(),
                    "requested_end": window.end.date().isoformat(),
                    "time_resolution": resolution,
                    "is_partial": is_partial,
                    "scaling_group_id": scaling_group_id,
                    "normalization_scope": "google_trends_request_0_to_100",
                    "independently_scaled": True,
                },
            )
        )
    return trends


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    to_datetime = getattr(value, "to_pydatetime", None)
    if callable(to_datetime):
        return to_datetime().date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise GoogleTrendsResponseError(
            f"Google Trends returned invalid date index {value!r}"
        ) from exc


def _resolution(days: list[date]) -> str:
    if len(days) < 2:
        return "single_point" if days else "empty"
    gaps = [(right - left).days for left, right in zip(days, days[1:])]
    typical = median(gaps)
    if typical == 1:
        return "daily"
    if 6 <= typical <= 8:
        return "weekly"
    if 27 <= typical <= 32:
        return "monthly"
    return "irregular"


def _scaling_group_id(
    window: GDELTWindow, term: str, geo: str, category: int, gprop: str
) -> str:
    identity = "|".join(
        [
            "google-trends-scaling-v1",
            term,
            geo,
            str(category),
            gprop,
            window.start.date().isoformat(),
            window.end.date().isoformat(),
        ]
    )
    return sha256(identity.encode("utf-8")).hexdigest()


def _exception_http_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return str(value)
