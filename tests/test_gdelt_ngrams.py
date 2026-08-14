from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from climate_attention.config import Country
from climate_attention.models import CollectionRequest, Query, QuerySpec, Topic
from climate_attention.sources.base import ProviderCollectionError
from climate_attention.sources.gdelt_ngrams import (
    GDELTNGramsProvider,
    GoogleBigQueryExecutor,
    audit_country_mapping,
    build_country_audit_sql,
    build_ngram_batch_sql,
    build_ngram_sql,
    parse_ngram_batch_rows,
    parse_political_article_samples,
    plan_ngram_windows,
)


def _request() -> CollectionRequest:
    return CollectionRequest(
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        topics=[
            Topic(
                id="climate_change",
                label="Climate change",
                queries=[
                    QuerySpec(id="climate", expression='"climate change"'),
                    QuerySpec(id="warming", expression='"global warming"'),
                ],
            )
        ],
    )


def test_ngram_sql_is_parameterized_and_deduplicates_urls():
    sql, parameters = build_ngram_sql(
        phrases=["climate change", "global warming"]
    )

    assert "COUNT(DISTINCT url) AS matched_count" in sql
    assert "COUNT(DISTINCT url) AS monitored_count" not in sql
    assert "CAST(NULL AS INT64) AS monitored_count" in sql
    assert "domainsbycountry_alllangs_april2015" in sql
    assert "GENERATE_DATE_ARRAY" in sql
    assert "@anchor_variants_0" in sql and "@pattern_1" in sql
    assert "climate change" not in sql
    assert "climate" in parameters["anchor_variants_0"]
    assert "Climate" in parameters["anchor_variants_0"]
    assert '"climate' not in parameters["anchor_variants_0"]
    assert "climate," not in parameters["anchor_variants_0"]
    assert r"climate\s+change" in parameters["pattern_0"]


def test_ngram_planning_is_topic_window_not_country_window():
    request = _request().model_copy(update={"end": date(2026, 1, 3)})
    windows, phrases = plan_ngram_windows(request, window_days=2)

    assert len(windows) == 2
    assert [item["text"] for item in phrases["climate_change"]] == [
        "climate change",
        "global warming",
    ]
    assert all(window.query.geography is None for window in windows)
    assert windows[0].start.date() == date(2026, 1, 1)
    assert windows[1].start.date() == date(2026, 1, 3)


def test_ngram_planning_batches_all_topics_per_date_window():
    request = _request().model_copy(deep=True)
    request.topics.append(
        Topic(
            id="clean_energy",
            label="Clean energy",
            queries=[QuerySpec(expression='"clean energy"')],
        )
    )
    request = request.model_copy(update={"end": date(2026, 1, 3)})

    windows, phrases = plan_ngram_windows(request, window_days=2)

    assert len(windows) == 2
    assert set(phrases) == {"climate_change", "clean_energy"}
    assert all(window.query.topic_id == "ngram_topic_batch" for window in windows)
    assert all(window.query.query_id == "topics_distinct_urls" for window in windows)


def test_batch_sql_scans_ngram_table_once_and_keeps_topic_membership():
    sql, parameters = build_ngram_batch_sql(
        phrases_by_topic={
            "climate_change": ["climate change", "global warming"],
            "clean_energy": ["clean energy"],
        }
    )

    assert sql.count("`gdelt-bq.gdeltv2.webngrams`") == 1
    assert "CROSS JOIN UNNEST" in sql
    assert "ARRAY_CONCAT" in sql
    assert "GROUP BY topic_id, day, url, host" in sql
    assert "PARTITION BY topic_id, day, url" in sql
    assert parameters["topic_ids"] == ["clean_energy", "climate_change"]
    assert {parameters["topic_id_0"], parameters["topic_id_1"]} == {
        "clean_energy",
        "climate_change",
    }


def test_political_sql_counts_url_level_signals_and_samples_articles():
    sql, parameters = build_ngram_batch_sql(
        phrases_by_topic={"climate_change": ["climate change"]},
        political_signals={
            "political_actor": ["government"],
            "government_action": ["new law"],
            "party_politics": ["opposition party"],
        },
        official_domains={"italy": ["governo.it"]},
        article_sample_size=10,
    )

    assert sql.count("`gdelt-bq.gdeltv2.webngrams`") == 1
    assert "LOGICAL_OR(political_actor)" in sql
    assert "COUNTIF(" in sql
    assert "article_samples_json" in sql
    assert "FARM_FINGERPRINT(url)" in sql
    assert "`gdelt-bq.gdeltv2.gal`" in sql
    assert "attribution_domains" in sql
    assert parameters["official_country_ids"] == ["italy"]
    assert parameters["official_domains"] == ["governo.it"]


