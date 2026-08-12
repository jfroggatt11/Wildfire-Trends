from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from climate_attention.config import Country
from climate_attention.models import CollectionRequest, QuerySpec, Topic
from climate_attention.sources.base import ProviderCollectionError
from climate_attention.sources.google_trends import (
    GoogleTrendsUnofficialProvider,
    plan_google_trends_windows,
    resolve_google_geo,
)


class FakeFrame:
    def __init__(self, rows):
        self._rows = rows
        self.columns = ["climate change", "isPartial"]

    def iterrows(self):
        yield from self._rows


class FakeClient:
    def __init__(self, frame):
        self.frame = frame
        self.payloads = []

    def build_payload(self, keywords, **kwargs):
        self.payloads.append((keywords, kwargs))

    def interest_over_time(self):
        return self.frame


def _request():
    return CollectionRequest(
        start=date(2024, 1, 1),
        end=date(2024, 1, 8),
        topics=[
            Topic(
                id="climate",
                label="Climate",
                queries=[
                    QuerySpec(id="climate_phrase", expression='"climate change"')
                ],
            )
        ],
    )


def test_plan_creates_one_request_per_query_country_and_resolves_geo():
    countries = [
        Country(id="italy", label="Italy"),
        Country(id="unitedstates", label="United States", google_geo="US"),
    ]
    windows, geos = plan_google_trends_windows(_request(), countries)

    assert len(windows) == 2
    assert geos == {"italy": "IT", "unitedstates": "US"}
    assert {window.query.geography for window in windows} == {
        "italy",
        "unitedstates",
    }
    assert all(window.start.date() == date(2024, 1, 1) for window in windows)
    assert resolve_google_geo(countries[0]) == "IT"


def test_plan_rejects_gdelt_boolean_modifiers():
    request = _request()
    request.topics[0].exclude_terms = ["weather"]
    with pytest.raises(ValueError, match="one literal search term"):
        plan_google_trends_windows(
            request, [Country(id="italy", label="Italy", google_geo="IT")]
        )


def test_provider_collects_index_with_scaling_and_resolution_metadata():
    frame = FakeFrame(
        [
            (datetime(2024, 1, 1), {"climate change": 20, "isPartial": False}),
            (datetime(2024, 1, 8), {"climate change": 100, "isPartial": True}),
        ]
    )
    client = FakeClient(frame)
    windows, geos = plan_google_trends_windows(
        _request(), [Country(id="italy", label="Italy", google_geo="IT")]
    )
    events = []
    envelopes = []
    provider = GoogleTrendsUnofficialProvider(
        client=client,
        country_geos=geos,
        request_interval_seconds=0,
        max_retries=0,
        response_sink=envelopes.append,
        timeline_sink=lambda *args: events.append(args),
    )

    result = provider.collect_windows(windows)

    assert [trend.attention_index for trend in result.trends] == [20.0, 100.0]
    assert all(trend.source == "google_trends_unofficial" for trend in result.trends)
    assert all(trend.geography == "italy" for trend in result.trends)
    assert result.trends[0].country_attention_share is None
    metadata = result.trends[0].metadata
    assert metadata["time_resolution"] == "weekly"
    assert metadata["independently_scaled"] is True
    assert metadata["scaling_group_id"]
    assert result.trends[1].metadata["is_partial"] is True
    assert client.payloads == [
        (
            ["climate change"],
            {
                "cat": 0,
                "timeframe": "2024-01-01 2024-01-08",
                "geo": "IT",
                "gprop": "",
            },
        )
    ]
    assert [event[0] for event in events] == ["started", "success"]
    assert envelopes[0]["request"]["scaling_group_id"] == metadata[
        "scaling_group_id"
    ]


def test_provider_retries_and_exposes_partial_failure():
    class FailingClient(FakeClient):
        def interest_over_time(self):
            response = type("Response", (), {"status_code": 429})()
            error = RuntimeError("rate limited")
            error.response = response
            raise error

    windows, geos = plan_google_trends_windows(
        _request(), [Country(id="italy", label="Italy", google_geo="IT")]
    )
    sleeps = []
    provider = GoogleTrendsUnofficialProvider(
        client=FailingClient(FakeFrame([])),
        country_geos=geos,
        request_interval_seconds=0,
        max_retries=1,
        backoff_seconds=2,
        sleep=sleeps.append,
    )

    with pytest.raises(ProviderCollectionError, match="2 attempt") as raised:
        provider.collect_windows(windows)

    assert sleeps == [2]
    assert raised.value.result.requests[0].http_status == 429
    assert raised.value.result.requests[0].attempts == 2
