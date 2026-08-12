from __future__ import annotations

from datetime import date

from climate_attention.cli import _execute_gdelt_run, _execute_timeline_run, main
from climate_attention.config import config_hash
from climate_attention.models import (
    CollectionRequest,
    DailyTrend,
    QuerySpec,
    RequestLog,
    Topic,
)
from climate_attention.run_state import RunStore
from climate_attention.sources.gdelt import plan_gdelt_windows


def _state(tmp_path):
    config_path = tmp_path / "topics.yaml"
    config_path.write_text(
        "topics:\n  climate:\n    label: Climate\n    queries: [climate]\n",
        encoding="utf-8",
    )
    topic = Topic(
        id="climate", label="Climate", queries=[QuerySpec(expression="climate")]
    )
    request = CollectionRequest(
        start=date(2024, 1, 1), end=date(2024, 1, 1), topics=[topic]
    )
    store = RunStore(tmp_path / "data")
    state = store.create(
        run_id="interrupt-run",
        source="gdelt",
        start=request.start,
        end=request.end,
        config_path=config_path,
        config_sha256=config_hash(config_path),
        topics=[topic],
        provider_options={},
        windows=plan_gdelt_windows(request),
    )
    return store, state


def test_cli_execution_persists_interrupted_status(tmp_path, monkeypatch):
    store, state = _state(tmp_path)

    class InterruptingProvider:
        def __init__(self, *, window_sink, **_):
            self.window_sink = window_sink

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def collect_windows(self, windows):
            self.window_sink("started", windows[0], None, [], [])
            raise KeyboardInterrupt

    monkeypatch.setattr("climate_attention.cli.GDELTProvider", InterruptingProvider)
    exit_code = _execute_gdelt_run(state, tmp_path / "data", store)

    restored = store.load("interrupt-run")
    assert exit_code == 130
    assert restored.status == "interrupted"
    assert restored.status_counts()["running"] == 1
    assert (tmp_path / "data/manifests/interrupt-run.json").exists()


def test_runs_list_and_inspect(tmp_path, capsys):
    _state(tmp_path)
    data_dir = tmp_path / "data"

    assert main(["runs", "list", "--data-dir", str(data_dir)]) == 0
    assert "interrupt-run" in capsys.readouterr().out

    assert (
        main(["runs", "inspect", "interrupt-run", "--data-dir", str(data_dir)])
        == 0
    )
    output = capsys.readouterr().out
    assert "Status:    planned" in output
    assert "pending" in output


def test_timeline_execution_writes_daily_points_and_completes(tmp_path, monkeypatch):
    store, original = _state(tmp_path)
    state = original.model_copy(
        update={
            "run_id": "timeline-run",
            "source": "gdelt_timeline",
            "provider_options": {"country_labels": {"italy": "Italy"}},
        },
        deep=True,
    )
    # Persist under its new run id without invoking create, since this is execution-only.
    store.save(state)
    window = state.resumable_windows()[0]

    class TimelineProvider:
        def __init__(self, *, timeline_sink, **_):
            self.timeline_sink = timeline_sink

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def collect_windows(self, windows):
            current = windows[0]
            self.timeline_sink("started", current, None, [], [])
            trend = DailyTrend(
                record_id="daily-1",
                date=current.start.date(),
                source="gdelt",
                topic_id=current.query.topic_id,
                query_id=current.query.query_id,
                query_expression=current.query.expression,
                geography="italy",
                matched_count=4,
                monitored_count=100,
            )
            log = RequestLog(
                window_id=current.window_id,
                query_id=current.query.query_id,
                topic_id=current.query.topic_id,
                start=current.start,
                end=current.end,
                status="success",
                attempts=1,
                records_returned=1,
                http_status=200,
            )
            self.timeline_sink("success", current, log, [trend], [])

    monkeypatch.setattr(
        "climate_attention.cli.GDELTTimelineProvider", TimelineProvider
    )
    assert _execute_timeline_run(state, tmp_path / "data", store) == 0
    restored = store.load("timeline-run")
    assert restored.status == "complete"
    assert restored.records_newly_stored == 1
    from climate_attention.storage import LocalParquetStorage

    assert len(LocalParquetStorage(tmp_path / "data").read_trends()) == 1


def test_collect_trends_plan_only_creates_frozen_resumable_work(tmp_path, capsys):
    topics = tmp_path / "topics.yaml"
    topics.write_text(
        "topics:\n  climate:\n    label: Climate\n    queries: [climate]\n",
        encoding="utf-8",
    )
    countries = tmp_path / "countries.yaml"
    countries.write_text("countries:\n  italy: Italy\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    code = main(
        [
            "collect-trends",
            "--config",
            str(topics),
            "--countries-config",
            str(countries),
            "--start",
            "2021-01-01",
            "--end",
            "2022-01-02",
            "--plan-only",
            "--data-dir",
            str(data_dir),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "2 planned window(s)" in output
    states = RunStore(data_dir).list()
    assert len(states) == 1
    assert states[0].status == "planned"
    assert states[0].country_config_snapshot_path is not None
    assert len(states[0].resumable_windows()) == 2
