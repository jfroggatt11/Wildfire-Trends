from __future__ import annotations

from datetime import date, datetime, time, timezone

import httpx
import pytest

from climate_attention.config import Country
from climate_attention.models import CollectionRequest, Query, QuerySpec, Topic
from climate_attention.sources.base import ProviderCollectionError
from climate_attention.sources.gdelt import GDELTResponseError, GDELTWindow
from climate_attention.sources.gdelt_timeline import (
    COUNTRY_COVERAGE_TOPIC_ID,
    GDELTSourceCountryProvider,
    GDELTTimelineProvider,
    build_timeline_query,
    compile_source_country_queries,
    compile_topic_queries,
    parse_country_coverage_response,
    parse_source_country_response,
    parse_timeline_response,
    plan_source_country_windows,
    plan_timeline_windows,
)


def _window(days: int = 8):
    return GDELTWindow(
        query=Query(
            topic_id="climate",
            query_id="topic_combined",
            expression='("climate change" OR "global warming")',
            geography="italy",
        ),
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime.combine(date(2024, 1, days), time.max, tzinfo=timezone.utc),
    )


def _payload(days: int = 8):
    return {
        "query_details": {"date_resolution": "day"},
        "timeline": [
            {
                "series": "Volume Intensity",
                "data": [
                    {
                        "date": f"202401{day:02d}T000000Z",
                        "value": day,
                        "norm": 100,
                    }
                    for day in range(1, days + 1)
                ],
            }
        ],
    }


def _source_country_payload(days: int = 8):
    return {
        "query_details": {"date_resolution": "day"},
        "timeline": [
            {
                "series": "Italy Volume Intensity",
                "data": [
                    {
                        "date": f"202401{day:02d}T000000Z",
                        "value": day / 10,
                    }
                    for day in range(1, days + 1)
                ],
            }
        ],
    }


def test_topic_queries_are_or_combined_once_per_country():
    topic = Topic(
        id="climate",
        label="Climate",
        queries=[
            QuerySpec(expression='"climate change"'),
            QuerySpec(expression='"global warming"'),
        ],
    )
    queries = compile_topic_queries(
        [topic], [Country(id="italy", label="Italy"), Country(id="france", label="France")]
    )
    assert len(queries) == 2
    assert queries[0].expression == '("climate change" OR "global warming")'
    assert {query.geography for query in queries} == {"italy", "france"}
    assert all(query.query_id == "topic_combined" for query in queries)


def test_source_country_queries_batch_explicit_countries():
    topic = Topic(
        id="climate", label="Climate", queries=[QuerySpec(expression="climate")]
    )
    countries = [Country(id=f"country{i}", label=f"Country {i}") for i in range(8)]
    queries = compile_source_country_queries([topic], countries, batch_size=7)

    assert len(queries) == 2
    assert len(queries[0].geographies) == 7
    assert len(queries[1].geographies) == 1
    assert queries[0].geography is None
    assert "sourcecountry:country0" in build_timeline_query(
        GDELTWindow(
            query=queries[0],
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 1, 8, tzinfo=timezone.utc),
        )
    )


def test_source_country_planner_reduces_world_request_count():
    topic = Topic(
        id="climate", label="Climate", queries=[QuerySpec(expression="climate")]
    )
    request = CollectionRequest(
        start=date(2021, 8, 12), end=date(2026, 8, 11), topics=[topic]
    )
    countries = [Country(id=f"country{i}", label=f"Country {i}") for i in range(197)]
    windows = plan_source_country_windows(request, countries, batch_size=7)

    assert len(windows) == 29 * 5
    assert all(1 <= len(window.query.geographies) <= 7 for window in windows)


def test_timeline_planner_covers_five_year_range_without_gaps():
    topic = Topic(
        id="climate", label="Climate", queries=[QuerySpec(expression="climate")]
    )
    request = CollectionRequest(
        start=date(2021, 8, 12), end=date(2026, 8, 11), topics=[topic]
    )
    windows = plan_timeline_windows(
        request, [Country(id="italy", label="Italy")], window_days=366
    )
    assert len(windows) == 10
    topic_windows = [
        window
        for window in windows
        if window.query.topic_id != COUNTRY_COVERAGE_TOPIC_ID
    ]
    assert len(topic_windows) == 5
    assert topic_windows[0].start.date() == request.start
    assert topic_windows[-1].end.date() == request.end
    assert all(
        left.end.date().toordinal() + 1 == right.start.date().toordinal()
        for left, right in zip(topic_windows, topic_windows[1:])
    )


def test_parse_raw_timeline_counts_and_normalization():
    collected_at = datetime(2024, 2, 1, tzinfo=timezone.utc)
    trends = parse_timeline_response(
        _payload(), _window(), collected_at, {"italy": "Italy"}
    )
    assert len(trends) == 8
    assert trends[0].matched_count == 1
    assert trends[0].source == "gdelt"
    assert trends[0].global_monitored_count == 100
    assert trends[0].global_attention_share == 0.01
    assert trends[0].country_monitored_count is None
    assert trends[0].country_attention_share is None
    assert trends[0].geography == "italy"
    assert trends[0].metadata["geography_label"] == "Italy"
    assert len({trend.record_id for trend in trends}) == 8


