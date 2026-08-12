from __future__ import annotations

import json
from datetime import date

import pytest

from climate_attention.config import Country
from climate_attention.models import CollectionRequest, QuerySpec, Topic
from climate_attention.sources.base import ProviderCollectionError
from climate_attention.sources.gdelt_ngrams import (
    GDELTNGramsProvider,
    GoogleBigQueryExecutor,
    build_ngram_sql,
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
    assert phrases == {
        "climate_change": ["climate change", "global warming"]
    }
    assert all(window.query.geography is None for window in windows)
    assert windows[0].start.date() == date(2026, 1, 1)
    assert windows[1].start.date() == date(2026, 1, 3)


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


def test_ngram_topic_rejects_gdelt_filters():
    request = _request()
    request.topics[0].include_terms = ["policy"]
    with pytest.raises(ValueError, match="literal query expressions"):
        plan_ngram_windows(request)


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