def test_political_parser_keeps_exact_counts_separate_from_validation_sample():
    window, _ = plan_ngram_windows(_request())
    rows = [
        {
            "topic_id": "climate_change",
            "day": date(2026, 1, 1),
            "country_id": "italy",
            "matched_count": 8,
            "monitored_count": None,
            "political_count": 3,
            "political_actor_count": 2,
            "government_action_count": 1,
            "party_politics_count": 1,
            "official_source_count": 1,
            "total_matched_urls": 8,
            "attributed_matched_urls": 8,
            "mapped_domain_count": 2,
            "language_counts_json": '[{"lang":"it","matched_count":8}]',
            "article_samples_json": json.dumps(
                [
                    {
                        "url": "https://example.it/story",
                        "domain": "example.it",
                        "published_at": "2026-01-01T08:30:00Z",
                        "outlet_name": "Example News",
                        "outlet_logo": "https://example.it/logo.png",
                        "outlet_twitter": "examplenews",
                        "title": "Story",
                        "image_url": "https://example.it/image.jpg",
                        "description": "Description",
                        "lang": "it",
                        "author": "Reporter",
                        "political_actor": True,
                        "government_action": False,
                        "party_politics": False,
                        "official_source": False,
                    }
                ]
            ),
        }
    ]
    signals = {
        "political_actor": ["governo"],
        "government_action": ["nuova legge"],
        "party_politics": ["partito di opposizione"],
    }

    trends = parse_ngram_batch_rows(
        rows=rows,
        window=window[0],
        phrases_by_topic={"climate_change": ["climate change"]},
        estimated_bytes=100,
        job={"job_id": "politics-1"},
        collected_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        political_signals=signals,
    )
    samples = parse_political_article_samples(
        rows=rows,
        collected_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        sample_size=10,
    )

    assert trends[0].political_count == 3
    assert trends[0].political_share_of_matched == 0.375
    assert trends[0].metadata["political_classifier"]["counts_are_census"] is True
    assert len(samples) == 1
    assert samples[0].political is True
    assert samples[0].published_at == datetime(
        2026, 1, 1, 8, 30, tzinfo=timezone.utc
    )
    assert samples[0].outlet_name == "Example News"
    assert samples[0].image_url == "https://example.it/image.jpg"
    assert samples[0].metadata["validation_sample_only"] is True


