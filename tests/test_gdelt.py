from __future__ import annotations

from datetime import date

import httpx
import pytest

from climate_attention.models import CollectionRequest, Query, QuerySpec, Topic
from climate_attention.sources.base import ProviderCollectionError
from climate_attention.sources.gdelt import (
    GDELTProvider,
    build_gdelt_query,
    parse_article,
)


def article(number: int = 1):
    return {
        "url": f"https://example.com/{number}",
        "url_mobile": "",
        "title": f"Story {number}",
        "seendate": "20240102T123000Z",
        "socialimage": "https://example.com/image.jpg",
        "domain": "example.com",
        "language": "English",
        "sourcecountry": "United States",
    }


def request():
    topic = Topic(
        id="climate",
        label="Climate",
        queries=[QuerySpec(id="phrase", expression='"climate change"')],
    )
    return CollectionRequest(
        start=date(2024, 1, 2), end=date(2024, 1, 2), topics=[topic]
    )


def test_build_gdelt_query_includes_dimensions_and_terms():
    query = Query(
        topic_id="climate",
        query_id="phrase",
        expression='"climate change"',
        include_terms=["public policy"],
        exclude_terms=["movie"],
        language="English",
        geography="US",
    )
    assert build_gdelt_query(query) == (
        '"climate change" "public policy" -movie '
        "sourcelang:English sourcecountry:US"
    )


def test_gdelt_response_parsing_preserves_metadata():
    query = Query(topic_id="climate", query_id="phrase", expression="climate")
    from datetime import datetime, timezone

    record = parse_article(article(), query, datetime(2024, 2, 1, tzinfo=timezone.utc))
    assert record.title == "Story 1"
    assert record.published_at.isoformat() == "2024-01-02T12:30:00+00:00"
    assert record.source_country == "United States"
    assert record.metadata["socialimage"].endswith("image.jpg")
    assert len(record.record_id) == 64


def test_retry_after_rate_limit_then_succeeds():
    calls = []
    sleeps = []

    def handler(incoming: httpx.Request):
        calls.append(incoming)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"articles": [article()]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GDELTProvider(client=client, sleep=sleeps.append)
    result = provider.collect(request())

    assert len(result.records) == 1
    assert result.requests[0].attempts == 2
    assert sleeps[0] == 0.0
    assert sleeps[1] == pytest.approx(6.0, abs=0.01)
    assert "startdatetime=20240102000000" in str(calls[-1].url)
    assert "enddatetime=20240102235959" in str(calls[-1].url)


def test_server_errors_retry_and_surface_partial_result():
    calls = 0

    def handler(_: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="unavailable")

    provider = GDELTProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=2,
        sleep=lambda _: None,
    )
    with pytest.raises(ProviderCollectionError, match="3 attempt") as raised:
        provider.collect(request())
    assert calls == 3
    assert raised.value.result.requests[-1].status == "failed"
    assert raised.value.result.requests[-1].http_status == 503


def test_saturated_response_is_split_and_deduplicated():
    calls = 0

    def handler(_: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"articles": [article(1), article(2)]})
        if calls == 2:
            return httpx.Response(200, json={"articles": [article(1)]})
        return httpx.Response(200, json={"articles": [article(2)]})

    provider = GDELTProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_records=2,
        sleep=lambda _: None,
    )
    result = provider.collect(request())
    assert calls == 3
    assert {item.title for item in result.records} == {"Story 1", "Story 2"}


def test_provider_options_are_validated():
    with pytest.raises(ValueError, match="max_retries"):
        GDELTProvider(max_retries=-1)
    with pytest.raises(ValueError, match="limit of 250"):
        GDELTProvider(max_records=251)
    with pytest.raises(ValueError, match="request_interval_seconds"):
        GDELTProvider(request_interval_seconds=-1)