def test_country_coverage_window_and_parser():
    topic = Topic(
        id="climate", label="Climate", queries=[QuerySpec(expression="climate")]
    )
    request = CollectionRequest(
        start=date(2024, 1, 1), end=date(2024, 1, 8), topics=[topic]
    )
    windows = plan_timeline_windows(
        request, [Country(id="italy", label="Italy")]
    )
    baseline = next(
        window
        for window in windows
        if window.query.topic_id == COUNTRY_COVERAGE_TOPIC_ID
    )
    assert build_timeline_query(baseline) == "sourcecountry:italy"
    coverage = parse_country_coverage_response(
        _payload(),
        baseline,
        datetime(2024, 2, 1, tzinfo=timezone.utc),
        {"italy": "Italy"},
    )
    assert len(coverage) == 8
    assert coverage[0].country_monitored_count == 1
    assert coverage[0].global_monitored_count == 100
    assert coverage[0].geography == "italy"


def test_parse_source_country_percentage_and_omitted_zero_series():
    query = Query(
        topic_id="climate",
        query_id="topic_combined",
        expression="climate",
        geographies=["italy", "malta"],
    )
    window = GDELTWindow(
        query=query,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime.combine(date(2024, 1, 8), time.max, tzinfo=timezone.utc),
    )
    trends = parse_source_country_response(
        _source_country_payload(),
        window,
        datetime(2024, 2, 1, tzinfo=timezone.utc),
        {"italy": "Italy", "malta": "Malta"},
    )

    assert len(trends) == 16
    italy = [trend for trend in trends if trend.geography == "italy"]
    malta = [trend for trend in trends if trend.geography == "malta"]
    assert italy[0].matched_count is None
    assert italy[0].country_attention_share == pytest.approx(0.001)
    assert italy[0].metadata["reported_percentage"] == pytest.approx(0.1)
    assert italy[0].metadata["series"] == "Italy Volume Intensity"
    assert all(trend.country_attention_share == 0 for trend in malta)
    assert all(trend.metadata["series_omitted_as_zero"] for trend in malta)
    assert len({trend.record_id for trend in trends}) == 16


def test_missing_day_fails_explicitly():
    payload = _payload()
    payload["timeline"][0]["data"].pop()
    with pytest.raises(GDELTResponseError, match="missing"):
        parse_timeline_response(
            payload,
            _window(),
            datetime(2024, 2, 1, tzinfo=timezone.utc),
            {"italy": "Italy"},
        )


def test_timeline_provider_uses_raw_mode_and_emits_checkpoint():
    calls = []
    events = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(200, json=_payload())

    provider = GDELTTimelineProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        country_labels={"italy": "Italy"},
        timeline_sink=lambda *event: events.append(event),
        request_interval_seconds=0,
    )
    result = provider.collect_windows([_window()])

    assert len(result.trends) == 8
    assert [event[0] for event in events] == ["started", "success"]
    url = str(calls[0].url)
    assert "mode=timelinevolraw" in url
    assert "sourcecountry%3Aitaly" in url
    assert "maxrecords" not in url


def test_timeline_provider_collects_operator_only_country_baseline():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(200, json=_payload())

    topic = Topic(
        id="climate", label="Climate", queries=[QuerySpec(expression="climate")]
    )
    request = CollectionRequest(
        start=date(2024, 1, 1), end=date(2024, 1, 8), topics=[topic]
    )
    baseline = next(
        window
        for window in plan_timeline_windows(
            request, [Country(id="italy", label="Italy")]
        )
        if window.query.topic_id == COUNTRY_COVERAGE_TOPIC_ID
    )
    provider = GDELTTimelineProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        country_labels={"italy": "Italy"},
        request_interval_seconds=0,
    )
    result = provider.collect_windows([baseline])

    assert result.trends == []
    assert len(result.country_coverages) == 8
    assert calls[0].url.params["query"] == "sourcecountry:italy"


def test_source_country_provider_uses_native_mode():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(200, json=_source_country_payload())

    query = Query(
        topic_id="climate",
        query_id="topic_combined",
        expression="climate",
        geographies=["italy"],
    )
    window = GDELTWindow(
        query=query,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime.combine(date(2024, 1, 8), time.max, tzinfo=timezone.utc),
    )
    provider = GDELTSourceCountryProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        country_labels={"italy": "Italy"},
        request_interval_seconds=0,
    )
    result = provider.collect_windows([window])

    assert len(result.trends) == 8
    assert calls[0].url.params["mode"] == "timelinesourcecountry"
    assert calls[0].url.params["query"] == "climate sourcecountry:italy"


def test_timeline_http_failure_is_explicit():
    provider = GDELTTimelineProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, text="rate limited")
            )
        ),
        country_labels={"italy": "Italy"},
        max_retries=0,
        request_interval_seconds=0,
    )
    with pytest.raises(ProviderCollectionError, match="429") as raised:
        provider.collect_windows([_window()])
    assert raised.value.result.requests[-1].status == "failed"