def test_batch_parser_creates_stable_topic_rows_and_deduplicates_per_topic():
    window, _ = plan_ngram_windows(_request())
    phrases = {
        "climate_change": ["climate change"],
        "clean_energy": ["clean energy"],
    }
    rows = [
        {
            "topic_id": topic_id,
            "day": date(2026, 1, 1),
            "country_id": "italy",
            "matched_count": count,
            "monitored_count": None,
            "total_matched_urls": count,
            "attributed_matched_urls": count,
            "mapped_domain_count": 2,
            "language_counts_json": (
                f'[{json.dumps({"lang": "en", "matched_count": count})}]'
            ),
        }
        for topic_id, count in (("climate_change", 3), ("clean_energy", 5))
    ]

    trends = parse_ngram_batch_rows(
        rows=rows,
        window=window[0],
        phrases_by_topic=phrases,
        estimated_bytes=100,
        job={"job_id": "batch-1"},
        collected_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert {(row.topic_id, row.matched_count) for row in trends} == {
        ("climate_change", 3),
        ("clean_energy", 5),
    }
    assert all(row.query_id == "topic_distinct_urls" for row in trends)
    assert all(
        row.metadata["bigquery_collection_mode"] == "multi_topic_batch"
        for row in trends
    )
    assert len({row.record_id for row in trends}) == 2


class FakeExecutor:
    def __init__(self, *, estimate=1234):
        self.estimated = estimate
        self.calls = []

    def estimate(self, sql, parameters):
        self.calls.append(("estimate", sql, parameters))
        return self.estimated

    def query(self, sql, parameters, *, maximum_bytes_billed):
        self.calls.append(("query", sql, parameters, maximum_bytes_billed))
        rows = []
        for day in (date(2026, 1, 1), date(2026, 1, 2)):
            for country, matched, monitored in (
                ("italy", 4, 100),
                ("unitedkingdom", 8, 200),
            ):
                rows.append(
                    {
                        "day": day,
                        "country_id": country,
                        "matched_count": matched,
                        "monitored_count": monitored,
                        "total_matched_urls": 20,
                        "attributed_matched_urls": 16,
                        "mapped_domain_count": 12,
                        "language_counts_json": '[{"lang":"en","matched_count":4}]',
                    }
                )
        return rows, {
            "job_id": "job-1",
            "total_bytes_processed": self.estimated,
            "total_bytes_billed": self.estimated,
            "cache_hit": False,
        }


def test_ngram_provider_dry_runs_then_writes_country_day_counts():
    windows, phrases = plan_ngram_windows(_request())
    executor = FakeExecutor()
    envelopes = []
    events = []
    provider = GDELTNGramsProvider(
        billing_project="research-project",
        country_labels={"italy": "Italy", "unitedkingdom": "United Kingdom"},
        topic_phrases=phrases,
        maximum_bytes_billed=10_000,
        include_denominator=True,
        executor=executor,
        response_sink=envelopes.append,
        timeline_sink=lambda *args: events.append(args),
    )

    result = provider.collect_windows(windows)

    assert [call[0] for call in executor.calls] == ["estimate", "query"]
    assert len(result.trends) == 4
    italy = next(
        trend
        for trend in result.trends
        if trend.geography == "italy" and trend.date == date(2026, 1, 1)
    )
    assert italy.matched_count == 4
    assert italy.country_monitored_count == 100
    assert italy.country_attention_share == 0.04
    assert italy.metadata["all_country_url_attribution_rate"] == 0.8
    assert italy.metadata["country_mapping_supported"] is True
    assert italy.metadata["language_counts"] == {"en": 4}
    assert italy.metadata["bigquery_job"]["job_id"] == "job-1"
    assert [event[0] for event in events] == ["started", "success"]
    assert envelopes[0]["estimated_bytes_processed"] == 1234
    assert envelopes[0]["response"][0]["day"] == "2026-01-01"
    json.dumps(envelopes[0])


def test_ngram_provider_refuses_query_over_cost_cap():
    windows, phrases = plan_ngram_windows(_request())
    provider = GDELTNGramsProvider(
        billing_project="research-project",
        country_labels={"italy": "Italy"},
        topic_phrases=phrases,
        maximum_bytes_billed=100,
        executor=FakeExecutor(estimate=101),
    )

    with pytest.raises(ProviderCollectionError, match="above the per-window cap"):
        provider.collect_windows(windows)


def test_provider_retries_legacy_per_topic_window():
    windows, phrases = plan_ngram_windows(_request())
    legacy_window = replace(
        windows[0],
        query=Query(
            topic_id="climate_change",
            query_id="topic_distinct_urls",
            expression='"climate change" OR "global warming"',
        ),
    )
    provider = GDELTNGramsProvider(
        billing_project="research-project",
        country_labels={"italy": "Italy", "unitedkingdom": "United Kingdom"},
        topic_phrases=phrases,
        maximum_bytes_billed=10_000,
        executor=FakeExecutor(),
    )

    result = provider.collect_windows([legacy_window])

    assert len(result.trends) == 4
    assert {trend.topic_id for trend in result.trends} == {"climate_change"}
    assert all(trend.query_id == "topic_distinct_urls" for trend in result.trends)


def test_ngram_topic_rejects_gdelt_filters():
    request = _request()
    request.topics[0].include_terms = ["policy"]
    with pytest.raises(ValueError, match="literal query expressions"):
        plan_ngram_windows(request)


def test_multilingual_phrases_filter_language_and_character_segmentation():
    sql, parameters = build_ngram_sql(
        phrases=[
            {
                "text": "cambio climático",
                "language": "es",
                "segmentation": "space",
            },
            {
                "text": "气候变化",
                "language": "zh",
                "segmentation": "character",
            },
        ]
    )

    assert "lang = @language_0" in sql
    assert "type = @segmentation_type_1" in sql
    assert parameters["language_0"] == "es"
    assert parameters["language_1"] == "zh"
    assert parameters["segmentation_type_0"] == 1
    assert parameters["segmentation_type_1"] == 2
    assert parameters["anchor_variants_1"] == ["候"]
    assert parameters["pattern_1"] == "气候变化"
    assert "language_counts_json" in sql
    assert "mapped_domain_count" in sql


def test_bigquery_dry_run_omits_none_maximum_bytes_billed():
    class FakeBigQuery:
        class ScalarQueryParameter:
            def __init__(self, *args):
                self.args = args

        class ArrayQueryParameter(ScalarQueryParameter):
            pass

        class QueryJobConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    executor = object.__new__(GoogleBigQueryExecutor)
    executor.bigquery = FakeBigQuery

    dry_run = executor._job_config(
        {"start_date": date(2026, 1, 1)}, dry_run=True
    )
    capped = executor._job_config(
        {"start_date": date(2026, 1, 1)},
        dry_run=False,
        maximum_bytes_billed=123,
    )

    assert "maximum_bytes_billed" not in dry_run.kwargs
    assert capped.kwargs["maximum_bytes_billed"] == 123


def test_country_audit_is_capped_and_parameterized():
    class AuditExecutor:
        def estimate(self, sql, parameters):
            assert "EDIT_DISTANCE" in sql
            assert parameters["country_ids"] == ["italy"]
            return 50

        def query(self, sql, parameters, *, maximum_bytes_billed):
            assert maximum_bytes_billed == 100
            return [
                {
                    "country_id": "italy",
                    "country_label": "Italy",
                    "mapped_domain_count": 10,
                    "sample_domains": ["example.it"],
                    "suggested_labels": ["Italy"],
                }
            ], {
                "job_id": "audit-1",
                "total_bytes_processed": 50,
                "total_bytes_billed": 10_000_000,
                "cache_hit": False,
            }

    rows, job = audit_country_mapping(
        executor=AuditExecutor(),
        country_labels={"italy": "Italy"},
        maximum_bytes_billed=100,
    )

    assert rows[0]["mapped_domain_count"] == 10
    assert job["estimated_bytes_processed"] == 50
    assert "domainsbycountry_alllangs_april2015" in build_country_audit_sql()
