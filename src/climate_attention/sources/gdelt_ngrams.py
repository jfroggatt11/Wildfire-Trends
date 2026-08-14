"""BigQuery-backed GDELT Web NGrams 3.0 trend collection."""

from __future__ import annotations

import json
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
    PoliticalArticleSample,
    Query,
    RequestLog,
    TrendProviderResult,
    utc_now,
)
from .base import ProviderCollectionError, ProviderUnavailableError
from .gdelt import GDELTWindow


LOGGER = logging.getLogger(__name__)
SOURCE = "gdelt_ngrams"
BATCH_TOPIC_ID = "ngram_topic_batch"
BATCH_QUERY_ID = "topics_distinct_urls"
TOPIC_QUERY_ID = "topic_distinct_urls"
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


def build_country_audit_sql(
    *, domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE
) -> str:
    """Return a small query that audits exact labels against the domain map."""
    if not _TABLE_PATTERN.fullmatch(domain_country_table):
        raise ValueError(f"invalid BigQuery table identifier: {domain_country_table!r}")
    return f"""
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
available_country_labels AS (
  SELECT DISTINCT country_label FROM unambiguous_domains
),
label_suggestions AS (
  SELECT
    countries.country_id,
    ARRAY_AGG(
      candidate.country_label
      ORDER BY EDIT_DISTANCE(
        LOWER(countries.country_label), LOWER(candidate.country_label)
      ), candidate.country_label
      LIMIT 3
    ) AS suggested_labels
  FROM requested_countries AS countries
  CROSS JOIN available_country_labels AS candidate
  GROUP BY countries.country_id
)
SELECT
  countries.country_id,
  countries.country_label,
  COUNT(domains.domain) AS mapped_domain_count,
  ARRAY_AGG(domains.domain IGNORE NULLS ORDER BY domains.domain LIMIT 5)
    AS sample_domains,
  ANY_VALUE(suggestions.suggested_labels) AS suggested_labels
FROM requested_countries AS countries
JOIN label_suggestions AS suggestions USING (country_id)
LEFT JOIN unambiguous_domains AS domains USING (country_label)
GROUP BY country_id, country_label
ORDER BY country_id
""".strip()


