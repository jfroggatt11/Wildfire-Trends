from __future__ import annotations

from datetime import date, datetime, time, timezone

import httpx
import pytest

from climate_attention.config import Country
from climate_attention.models import CollectionRequest, Query, QuerySpec, Topic
from climate_attention.sources.base import ProviderCollectionError
from climate_attention.sources.gdelt import GDELTResponseError, GDELTWindow
from climate_attention.sources.gdelt_timeline import (
    GDELTTimelineProvider,
    compile_topic_queries,
    parse_timeline_response,
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
    assert len(windows) == 5
    assert windows[0].start.date() == request.start
    assert windows[-1].end.date() == request.end
    assert all(
        left.end.date().toordinal() + 1 == right.start.date().toordinal()
        for left, right in zip(windows, windows[1:])
    )


def test_parse_raw_timeline_counts_and_normalization():
    collected_at = datetime(2024, 2, 1, tzinfo=timezone.utc)
    trends = parse_timeline_response(
        _payload(), _window(), collected_at, {"italy": "Italy"}
    )
    assert len(trends) == 8
    assert trends[0].matched_count == 1
    assert trends[0].source == "gdelt"
    assert trends[0].monitored_count == 100
    assert trends[0].attention_share == 0.01
    assert trends[0].geography == "italy"
    assert trends[0].metadata["geography_label"] == "Italy"
    assert len({trend.record_id for trend in trends}) == 8


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
