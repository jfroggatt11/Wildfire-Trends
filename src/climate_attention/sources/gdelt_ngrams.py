"""BigQuery-backed GDELT Web NGrams 3.0 trend collection."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from datetime import date, datetime, time as dt_time, timedelta, timezone
from hashlib import sha256
from typing import Any, Protocol

from ..config import Country
from ..models import (
    CollectionRequest,
    DailyTrend,
    Query,
    RequestLog,
    TrendProviderResult,
    utc_now,
)
from .base import ProviderCollectionError, ProviderUnavailableError
from .gdelt import GDELTWindow


LOGGER = logging.getLogger(__name__)
SOURCE = "gdelt_ngrams"
DEFAULT_NGRAM_TABLE = "gdelt-bq.gdeltv2.webngrams"
DEFAULT_COVERAGE_TABLE = "gdelt-bq.gdeltv2.gal"
DEFAULT_DOMAIN_COUNTRY_TABLE = (
    "gdelt-bq.gdeltv2.domainsbycountry_alllangs_april2015"
)
_TABLE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class BigQueryExecutor(Protocol):
    def estimate(self, sql: str, parameters: dict[str, Any]) -> int: ...

    def query(
        self,
        sql: str,
        parameters: dict[str, Any],
        *,
        maximum_bytes_billed: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...


NGramWindowSink = Callable[
    [str, GDELTWindow, RequestLog | None, list[DailyTrend], list[GDELTWindow]],
    None,
]


def _literal_phrase(expression: str) -> str:
    value = expression.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    if not value:
        raise ValueError("NGram phrase must not be empty")
    return value


def topic_phrases(request: CollectionRequest) -> dict[str, list[str]]:
    """Extract literal phrases while rejecting provider-specific query dimensions."""
    values: dict[str, list[str]] = {}
    for topic in request.topics:
        if topic.include_terms or topic.exclude_terms or topic.languages or topic.geographies:
            raise ValueError(
                f"NGram topic {topic.id!r} must contain literal query expressions "
                "without GDELT include/exclude or dimension filters"
            )
        phrases: list[str] = []
        for spec in topic.queries:
            if not spec.enabled:
                continue
            if any(
                item is not None
                for item in (
                    spec.include_terms,
                    spec.exclude_terms,
                    spec.languages,
                    spec.geographies,
                )
            ):
                raise ValueError(
                    f"NGram query {spec.id!r} must be one literal expression"
                )
            phrases.append(_literal_phrase(spec.expression))
        if phrases:
            values[topic.id] = list(dict.fromkeys(phrases))
    return values


def plan_ngram_windows(
    request: CollectionRequest, *, window_days: int = 366
) -> tuple[list[GDELTWindow], dict[str, list[str]]]:
    if window_days < 1:
        raise ValueError("NGram window must be at least one day")
    phrases_by_topic = topic_phrases(request)
    windows: list[GDELTWindow] = []
    for topic in request.topics:
        phrases = phrases_by_topic.get(topic.id)
        if not phrases:
            continue
        expression = " OR ".join(f'"{phrase}"' for phrase in phrases)
        current = request.start
        while current <= request.end:
            chunk_end = min(request.end, current + timedelta(days=window_days - 1))
            windows.append(
                GDELTWindow(
                    query=Query(
                        topic_id=topic.id,
                        query_id="topic_distinct_urls",
                        expression=expression,
                    ),
                    start=datetime.combine(current, dt_time.min, tzinfo=timezone.utc),
                    end=datetime.combine(chunk_end, dt_time.max, tzinfo=timezone.utc),
                )
            )
            current = chunk_end + timedelta(days=1)
    return windows, phrases_by_topic


def build_ngram_sql(
    *,
    phrases: list[str],
    ngram_table: str = DEFAULT_NGRAM_TABLE,
    coverage_table: str = DEFAULT_COVERAGE_TABLE,
    domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE,
    include_denominator: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Build parameterized SQL for deduplicated matched URL counts."""
    for table in (ngram_table, coverage_table, domain_country_table):
        if not _TABLE_PATTERN.fullmatch(table):
            raise ValueError(f"invalid BigQuery table identifier: {table!r}")
    if not phrases:
        raise ValueError("at least one NGram phrase is required")

    clauses: list[str] = []
    parameters: dict[str, Any] = {}
    for index, phrase in enumerate(phrases):
        words = phrase.split()
        if not words:
            raise ValueError("NGram phrase must contain a word")
        anchor = words[(len(words) - 1) // 2].casefold()
        escaped = r"\s+".join(re.escape(word.casefold()) for word in words)
        parameters[f"anchor_variants_{index}"] = _anchor_variants(
            anchor, single_word=len(words) == 1
        )
        parameters[f"pattern_{index}"] = (
            rf"(^|[^\p{{L}}\p{{N}}]){escaped}([^\p{{L}}\p{{N}}]|$)"
        )
        clauses.append(
            "("
            f"ngram IN UNNEST(@anchor_variants_{index}) AND "
            "REGEXP_CONTAINS(LOWER(CONCAT(COALESCE(pre, ''), ' ', ngram, "
            f"' ', COALESCE(post, ''))), @pattern_{index})"
            ")"
        )
    phrase_filter = "\n      OR ".join(clauses)

    coverage_ctes = ""
    monitored_expression = "CAST(NULL AS INT64)"
    coverage_join = ""
    if include_denominator:
        coverage_ctes = f""",
coverage_urls AS (
  SELECT DISTINCT DATE(date) AS day, url, LOWER(NET.HOST(url)) AS host
  FROM `{coverage_table}`
  WHERE DATE(date) BETWEEN @start_date AND @end_date
),
coverage_attributed AS (
  SELECT day, url, domains.country_label
  FROM coverage_urls
  JOIN unambiguous_domains AS domains
    ON host = domains.domain OR ENDS_WITH(host, CONCAT('.', domains.domain))
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY day, url ORDER BY LENGTH(domains.domain) DESC
  ) = 1
),
country_coverage AS (
  SELECT day, countries.country_id, COUNT(DISTINCT url) AS monitored_count
  FROM coverage_attributed
  JOIN requested_countries AS countries USING (country_label)
  GROUP BY day, country_id
)"""
        monitored_expression = "COALESCE(coverage.monitored_count, 0)"
        coverage_join = (
            "LEFT JOIN country_coverage AS coverage USING (day, country_id)"
        )

    sql = f"""
WITH requested_countries AS (
  SELECT country_id, country_label
  FROM UNNEST(@country_ids) AS country_id WITH OFFSET AS position
  JOIN UNNEST(@country_labels) AS country_label WITH OFFSET AS label_position
    ON position = label_position
),
unambiguous_domains AS (
  SELECT LOWER(Domain) AS domain, ANY_VALUE(CountryHumanName) AS country_label
  FROM `{domain_country_table}`
  WHERE Domain IS NOT NULL AND CountryHumanName IS NOT NULL
  GROUP BY domain
  HAVING COUNT(DISTINCT CountryHumanName) = 1
),
matched_urls AS (
  SELECT DISTINCT DATE(date) AS day, url, LOWER(NET.HOST(url)) AS host
  FROM `{ngram_table}`
  WHERE DATE(date) BETWEEN @start_date AND @end_date
    AND (
      {phrase_filter}
    )
),
matched_attributed AS (
  SELECT day, url, domains.country_label
  FROM matched_urls
  JOIN unambiguous_domains AS domains
    ON host = domains.domain OR ENDS_WITH(host, CONCAT('.', domains.domain))
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY day, url ORDER BY LENGTH(domains.domain) DESC
  ) = 1
),
mapping_stats AS (
  SELECT
    (SELECT COUNT(*) FROM matched_urls) AS total_matched_urls,
    (SELECT COUNT(*) FROM matched_attributed) AS attributed_matched_urls
),
country_matches AS (
  SELECT day, countries.country_id, COUNT(DISTINCT url) AS matched_count
  FROM matched_attributed
  JOIN requested_countries AS countries USING (country_label)
  GROUP BY day, country_id
){coverage_ctes},
calendar AS (
  SELECT day
  FROM UNNEST(GENERATE_DATE_ARRAY(@start_date, @end_date)) AS day
)
SELECT
  calendar.day,
  countries.country_id,
  COALESCE(matches.matched_count, 0) AS matched_count,
  {monitored_expression} AS monitored_count,
  mapping_stats.total_matched_urls,
  mapping_stats.attributed_matched_urls
FROM calendar
CROSS JOIN requested_countries AS countries
CROSS JOIN mapping_stats
LEFT JOIN country_matches AS matches USING (day, country_id)
{coverage_join}
ORDER BY day, country_id
""".strip()
    return sql, parameters


def _anchor_variants(anchor: str, *, single_word: bool) -> list[str]:
    """Return a bounded cluster-friendly pilot anchor set."""
    cases = list(dict.fromkeys((anchor, anchor.capitalize())))
    # Multiword phrases anchor on a non-final word. Unpunctuated lower/title forms
    # capture ordinary prose while keeping the BigQuery pilot affordable. Broader
    # punctuation/case recall is measured later as a sensitivity analysis.
    prefixes = ("",)
    suffixes = ("", ".", ",") if single_word else ("",)
    return list(
        dict.fromkeys(
            f"{prefix}{value}{suffix}"
            for value in cases
            for prefix in prefixes
            for suffix in suffixes
        )
    )


def prepare_ngram_query(
    window: GDELTWindow,
    *,
    phrases: list[str],
    country_labels: dict[str, str],
    ngram_table: str = DEFAULT_NGRAM_TABLE,
    coverage_table: str = DEFAULT_COVERAGE_TABLE,
    domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE,
    include_denominator: bool = False,
) -> tuple[str, dict[str, Any]]:
    sql, phrase_parameters = build_ngram_sql(
        phrases=phrases,
        ngram_table=ngram_table,
        coverage_table=coverage_table,
        domain_country_table=domain_country_table,
        include_denominator=include_denominator,
    )
    return sql, {
        **phrase_parameters,
        "start_date": window.start.date(),
        "end_date": window.end.date(),
        "country_ids": list(country_labels),
        "country_labels": list(country_labels.values()),
    }


def estimate_ngram_windows(
    windows: list[GDELTWindow],
    *,
    executor: BigQueryExecutor,
    country_labels: dict[str, str],
    phrases_by_topic: dict[str, list[str]],
    include_denominator: bool = False,
) -> list[dict[str, Any]]:
    estimates: list[dict[str, Any]] = []
    for window in windows:
        phrases = phrases_by_topic[window.query.topic_id]
        sql, parameters = prepare_ngram_query(
            window,
            phrases=phrases,
            country_labels=country_labels,
            include_denominator=include_denominator,
        )
        estimates.append(
            {
                "window_id": window.window_id,
                "topic_id": window.query.topic_id,
                "start": window.start.date(),
                "end": window.end.date(),
                "estimated_bytes_processed": executor.estimate(sql, parameters),
            }
        )
    return estimates


class GoogleBigQueryExecutor:
    """Thin lazy wrapper so core installation and unit tests do not require the SDK."""

    def __init__(self, *, project: str, location: str = "US") -> None:
        try:
            from google.cloud import bigquery
            from google.auth.exceptions import DefaultCredentialsError
        except ImportError as exc:
            raise ProviderUnavailableError(
                "GDELT NGrams requires the BigQuery extra; install with "
                "python -m pip install -e '.[bigquery]'"
            ) from exc
        self.bigquery = bigquery
        try:
            self.client = bigquery.Client(project=project, location=location)
        except DefaultCredentialsError as exc:
            raise ProviderUnavailableError(
                "BigQuery Application Default Credentials are unavailable; run "
                "gcloud auth application-default login"
            ) from exc
        self.location = location

    def _job_config(
        self,
        parameters: dict[str, Any],
        *,
        dry_run: bool,
        maximum_bytes_billed: int | None = None,
    ) -> Any:
        bigquery = self.bigquery
        query_parameters: list[Any] = []
        for name, value in parameters.items():
            if isinstance(value, list):
                query_parameters.append(
                    bigquery.ArrayQueryParameter(name, "STRING", value)
                )
            elif isinstance(value, date):
                query_parameters.append(
                    bigquery.ScalarQueryParameter(name, "DATE", value)
                )
            else:
                query_parameters.append(
                    bigquery.ScalarQueryParameter(name, "STRING", value)
                )
        options: dict[str, Any] = {
            "query_parameters": query_parameters,
            "dry_run": dry_run,
            "use_query_cache": not dry_run,
        }
        if maximum_bytes_billed is not None:
            options["maximum_bytes_billed"] = maximum_bytes_billed
        return bigquery.QueryJobConfig(
            **options
        )

    def estimate(self, sql: str, parameters: dict[str, Any]) -> int:
        job = self.client.query(
            sql,
            job_config=self._job_config(parameters, dry_run=True),
            location=self.location,
        )
        return int(job.total_bytes_processed or 0)

    def query(
        self,
        sql: str,
        parameters: dict[str, Any],
        *,
        maximum_bytes_billed: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        job = self.client.query(
            sql,
            job_config=self._job_config(
                parameters,
                dry_run=False,
                maximum_bytes_billed=maximum_bytes_billed,
            ),
            location=self.location,
        )
        rows = [dict(row.items()) for row in job.result()]
        return rows, {
            "job_id": job.job_id,
            "total_bytes_processed": int(job.total_bytes_processed or 0),
            "total_bytes_billed": int(job.total_bytes_billed or 0),
            "cache_hit": bool(job.cache_hit),
        }


class GDELTNGramsProvider:
    name = SOURCE

    def __init__(
        self,
        *,
        billing_project: str,
        country_labels: dict[str, str],
        topic_phrases: dict[str, list[str]],
        maximum_bytes_billed: int,
        location: str = "US",
        ngram_table: str = DEFAULT_NGRAM_TABLE,
        coverage_table: str = DEFAULT_COVERAGE_TABLE,
        domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE,
        include_denominator: bool = False,
        executor: BigQueryExecutor | None = None,
        response_sink: Callable[[dict[str, Any]], None] | None = None,
        timeline_sink: NGramWindowSink | None = None,
        **_: Any,
    ) -> None:
        if not billing_project:
            raise ValueError("a BigQuery billing project is required")
        if maximum_bytes_billed <= 0:
            raise ValueError("maximum_bytes_billed must be greater than zero")
        self.billing_project = billing_project
        self.country_labels = country_labels
        self.topic_phrases = topic_phrases
        self.maximum_bytes_billed = maximum_bytes_billed
        self.ngram_table = ngram_table
        self.coverage_table = coverage_table
        self.domain_country_table = domain_country_table
        self.include_denominator = include_denominator
        self.executor = executor or GoogleBigQueryExecutor(
            project=billing_project, location=location
        )
        self.response_sink = response_sink
        self.timeline_sink = timeline_sink

    def __enter__(self) -> "GDELTNGramsProvider":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def collect_windows(self, windows: list[GDELTWindow]) -> TrendProviderResult:
        result = TrendProviderResult()
        for window in windows:
            self._emit("started", window)
            try:
                trends = self._collect_window(window)
                log = self._log(window, "success", len(trends))
                result.requests.append(log)
                result.trends.extend(trends)
                self._emit("success", window, log, trends)
            except Exception as exc:
                log = self._log(window, "failed", 0, error=str(exc))
                result.requests.append(log)
                self._emit("failed", window, log, [])
                raise ProviderCollectionError(str(exc), result) from exc
        return result

    def _collect_window(self, window: GDELTWindow) -> list[DailyTrend]:
        phrases = self.topic_phrases.get(window.query.topic_id)
        if not phrases:
            raise ValueError(f"missing NGram phrases for topic {window.query.topic_id!r}")
        sql, parameters = prepare_ngram_query(
            window,
            phrases=phrases,
            country_labels=self.country_labels,
            ngram_table=self.ngram_table,
            coverage_table=self.coverage_table,
            domain_country_table=self.domain_country_table,
            include_denominator=self.include_denominator,
        )
        estimated_bytes = self.executor.estimate(sql, parameters)
        if estimated_bytes > self.maximum_bytes_billed:
            raise ValueError(
                f"BigQuery dry run estimated {estimated_bytes} bytes, above the "
                f"per-window cap of {self.maximum_bytes_billed} bytes"
            )
        rows, job = self.executor.query(
            sql,
            parameters,
            maximum_bytes_billed=self.maximum_bytes_billed,
        )
        collected_at = utc_now()
        if self.response_sink:
            self.response_sink(
                {
                    "collected_at": collected_at.isoformat(),
                    "window_id": window.window_id,
                    "source": SOURCE,
                    "query": window.query.model_dump(mode="json"),
                    "phrases": phrases,
                    "start": window.start.isoformat(),
                    "end": window.end.isoformat(),
                    "estimated_bytes_processed": estimated_bytes,
                    "job": job,
                    "response": [_json_safe_row(row) for row in rows],
                }
            )
        trends = parse_ngram_rows(
            rows=rows,
            window=window,
            phrases=phrases,
            estimated_bytes=estimated_bytes,
            job=job,
            collected_at=collected_at,
            include_denominator=self.include_denominator,
        )
        expected = (
            (window.end.date() - window.start.date()).days + 1
        ) * len(self.country_labels)
        if len(trends) != expected:
            raise ValueError(
                f"BigQuery returned {len(trends)} country-day rows; expected {expected}"
            )
        returned_countries = {trend.geography for trend in trends}
        if returned_countries != set(self.country_labels):
            raise ValueError("BigQuery returned unexpected country dimensions")
        return trends
    @staticmethod
    def _log(
        window: GDELTWindow,
        status: str,
        records: int,
        *,
        error: str | None = None,
    ) -> RequestLog:
        return RequestLog(
            window_id=window.window_id,
            query_id=window.query.query_id,
            topic_id=window.query.topic_id,
            start=window.start,
            end=window.end,
            status=status,
            attempts=1,
            records_returned=records,
            error=error,
        )

    def _emit(
        self,
        event: str,
        window: GDELTWindow,
        log: RequestLog | None = None,
        trends: list[DailyTrend] | None = None,
    ) -> None:
        if self.timeline_sink:
            self.timeline_sink(event, window, log, trends or [], [])


def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert BigQuery temporal scalars before writing the raw JSONL envelope."""
    return {
        key: value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in row.items()
    }


def parse_ngram_rows(
    *,
    rows: Iterable[dict[str, Any]],
    window: GDELTWindow,
    phrases: list[str],
    estimated_bytes: int,
    job: dict[str, Any],
    collected_at: datetime,
    include_denominator: bool = False,
) -> list[DailyTrend]:
    trends: list[DailyTrend] = []
    seen: set[tuple[date, str]] = set()
    for row in rows:
        day = row.get("day")
        if isinstance(day, datetime):
            day = day.date()
        if not isinstance(day, date):
            day = date.fromisoformat(str(day))
        country_id = str(row["country_id"])
        key = (day, country_id)
        if key in seen:
            raise ValueError(f"duplicate NGram aggregate row for {country_id} {day}")
        seen.add(key)
        matched = int(row["matched_count"])
        raw_monitored = row.get("monitored_count")
        monitored = int(raw_monitored) if raw_monitored is not None else None
        total_matched = int(row.get("total_matched_urls", 0))
        attributed_matched = int(row.get("attributed_matched_urls", 0))
        if matched < 0 or (monitored is not None and monitored < 0):
            raise ValueError("NGram counts must be non-negative")
        share = matched / monitored if monitored else None
        identity = "|".join(
            [
                "gdelt-ngrams-v1",
                window.query.topic_id,
                window.query.query_id,
                country_id,
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
                query_expression=window.query.expression,
                geography=country_id,
                matched_count=matched,
                country_monitored_count=monitored,
                country_attention_share=share,
                collected_at=collected_at,
                metadata={
                    "collection_mode": "webngrams_distinct_urls",
                    "phrases": phrases,
                    "deduplication_scope": "distinct_url_per_day_topic",
                    "anchor_variant_policy": (
                        "unpunctuated_lower_and_title_case_pilot"
                    ),
                    "country_attribution": (
                        "gdelt_domainsbycountry_alllangs_april2015_longest_suffix"
                    ),
                    "country_map_limitations": (
                        "2015 snapshot; ambiguous and unmapped domains excluded"
                    ),
                    "all_country_total_matched_urls": total_matched,
                    "all_country_attributed_matched_urls": attributed_matched,
                    "all_country_url_attribution_rate": (
                        attributed_matched / total_matched
                        if total_matched
                        else None
                    ),
                    "denominator_scope": (
                        "distinct_gal_urls_mapped_to_country"
                        if include_denominator
                        else None
                    ),
                    "estimated_bytes_processed": estimated_bytes,
                    "bigquery_job": job,
                },
            )
        )
    return trends