def audit_country_mapping(
    *,
    executor: BigQueryExecutor,
    country_labels: dict[str, str],
    maximum_bytes_billed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = build_country_audit_sql()
    parameters = {
        "country_ids": list(country_labels),
        "country_labels": list(country_labels.values()),
    }
    estimate = executor.estimate(sql, parameters)
    if estimate > maximum_bytes_billed:
        raise ValueError(
            f"country audit dry run estimated {estimate} bytes, above the cap of "
            f"{maximum_bytes_billed} bytes"
        )
    rows, job = executor.query(
        sql, parameters, maximum_bytes_billed=maximum_bytes_billed
    )
    return [_json_safe_row(row) for row in rows], {
        **job,
        "estimated_bytes_processed": estimate,
    }


NGramWindowSink = Callable[
    [
        str,
        GDELTWindow,
        RequestLog | None,
        list[DailyTrend | PoliticalArticleSample],
        list[GDELTWindow],
    ],
    None,
]


def _literal_phrase(expression: str) -> str:
    value = expression.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    if not value:
        raise ValueError("NGram phrase must not be empty")
    return value


def topic_phrases(request: CollectionRequest) -> dict[str, list[dict[str, Any]]]:
    """Build native-language phrase records, with legacy queries as a fallback."""
    values: dict[str, list[dict[str, Any]]] = {}
    for topic in request.topics:
        if topic.include_terms or topic.exclude_terms or topic.geographies:
            raise ValueError(
                f"NGram topic {topic.id!r} must contain literal query expressions "
                "without GDELT include/exclude or dimension filters"
            )
        if topic.ngram_phrases:
            values[topic.id] = [
                phrase.model_dump(mode="json") for phrase in topic.ngram_phrases
            ]
            continue
        phrases: list[dict[str, Any]] = []
        for spec in topic.queries:
            if not spec.enabled:
                continue
            if any(
                item is not None
                for item in (
                    spec.include_terms,
                    spec.exclude_terms,
                    spec.geographies,
                )
            ):
                raise ValueError(
                    f"NGram query {spec.id!r} must be one literal expression"
                )
            languages = spec.languages if spec.languages is not None else topic.languages
            for language in languages or [None]:
                phrases.append(
                    {
                        "text": _literal_phrase(spec.expression),
                        "language": language,
                        "segmentation": "space",
                        "translation_status": "validated" if language is None else "draft",
                        "notes": "legacy query fallback",
                    }
                )
        if phrases:
            values[topic.id] = list(
                {
                    (item["text"].casefold(), item["language"], item["segmentation"]): item
                    for item in phrases
                }.values()
            )
    return values


def plan_ngram_windows(
    request: CollectionRequest, *, window_days: int = 366
) -> tuple[list[GDELTWindow], dict[str, list[dict[str, Any]]]]:
    if window_days < 1:
        raise ValueError("NGram window must be at least one day")
    phrases_by_topic = topic_phrases(request)
    if not phrases_by_topic:
        return [], phrases_by_topic
    windows: list[GDELTWindow] = []
    expression = ",".join(sorted(phrases_by_topic))
    current = request.start
    while current <= request.end:
        chunk_end = min(request.end, current + timedelta(days=window_days - 1))
        windows.append(
            GDELTWindow(
                query=Query(
                    topic_id=BATCH_TOPIC_ID,
                    query_id=BATCH_QUERY_ID,
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
    phrases: list[str | dict[str, Any]],
    ngram_table: str = DEFAULT_NGRAM_TABLE,
    coverage_table: str = DEFAULT_COVERAGE_TABLE,
    domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE,
    include_denominator: bool = False,
    political_signals: dict[str, list[str | dict[str, Any]]] | None = None,
    official_domains: dict[str, list[str]] | None = None,
    article_sample_size: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Build the legacy single-topic shape through the batched SQL builder."""
    return build_ngram_batch_sql(
        phrases_by_topic={"single_topic": phrases},
        ngram_table=ngram_table,
        coverage_table=coverage_table,
        domain_country_table=domain_country_table,
        include_denominator=include_denominator,
        political_signals=political_signals,
        official_domains=official_domains,
        article_sample_size=article_sample_size,
    )


def build_ngram_batch_sql(
    *,
    phrases_by_topic: dict[str, list[str | dict[str, Any]]],
    ngram_table: str = DEFAULT_NGRAM_TABLE,
    coverage_table: str = DEFAULT_COVERAGE_TABLE,
    domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE,
    include_denominator: bool = False,
    political_signals: dict[str, list[str | dict[str, Any]]] | None = None,
    official_domains: dict[str, list[str]] | None = None,
    article_sample_size: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Build one scan that independently deduplicates URLs for every topic."""
    for table in (ngram_table, coverage_table, domain_country_table):
        if not _TABLE_PATTERN.fullmatch(table):
            raise ValueError(f"invalid BigQuery table identifier: {table!r}")
    if not phrases_by_topic or any(not values for values in phrases_by_topic.values()):
        raise ValueError("each NGram topic must contain at least one phrase")
    if article_sample_size < -1 or article_sample_size > 100:
        raise ValueError("article sample size must be -1 (all) or between 0 and 100")
    if political_signals:
        return _build_political_ngram_batch_sql(
            phrases_by_topic=phrases_by_topic,
            political_signals=political_signals,
            official_domains=official_domains or {},
            article_sample_size=article_sample_size,
            ngram_table=ngram_table,
            coverage_table=coverage_table,
            domain_country_table=domain_country_table,
            include_denominator=include_denominator,
        )

    parameters: dict[str, Any] = {}
    topic_clauses: list[tuple[int, str]] = []
    phrase_index = 0
    topic_ids = sorted(phrases_by_topic)
    for topic_index, topic_id in enumerate(topic_ids):
        parameters[f"topic_id_{topic_index}"] = topic_id
        clauses: list[str] = []
        for phrase in _normalize_phrase_specs(phrases_by_topic[topic_id]):
            clause, values = _phrase_sql_clause(phrase, phrase_index)
            parameters.update(values)
            clauses.append(clause)
            phrase_index += 1
        topic_clauses.append((topic_index, " OR ".join(clauses)))
    phrase_filter = "\n      OR ".join(
        f"({clause})" for _, clause in topic_clauses
    )
    topic_array = "ARRAY_CONCAT(\n        " + ",\n        ".join(
        "IF(("
        + clause
        + f"), ARRAY<STRING>[@topic_id_{topic_index}], ARRAY<STRING>[])"
        for topic_index, clause in topic_clauses
    ) + "\n      )"

    parameters["topic_ids"] = topic_ids

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
requested_topics AS (
  SELECT topic_id FROM UNNEST(@topic_ids) AS topic_id
),
unambiguous_domains AS (
  SELECT LOWER(Domain) AS domain, ANY_VALUE(CountryHumanName) AS country_label
  FROM `{domain_country_table}`
  WHERE Domain IS NOT NULL AND CountryHumanName IS NOT NULL
  GROUP BY domain
  HAVING COUNT(DISTINCT CountryHumanName) = 1
),
matched_urls AS (
  SELECT
    topic_id,
    DATE(date) AS day,
    url,
    LOWER(NET.HOST(url)) AS host,
    ARRAY_AGG(DISTINCT lang ORDER BY lang LIMIT 1)[SAFE_OFFSET(0)] AS lang
  FROM `{ngram_table}`
  CROSS JOIN UNNEST(
    {topic_array}
  ) AS topic_id
  WHERE DATE(date) BETWEEN @start_date AND @end_date
    AND (
      {phrase_filter}
    )
  GROUP BY topic_id, day, url, host
),
matched_attributed AS (
  SELECT topic_id, day, url, lang, domains.country_label
  FROM matched_urls
  JOIN unambiguous_domains AS domains
    ON host = domains.domain OR ENDS_WITH(host, CONCAT('.', domains.domain))
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY topic_id, day, url ORDER BY LENGTH(domains.domain) DESC
  ) = 1
),
mapping_stats AS (
  SELECT
    topics.topic_id,
    COUNT(DISTINCT matched.url) AS total_matched_urls,
    COUNT(DISTINCT attributed.url) AS attributed_matched_urls
  FROM requested_topics AS topics
  LEFT JOIN matched_urls AS matched USING (topic_id)
  LEFT JOIN matched_attributed AS attributed USING (topic_id, day, url)
  GROUP BY topic_id
),
country_matches AS (
  SELECT topic_id, day, countries.country_id, COUNT(DISTINCT url) AS matched_count
  FROM matched_attributed
  JOIN requested_countries AS countries USING (country_label)
  GROUP BY topic_id, day, country_id
),
country_language_matches AS (
  SELECT topic_id, day, countries.country_id, lang,
    COUNT(DISTINCT url) AS matched_count
  FROM matched_attributed
  JOIN requested_countries AS countries USING (country_label)
  GROUP BY topic_id, day, country_id, lang
),
country_language_breakdown AS (
  SELECT topic_id, day, country_id,
    TO_JSON_STRING(ARRAY_AGG(STRUCT(lang, matched_count) ORDER BY lang))
      AS language_counts_json
  FROM country_language_matches
  GROUP BY topic_id, day, country_id
),
country_mapping_support AS (
  SELECT countries.country_id, COUNT(domains.domain) AS mapped_domain_count
  FROM requested_countries AS countries
  LEFT JOIN unambiguous_domains AS domains USING (country_label)
  GROUP BY country_id
){coverage_ctes},
calendar AS (
  SELECT day
  FROM UNNEST(GENERATE_DATE_ARRAY(@start_date, @end_date)) AS day
)
SELECT
  topics.topic_id,
  calendar.day,
  countries.country_id,
  COALESCE(matches.matched_count, 0) AS matched_count,
  {monitored_expression} AS monitored_count,
  mapping_stats.total_matched_urls,
  mapping_stats.attributed_matched_urls,
  support.mapped_domain_count,
  COALESCE(language_breakdown.language_counts_json, '[]') AS language_counts_json
FROM calendar
CROSS JOIN requested_topics AS topics
CROSS JOIN requested_countries AS countries
JOIN mapping_stats USING (topic_id)
LEFT JOIN country_matches AS matches USING (topic_id, day, country_id)
LEFT JOIN country_language_breakdown AS language_breakdown
  USING (topic_id, day, country_id)
JOIN country_mapping_support AS support USING (country_id)
{coverage_join}
ORDER BY topic_id, day, country_id
""".strip()
    return sql, parameters


def _build_political_ngram_batch_sql(
    *,
    phrases_by_topic: dict[str, list[str | dict[str, Any]]],
    political_signals: dict[str, list[str | dict[str, Any]]],
    official_domains: dict[str, list[str]],
    article_sample_size: int,
    ngram_table: str,
    coverage_table: str,
    domain_country_table: str,
    include_denominator: bool,
) -> tuple[str, dict[str, Any]]:
    """Build the main topic scan with URL-level political co-occurrence flags."""
    required = {"political_actor", "government_action", "party_politics"}
    missing = required - set(political_signals)
    if missing:
        raise ValueError(
            "political signals are missing: " + ", ".join(sorted(missing))
        )
    if any(not values for values in political_signals.values()):
        raise ValueError("each political signal must contain at least one phrase")

    parameters: dict[str, Any] = {}
    phrase_index = 0
    topic_clauses: list[tuple[int, str]] = []
    topic_ids = sorted(phrases_by_topic)
    for topic_index, topic_id in enumerate(topic_ids):
        parameters[f"topic_id_{topic_index}"] = topic_id
        clauses = []
        for phrase in _normalize_phrase_specs(phrases_by_topic[topic_id]):
            clause, values = _phrase_sql_clause(phrase, phrase_index)
            parameters.update(values)
            clauses.append(clause)
            phrase_index += 1
        topic_clauses.append((topic_index, " OR ".join(clauses)))

    signal_clauses: dict[str, str] = {}
    for signal_id in sorted(political_signals):
        clauses = []
        for phrase in _normalize_phrase_specs(political_signals[signal_id]):
            clause, values = _phrase_sql_clause(phrase, phrase_index)
            parameters.update(values)
            clauses.append(clause)
            phrase_index += 1
        signal_clauses[signal_id] = " OR ".join(clauses)

    topic_filter = "\n      OR ".join(f"({clause})" for _, clause in topic_clauses)
    political_filter = "\n      OR ".join(
        f"({clause})" for clause in signal_clauses.values()
    )
    topic_array = "ARRAY_CONCAT(\n        " + ",\n        ".join(
        "IF(("
        + clause
        + f"), ARRAY<STRING>[@topic_id_{topic_index}], ARRAY<STRING>[] )"
        for topic_index, clause in topic_clauses
    ) + "\n      )"
    parameters["topic_ids"] = topic_ids

    official_country_ids: list[str] = []
    official_domain_values: list[str] = []
    for country_id in sorted(official_domains):
        for domain in official_domains[country_id]:
            official_country_ids.append(country_id)
            official_domain_values.append(domain.lower().lstrip("."))
    parameters["official_country_ids"] = official_country_ids
    parameters["official_domains"] = official_domain_values

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
        coverage_join = "LEFT JOIN country_coverage AS coverage USING (day, country_id)"

    article_catalog_cte = ""
    enriched_source = "country_article_signals"
    sample_expression = "'[]'"
    if article_sample_size != 0:
        article_catalog_cte = f""",
article_catalog AS (
  SELECT
    catalog.url,
    ARRAY_AGG(
      STRUCT(catalog.date AS published_at, catalog.domain,
        catalog.outletName AS outlet_name, catalog.outletLogo AS outlet_logo,
        catalog.outletTwitter AS outlet_twitter, catalog.title,
        catalog.image AS image_url, catalog.`desc` AS description,
        catalog.lang, catalog.author)
      ORDER BY catalog.date DESC LIMIT 1
    )[SAFE_OFFSET(0)] AS article
  FROM `{coverage_table}` AS catalog
  JOIN (SELECT DISTINCT url FROM country_article_signals) AS matched USING (url)
  WHERE DATE(catalog.date) BETWEEN @start_date AND @end_date
  GROUP BY catalog.url
),
enriched_country_articles AS (
  SELECT signals.*, catalog.article
  FROM country_article_signals AS signals
  LEFT JOIN article_catalog AS catalog USING (url)
)"""
        enriched_source = "enriched_country_articles"
        article_limit = (
            "" if article_sample_size == -1 else f" LIMIT {article_sample_size}"
        )
        sample_expression = f"""TO_JSON_STRING(ARRAY_AGG(STRUCT(
      url AS url,
      COALESCE(article.domain, host) AS domain,
      article.published_at AS published_at,
      article.outlet_name AS outlet_name,
      article.outlet_logo AS outlet_logo,
      article.outlet_twitter AS outlet_twitter,
      article.title AS title,
      article.image_url AS image_url,
      article.description AS description,
      COALESCE(article.lang, lang) AS lang,
      article.author AS author,
      political_actor AS political_actor,
      government_action AS government_action,
      party_politics AS party_politics,
      official_source AS official_source
    ) ORDER BY FARM_FINGERPRINT(url){article_limit}))"""

    sql = f"""
WITH requested_countries AS (
  SELECT country_id, country_label
  FROM UNNEST(@country_ids) AS country_id WITH OFFSET AS position
  JOIN UNNEST(@country_labels) AS country_label WITH OFFSET AS label_position
    ON position = label_position
),
requested_topics AS (
  SELECT topic_id FROM UNNEST(@topic_ids) AS topic_id
),
requested_official_domains AS (
  SELECT country_id, domain
  FROM UNNEST(@official_country_ids) AS country_id WITH OFFSET AS position
  JOIN UNNEST(@official_domains) AS domain WITH OFFSET AS domain_position
    ON position = domain_position
),
unambiguous_domains AS (
  SELECT LOWER(Domain) AS domain, ANY_VALUE(CountryHumanName) AS country_label
  FROM `{domain_country_table}`
  WHERE Domain IS NOT NULL AND CountryHumanName IS NOT NULL
  GROUP BY domain
  HAVING COUNT(DISTINCT CountryHumanName) = 1
),
attribution_domains AS (
  SELECT domain, country_label, 1 AS priority FROM unambiguous_domains
  UNION ALL
  SELECT official.domain, countries.country_label, 0 AS priority
  FROM requested_official_domains AS official
  JOIN requested_countries AS countries USING (country_id)
),
signal_rows AS (
  SELECT
    DATE(date) AS day,
    url,
    LOWER(NET.HOST(url)) AS host,
    lang,
    {topic_array} AS topic_ids,
    ({signal_clauses['political_actor']}) AS political_actor,
    ({signal_clauses['government_action']}) AS government_action,
    ({signal_clauses['party_politics']}) AS party_politics
  FROM `{ngram_table}`
  WHERE DATE(date) BETWEEN @start_date AND @end_date
    AND (({topic_filter}) OR ({political_filter}))
),
article_signal_aggregates AS (
  SELECT
    day,
    url,
    host,
    ARRAY_AGG(DISTINCT lang ORDER BY lang LIMIT 1)[SAFE_OFFSET(0)] AS lang,
    ARRAY_CONCAT_AGG(topic_ids) AS all_topic_ids,
    LOGICAL_OR(political_actor) AS political_actor,
    LOGICAL_OR(government_action) AS government_action,
    LOGICAL_OR(party_politics) AS party_politics
  FROM signal_rows
  GROUP BY day, url, host
),
article_signals AS (
  SELECT
    * EXCEPT(all_topic_ids),
    ARRAY(
      SELECT DISTINCT topic_id FROM UNNEST(all_topic_ids) AS topic_id
    ) AS topic_ids
  FROM article_signal_aggregates
),
matched_urls AS (
  SELECT topic_id, day, url, host, lang,
    political_actor, government_action, party_politics
  FROM article_signals
  CROSS JOIN UNNEST(topic_ids) AS topic_id
),
matched_attributed AS (
  SELECT matched.*, domains.country_label
  FROM matched_urls AS matched
  JOIN attribution_domains AS domains
    ON host = domains.domain OR ENDS_WITH(host, CONCAT('.', domains.domain))
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY topic_id, day, url
    ORDER BY LENGTH(domains.domain) DESC, domains.priority
  ) = 1
),
country_article_signals AS (
  SELECT
    matched.topic_id, matched.day, matched.url, matched.host, matched.lang,
    countries.country_id, matched.political_actor, matched.government_action,
    matched.party_politics,
    EXISTS(
      SELECT 1 FROM requested_official_domains AS official
      WHERE official.country_id = countries.country_id
        AND (
          matched.host = official.domain
          OR ENDS_WITH(matched.host, CONCAT('.', official.domain))
        )
    ) AS official_source
  FROM matched_attributed AS matched
  JOIN requested_countries AS countries USING (country_label)
){article_catalog_cte},
mapping_stats AS (
  SELECT
    topics.topic_id,
    COUNT(DISTINCT matched.url) AS total_matched_urls,
    COUNT(DISTINCT attributed.url) AS attributed_matched_urls
  FROM requested_topics AS topics
  LEFT JOIN matched_urls AS matched USING (topic_id)
  LEFT JOIN matched_attributed AS attributed USING (topic_id, day, url)
  GROUP BY topic_id
),
country_matches AS (
  SELECT
    topic_id, day, country_id,
    COUNT(*) AS matched_count,
    COUNTIF(
      political_actor OR government_action OR party_politics OR official_source
    ) AS political_count,
    COUNTIF(political_actor) AS political_actor_count,
    COUNTIF(government_action) AS government_action_count,
    COUNTIF(party_politics) AS party_politics_count,
    COUNTIF(official_source) AS official_source_count,
    {sample_expression} AS article_samples_json
  FROM {enriched_source}
  GROUP BY topic_id, day, country_id
),
country_language_matches AS (
  SELECT topic_id, day, country_id, lang, COUNT(*) AS matched_count
  FROM country_article_signals
  GROUP BY topic_id, day, country_id, lang
),
country_language_breakdown AS (
  SELECT topic_id, day, country_id,
    TO_JSON_STRING(ARRAY_AGG(STRUCT(lang, matched_count) ORDER BY lang))
      AS language_counts_json
  FROM country_language_matches
  GROUP BY topic_id, day, country_id
),
country_mapping_support AS (
  SELECT countries.country_id, COUNT(domains.domain) AS mapped_domain_count
  FROM requested_countries AS countries
  LEFT JOIN unambiguous_domains AS domains USING (country_label)
  GROUP BY country_id
){coverage_ctes},
calendar AS (
  SELECT day FROM UNNEST(GENERATE_DATE_ARRAY(@start_date, @end_date)) AS day
)
SELECT
  topics.topic_id,
  calendar.day,
  countries.country_id,
  COALESCE(matches.matched_count, 0) AS matched_count,
  {monitored_expression} AS monitored_count,
  COALESCE(matches.political_count, 0) AS political_count,
  COALESCE(matches.political_actor_count, 0) AS political_actor_count,
  COALESCE(matches.government_action_count, 0) AS government_action_count,
  COALESCE(matches.party_politics_count, 0) AS party_politics_count,
  COALESCE(matches.official_source_count, 0) AS official_source_count,
  COALESCE(matches.article_samples_json, '[]') AS article_samples_json,
  mapping_stats.total_matched_urls,
  mapping_stats.attributed_matched_urls,
  support.mapped_domain_count,
  COALESCE(language_breakdown.language_counts_json, '[]') AS language_counts_json
FROM calendar
CROSS JOIN requested_topics AS topics
CROSS JOIN requested_countries AS countries
JOIN mapping_stats USING (topic_id)
LEFT JOIN country_matches AS matches USING (topic_id, day, country_id)
LEFT JOIN country_language_breakdown AS language_breakdown
  USING (topic_id, day, country_id)
JOIN country_mapping_support AS support USING (country_id)
{coverage_join}
ORDER BY topic_id, day, country_id
""".strip()
    return sql, parameters


def _phrase_sql_clause(
    phrase: dict[str, Any], index: int
) -> tuple[str, dict[str, Any]]:
    text = phrase["text"]
    segmentation = phrase["segmentation"]
    units = text.split() if segmentation == "space" else list(text.replace(" ", ""))
    if not units:
        raise ValueError("NGram phrase must contain a word")
    anchor = units[(len(units) - 1) // 2].casefold()
    separator = r"\s+" if segmentation == "space" else ""
    escaped = separator.join(re.escape(unit.casefold()) for unit in units)
    values: dict[str, Any] = {
        f"anchor_variants_{index}": _anchor_variants(
            anchor,
            single_word=len(units) == 1,
            character=segmentation == "character",
        ),
        f"pattern_{index}": (
            escaped
            if segmentation == "character"
            else rf"(^|[^\p{{L}}\p{{N}}]){escaped}([^\p{{L}}\p{{N}}]|$)"
        ),
        f"segmentation_type_{index}": 2 if segmentation == "character" else 1,
    }
    language_filter = ""
    if phrase["language"]:
        values[f"language_{index}"] = phrase["language"]
        language_filter = f"lang = @language_{index} AND "
    context = (
        "CONCAT(COALESCE(pre, ''), ngram, COALESCE(post, ''))"
        if segmentation == "character"
        else "CONCAT(COALESCE(pre, ''), ' ', ngram, ' ', COALESCE(post, ''))"
    )
    return (
        "("
        f"{language_filter}type = @segmentation_type_{index} AND "
        f"ngram IN UNNEST(@anchor_variants_{index}) AND "
        f"REGEXP_CONTAINS(LOWER({context}), @pattern_{index})"
        ")",
        values,
    )


def _normalize_phrase_specs(
    phrases: list[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for phrase in phrases:
        if isinstance(phrase, str):
            item = {
                "text": phrase,
                "language": None,
                "segmentation": "space",
                "translation_status": "validated",
                "notes": "legacy query fallback",
            }
        else:
            item = {
                "language": None,
                "segmentation": "space",
                "translation_status": "draft",
                "notes": None,
                **phrase,
            }
        text = str(item["text"]).strip()
        if not text:
            raise ValueError("NGram phrase must not be empty")
        if item["segmentation"] not in {"space", "character"}:
            raise ValueError("NGram segmentation must be space or character")
        item["text"] = text
        normalized.append(item)
    return normalized


def _topic_expression(phrases: list[str | dict[str, Any]]) -> str:
    return " OR ".join(
        f'"{phrase["text"]}"' for phrase in _normalize_phrase_specs(phrases)
    )


def _anchor_variants(
    anchor: str, *, single_word: bool, character: bool = False
) -> list[str]:
    """Return a bounded cluster-friendly pilot anchor set."""
    cases = [anchor] if character else list(dict.fromkeys((anchor, anchor.capitalize())))
    # Multiword phrases anchor on a non-final word. Unpunctuated lower/title forms
    # capture ordinary prose while keeping the BigQuery pilot affordable. Broader
    # punctuation/case recall is measured later as a sensitivity analysis.
    prefixes = ("",)
    suffixes = ("",) if character else (("", ".", ",") if single_word else ("",))
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
    phrases: list[str | dict[str, Any]],
    country_labels: dict[str, str],
    ngram_table: str = DEFAULT_NGRAM_TABLE,
    coverage_table: str = DEFAULT_COVERAGE_TABLE,
    domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE,
    include_denominator: bool = False,
    political_signals: dict[str, list[str | dict[str, Any]]] | None = None,
    official_domains: dict[str, list[str]] | None = None,
    article_sample_size: int = 0,
) -> tuple[str, dict[str, Any]]:
    return prepare_ngram_batch_query(
        window,
        phrases_by_topic={window.query.topic_id: phrases},
        country_labels=country_labels,
        ngram_table=ngram_table,
        coverage_table=coverage_table,
        domain_country_table=domain_country_table,
        include_denominator=include_denominator,
        political_signals=political_signals,
        official_domains=official_domains,
        article_sample_size=article_sample_size,
    )


def prepare_ngram_batch_query(
    window: GDELTWindow,
    *,
    phrases_by_topic: dict[str, list[str | dict[str, Any]]],
    country_labels: dict[str, str],
    ngram_table: str = DEFAULT_NGRAM_TABLE,
    coverage_table: str = DEFAULT_COVERAGE_TABLE,
    domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE,
    include_denominator: bool = False,
    political_signals: dict[str, list[str | dict[str, Any]]] | None = None,
    official_domains: dict[str, list[str]] | None = None,
    article_sample_size: int = 0,
) -> tuple[str, dict[str, Any]]:
    sql, phrase_parameters = build_ngram_batch_sql(
        phrases_by_topic=phrases_by_topic,
        ngram_table=ngram_table,
        coverage_table=coverage_table,
        domain_country_table=domain_country_table,
        include_denominator=include_denominator,
        political_signals=political_signals,
        official_domains=official_domains,
        article_sample_size=article_sample_size,
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
    phrases_by_topic: dict[str, list[str | dict[str, Any]]],
    include_denominator: bool = False,
    political_signals: dict[str, list[str | dict[str, Any]]] | None = None,
    official_domains: dict[str, list[str]] | None = None,
    article_sample_size: int = 0,
) -> list[dict[str, Any]]:
    estimates: list[dict[str, Any]] = []
    for window in windows:
        selected_phrases = (
            phrases_by_topic
            if window.query.topic_id == BATCH_TOPIC_ID
            else {window.query.topic_id: phrases_by_topic[window.query.topic_id]}
        )
        sql, parameters = prepare_ngram_batch_query(
            window,
            phrases_by_topic=selected_phrases,
            country_labels=country_labels,
            include_denominator=include_denominator,
            political_signals=political_signals,
            official_domains=official_domains,
            article_sample_size=article_sample_size,
        )
        estimates.append(
            {
                "window_id": window.window_id,
                "topic_id": window.query.topic_id,
                "topic_ids": sorted(selected_phrases),
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
            elif isinstance(value, int):
                query_parameters.append(
                    bigquery.ScalarQueryParameter(name, "INT64", value)
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
        topic_phrases: dict[str, list[str | dict[str, Any]]],
        maximum_bytes_billed: int,
        location: str = "US",
        ngram_table: str = DEFAULT_NGRAM_TABLE,
        coverage_table: str = DEFAULT_COVERAGE_TABLE,
        domain_country_table: str = DEFAULT_DOMAIN_COUNTRY_TABLE,
        include_denominator: bool = False,
        political_signals: dict[str, list[str | dict[str, Any]]] | None = None,
        official_domains: dict[str, list[str]] | None = None,
        article_sample_size: int = 0,
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
        self.political_signals = political_signals
        self.official_domains = official_domains or {}
        self.article_sample_size = article_sample_size
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
                trends, samples = self._collect_window(window)
                log = self._log(window, "success", len(trends))
                result.requests.append(log)
                result.trends.extend(trends)
                self._emit("success", window, log, [*trends, *samples])
            except Exception as exc:
                log = self._log(window, "failed", 0, error=str(exc))
                result.requests.append(log)
                self._emit("failed", window, log, [])
                raise ProviderCollectionError(str(exc), result) from exc
        return result

    def _collect_window(
        self, window: GDELTWindow
    ) -> tuple[list[DailyTrend], list[PoliticalArticleSample]]:
        selected_phrases = (
            self.topic_phrases
            if window.query.topic_id == BATCH_TOPIC_ID
            else {
                window.query.topic_id: self.topic_phrases.get(window.query.topic_id, [])
            }
        )
        if not selected_phrases or any(not values for values in selected_phrases.values()):
            raise ValueError(f"missing NGram phrases for topic {window.query.topic_id!r}")
        sql, parameters = prepare_ngram_batch_query(
            window,
            phrases_by_topic=selected_phrases,
            country_labels=self.country_labels,
            ngram_table=self.ngram_table,
            coverage_table=self.coverage_table,
            domain_country_table=self.domain_country_table,
            include_denominator=self.include_denominator,
            political_signals=self.political_signals,
            official_domains=self.official_domains,
            article_sample_size=self.article_sample_size,
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
                    "topic_phrases": selected_phrases,
                    "political_signals": self.political_signals,
                    "official_domains": self.official_domains,
                    "article_sample_size": self.article_sample_size,
                    "start": window.start.isoformat(),
                    "end": window.end.isoformat(),
                    "estimated_bytes_processed": estimated_bytes,
                    "job": job,
                    "response": [_json_safe_row(row) for row in rows],
                }
            )
        trends = parse_ngram_batch_rows(
            rows=rows,
            window=window,
            phrases_by_topic=selected_phrases,
            estimated_bytes=estimated_bytes,
            job=job,
            collected_at=collected_at,
            include_denominator=self.include_denominator,
            political_signals=self.political_signals,
            official_domains=self.official_domains,
        )
        samples = parse_political_article_samples(
            rows=rows,
            collected_at=collected_at,
            sample_size=self.article_sample_size,
        )
        expected = (
            (window.end.date() - window.start.date()).days + 1
        ) * len(self.country_labels) * len(selected_phrases)
        if len(trends) != expected:
            raise ValueError(
                f"BigQuery returned {len(trends)} country-day rows; expected {expected}"
            )
        returned_countries = {trend.geography for trend in trends}
        if returned_countries != set(self.country_labels):
            raise ValueError("BigQuery returned unexpected country dimensions")
        returned_topics = {trend.topic_id for trend in trends}
        if returned_topics != set(selected_phrases):
            raise ValueError("BigQuery returned unexpected topic dimensions")
        return trends, samples

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
        trends: list[DailyTrend | PoliticalArticleSample] | None = None,
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
    phrases: list[str | dict[str, Any]],
    estimated_bytes: int,
    job: dict[str, Any],
    collected_at: datetime,
    include_denominator: bool = False,
    political_signals: dict[str, list[str | dict[str, Any]]] | None = None,
    official_domains: dict[str, list[str]] | None = None,
) -> list[DailyTrend]:
    return parse_ngram_batch_rows(
        rows=rows,
        window=window,
        phrases_by_topic={window.query.topic_id: phrases},
        estimated_bytes=estimated_bytes,
        job=job,
        collected_at=collected_at,
        include_denominator=include_denominator,
        political_signals=political_signals,
        official_domains=official_domains,
    )


def parse_ngram_batch_rows(
    *,
    rows: Iterable[dict[str, Any]],
    window: GDELTWindow,
    phrases_by_topic: dict[str, list[str | dict[str, Any]]],
    estimated_bytes: int,
    job: dict[str, Any],
    collected_at: datetime,
    include_denominator: bool = False,
    political_signals: dict[str, list[str | dict[str, Any]]] | None = None,
    official_domains: dict[str, list[str]] | None = None,
) -> list[DailyTrend]:
    trends: list[DailyTrend] = []
    seen: set[tuple[str, date, str]] = set()
    sole_topic = next(iter(phrases_by_topic)) if len(phrases_by_topic) == 1 else None
    batch_topic_ids = sorted(phrases_by_topic)
    for row in rows:
        day = row.get("day")
        if isinstance(day, datetime):
            day = day.date()
        if not isinstance(day, date):
            day = date.fromisoformat(str(day))
        topic_id = str(row.get("topic_id") or sole_topic or "")
        if topic_id not in phrases_by_topic:
            raise ValueError(f"unexpected NGram topic id: {topic_id!r}")
        phrases = phrases_by_topic[topic_id]
        country_id = str(row["country_id"])
        key = (topic_id, day, country_id)
        if key in seen:
            raise ValueError(
                f"duplicate NGram aggregate row for {topic_id}/{country_id}/{day}"
            )
        seen.add(key)
        matched = int(row["matched_count"])
        raw_monitored = row.get("monitored_count")
        monitored = int(raw_monitored) if raw_monitored is not None else None
        total_matched = int(row.get("total_matched_urls", 0))
        attributed_matched = int(row.get("attributed_matched_urls", 0))
        mapped_domain_count = int(row.get("mapped_domain_count", 0))
        language_counts = json.loads(row.get("language_counts_json") or "[]")
        political_enabled = political_signals is not None
        political_count = (
            int(row.get("political_count", 0)) if political_enabled else None
        )
        political_actor_count = (
            int(row.get("political_actor_count", 0)) if political_enabled else None
        )
        government_action_count = (
            int(row.get("government_action_count", 0)) if political_enabled else None
        )
        party_politics_count = (
            int(row.get("party_politics_count", 0)) if political_enabled else None
        )
        official_source_count = (
            int(row.get("official_source_count", 0)) if political_enabled else None
        )
        if matched < 0 or (monitored is not None and monitored < 0):
            raise ValueError("NGram counts must be non-negative")
        share = matched / monitored if monitored else None
        identity = "|".join(
            [
                "gdelt-ngrams-v1",
                topic_id,
                TOPIC_QUERY_ID,
                country_id,
                day.isoformat(),
            ]
        )
        trends.append(
            DailyTrend(
                record_id=sha256(identity.encode("utf-8")).hexdigest(),
                date=day,
                source=SOURCE,
                topic_id=topic_id,
                query_id=TOPIC_QUERY_ID,
                query_expression=_topic_expression(phrases),
                geography=country_id,
                matched_count=matched,
                country_monitored_count=monitored,
                country_attention_share=share,
                political_count=political_count,
                political_actor_count=political_actor_count,
                government_action_count=government_action_count,
                party_politics_count=party_politics_count,
                official_source_count=official_source_count,
                political_share_of_matched=(
                    political_count / matched
                    if political_count is not None and matched
                    else (0.0 if political_count is not None else None)
                ),
                collected_at=collected_at,
                metadata={
                    "collection_mode": "webngrams_distinct_urls",
                    "bigquery_collection_mode": (
                        "multi_topic_batch"
                        if len(batch_topic_ids) > 1
                        else "single_topic_batch"
                    ),
                    "bigquery_batch_topic_ids": batch_topic_ids,
                    "phrases": _normalize_phrase_specs(phrases),
                    "language_counts": {
                        item["lang"]: int(item["matched_count"])
                        for item in language_counts
                    },
                    "configured_languages": sorted(
                        {
                            item["language"]
                            for item in _normalize_phrase_specs(phrases)
                            if item["language"]
                        }
                    ),
                    "deduplication_scope": "distinct_url_per_day_topic",
                    "anchor_variant_policy": (
                        "unpunctuated_lower_and_title_case_pilot"
                    ),
                    "country_attribution": (
                        "gdelt_2015_map_plus_configured_official_domain_overrides"
                        if political_signals is not None
                        else "gdelt_domainsbycountry_alllangs_april2015_longest_suffix"
                    ),
                    "country_map_limitations": (
                        "2015 snapshot; ambiguous and unmapped domains excluded"
                    ),
                    "country_mapping_supported": mapped_domain_count > 0,
                    "mapped_domain_count": mapped_domain_count,
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
                    "political_classifier": (
                        {
                            "scope": "full_article_webngrams_url_cooccurrence",
                            "signals": {
                                signal_id: _normalize_phrase_specs(signal_phrases)
                                for signal_id, signal_phrases in political_signals.items()
                            },
                            "political_union": (
                                "political_actor OR government_action OR "
                                "party_politics OR official_source"
                            ),
                            "counts_are_census": True,
                            "official_domains": official_domains or {},
                        }
                        if political_signals is not None
                        else None
                    ),
                    "estimated_bytes_processed": estimated_bytes,
                    "bigquery_job": job,
                },
            )
        )
    return trends


def parse_political_article_samples(
    *,
    rows: Iterable[dict[str, Any]],
    collected_at: datetime,
    sample_size: int,
) -> list[PoliticalArticleSample]:
    """Parse bounded deterministic URL samples returned beside exact counts."""
    if sample_size == 0:
        return []
    samples: list[PoliticalArticleSample] = []
    seen: set[tuple[str, date, str, str]] = set()
    for row in rows:
        day = row.get("day")
        if isinstance(day, datetime):
            day = day.date()
        if not isinstance(day, date):
            day = date.fromisoformat(str(day))
        topic_id = str(row["topic_id"])
        country_id = str(row["country_id"])
        raw_samples = json.loads(row.get("article_samples_json") or "[]")
        for item in raw_samples:
            url = str(item["url"])
            key = (topic_id, day, country_id, url)
            if key in seen:
                continue
            seen.add(key)
            identity = "|".join(
                [
                    "gdelt-ngrams-political-sample-v1",
                    topic_id,
                    country_id,
                    day.isoformat(),
                    url,
                ]
            )
            published_at = item.get("published_at")
            if isinstance(published_at, str):
                published_at = datetime.fromisoformat(
                    published_at.replace("Z", "+00:00")
                )
            samples.append(
                PoliticalArticleSample(
                    record_id=sha256(identity.encode("utf-8")).hexdigest(),
                    date=day,
                    topic_id=topic_id,
                    geography=country_id,
                    url=url,
                    domain=item.get("domain"),
                    published_at=published_at,
                    outlet_name=item.get("outlet_name"),
                    outlet_logo=item.get("outlet_logo"),
                    outlet_twitter=item.get("outlet_twitter"),
                    title=item.get("title"),
                    image_url=item.get("image_url"),
                    description=item.get("description"),
                    language=item.get("lang"),
                    author=item.get("author"),
                    political_actor=bool(item.get("political_actor")),
                    government_action=bool(item.get("government_action")),
                    party_politics=bool(item.get("party_politics")),
                    official_source=bool(item.get("official_source")),
                    collected_at=collected_at,
                    metadata={
                        "selection_method": (
                            "all_matched_articles"
                            if sample_size == -1
                            else "farm_fingerprint_url"
                        ),
                        "article_limit_per_topic_country_day": (
                            None if sample_size == -1 else sample_size
                        ),
                        "complete_article_panel": sample_size == -1,
                        "validation_sample_only": sample_size != -1,
                        "counts_must_not_be_inferred_from_sample": sample_size != -1,
                        "metadata_source": "gdelt_gal_article_list",
                        "knowledge_graph_queried": False,
                    },
                )
            )
    return samples
