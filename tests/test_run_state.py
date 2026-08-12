from __future__ import annotations

from datetime import date

import httpx
import pytest

from climate_attention.config import config_hash
from climate_attention.models import CollectionRequest, QuerySpec, Topic
from climate_attention.run_state import RunStore
from climate_attention.sources.base import ProviderCollectionError
from climate_attention.sources.gdelt import GDELTProvider, plan_gdelt_windows
from climate_attention.storage import LocalParquetStorage


def _article(number: int):
    return {
        "url": f"https://example.com/{number}",
        "title": f"Story {number}",
        "seendate": "20240102T123000Z",
        "domain": "example.com",
        "language": "English",
        "sourcecountry": "United States",
    }


def _create_state(tmp_path):
    config_path = tmp_path / "topics.yaml"
    config_path.write_text(
        'topics:\n  climate:\n    label: Climate\n    queries: [\'"climate change"\']\n',
        encoding="utf-8",
    )
    topic = Topic(
        id="climate",
        label="Climate",
        queries=[QuerySpec(id="phrase", expression='"climate change"')],
    )
    request = CollectionRequest(
        start=date(2024, 1, 2), end=date(2024, 1, 2), topics=[topic]
    )
    store = RunStore(tmp_path / "data")
    state = store.create(
        run_id="test-run",
        source="gdelt",
        start=request.start,
        end=request.end,
        config_path=config_path,
        config_sha256=config_hash(config_path),
        topics=[topic],
        provider_options={
            "timeout": 30,
            "max_retries": 0,
            "request_interval_seconds": 0,
            "backoff_seconds": 0,
        },
        windows=plan_gdelt_windows(request),
    )
    return store, state


def test_run_store_round_trip_and_config_snapshot(tmp_path):
    store, state = _create_state(tmp_path)
    restored = store.load(state.run_id)

    assert restored == state
    assert restored.status_counts()["pending"] == 1
    assert (tmp_path / "data/runs/test-run/config.yaml").exists()
    assert [item.run_id for item in store.list()] == ["test-run"]


def test_failed_split_run_resumes_only_unfinished_leaf(tmp_path):
    store, state = _create_state(tmp_path)
    storage = LocalParquetStorage(tmp_path / "data")
    calls = 0

    def first_handler(_: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"articles": [_article(1), _article(2)]})
        if calls == 2:
            return httpx.Response(200, json={"articles": [_article(1)]})
        return httpx.Response(503, text="temporarily unavailable")

    def checkpoint(event, window, log, records, children):
        if event == "success":
            state.records_newly_stored += storage.write_records(records)
        state.apply_window_event(event, window, log, children)
        store.save(state)

    provider = GDELTProvider(
        client=httpx.Client(transport=httpx.MockTransport(first_handler)),
        max_records=2,
        max_retries=0,
        request_interval_seconds=0,
        backoff_seconds=0,
        window_sink=checkpoint,
    )
    with pytest.raises(ProviderCollectionError):
        provider.collect_windows(state.resumable_windows())

    restored = store.load("test-run")
    assert restored.status_counts() == {
        "pending": 0,
        "running": 0,
        "success": 1,
        "failed": 1,
        "split": 1,
    }
    assert storage.write_records(storage.read_records()) == 0
    unfinished = restored.resumable_windows()
    assert len(unfinished) == 1
    assert unfinished[0].start.hour == 12

    resumed_calls = 0

    def resumed_handler(_: httpx.Request):
        nonlocal resumed_calls
        resumed_calls += 1
        return httpx.Response(200, json={"articles": [_article(2)]})

    state = restored

    def resumed_checkpoint(event, window, log, records, children):
        if event == "success":
            state.records_newly_stored += storage.write_records(records)
        state.apply_window_event(event, window, log, children)
        store.save(state)

    resumed = GDELTProvider(
        client=httpx.Client(transport=httpx.MockTransport(resumed_handler)),
        max_records=2,
        max_retries=0,
        request_interval_seconds=0,
        backoff_seconds=0,
        window_sink=resumed_checkpoint,
    )
    resumed.collect_windows(unfinished)

    final = store.load("test-run")
    assert resumed_calls == 1
    assert final.is_complete()
    assert final.records_newly_stored == 2
    assert len(storage.read_records()) == 2


def test_interrupt_leaves_started_window_resumable(tmp_path):
    store, state = _create_state(tmp_path)

    def checkpoint(event, window, log, records, children):
        state.apply_window_event(event, window, log, children)
        store.save(state)

    def interrupt(_: httpx.Request):
        raise KeyboardInterrupt

    provider = GDELTProvider(
        client=httpx.Client(transport=httpx.MockTransport(interrupt)),
        request_interval_seconds=0,
        window_sink=checkpoint,
    )
    with pytest.raises(KeyboardInterrupt):
        provider.collect_windows(state.resumable_windows())

    restored = store.load("test-run")
    assert restored.status_counts()["running"] == 1
    assert len(restored.resumable_windows()) == 1

