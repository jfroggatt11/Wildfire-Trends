from __future__ import annotations

import csv
from datetime import date, datetime, timezone

from climate_attention.cli import _execute_gdelt_run, _execute_timeline_run, main
from climate_attention.config import config_hash
from climate_attention.models import (
    ArticleMatchEvidence,
    CollectionRequest,
    DailyTrend,
    PoliticalArticleSample,
    QuerySpec,
    RequestLog,
    Topic,
)
from climate_attention.run_state import RunStore
from climate_attention.sources.gdelt import plan_gdelt_windows
from climate_attention.storage import LocalParquetStorage


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


def test_runs_retry_can_raise_ngram_billing_cap(tmp_path, monkeypatch):
    store, original = _state(tmp_path)
    state = original.model_copy(
        update={
            "source": "gdelt_ngrams",
            "provider_options": {"maximum_bytes_billed": 30_000_000_000},
        },
        deep=True,
    )
    store.save(state)
    observed = {}

    def fake_execute(current, *_):
        observed.update(current.provider_options)
        return 0

    monkeypatch.setattr("climate_attention.cli._execute_timeline_run", fake_execute)

    assert main(
        [
            "runs",
            "retry",
            "interrupt-run",
            "--maximum-gb-billed",
            "40",
            "--data-dir",
            str(tmp_path / "data"),
        ]
    ) == 0

    assert observed["maximum_bytes_billed"] == 40_000_000_000
    assert store.load("interrupt-run").provider_options["maximum_bytes_billed"] == (
        40_000_000_000
    )


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
                global_monitored_count=100,
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
    assert "mode=country-share" in output
    assert "one global country breakdown" in output
    assert "matched_count remains null" in output
    states = RunStore(data_dir).list()
    assert len(states) == 1
    assert states[0].status == "planned"
    assert states[0].country_config_snapshot_path is not None
    assert states[0].source == "gdelt_source_country"
    assert len(states[0].resumable_windows()) == 2
    assert all(
        window.query.geographies == []
        for window in states[0].resumable_windows()
    )


def test_collect_trends_raw_mode_retains_count_and_baseline_plan(tmp_path, capsys):
    topics = tmp_path / "topics.yaml"
    topics.write_text(
        "topics:\n  climate:\n    label: Climate\n    queries: [climate]\n",
        encoding="utf-8",
    )
    countries = tmp_path / "countries.yaml"
    countries.write_text("countries:\n  italy: Italy\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    assert main(
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
            "--trend-mode",
            "raw-counts",
            "--plan-only",
            "--data-dir",
            str(data_dir),
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "4 planned window(s)" in output
    assert "2 country-coverage baseline window(s)" in output


def test_collect_google_trends_plan_only_is_country_scoped_and_resumable(
    tmp_path, capsys
):
    topics = tmp_path / "topics.yaml"
    topics.write_text(
        "topics:\n  climate:\n    label: Climate\n"
        "    queries:\n      - id: climate_phrase\n"
        "        expression: '\"climate change\"'\n",
        encoding="utf-8",
    )
    countries = tmp_path / "countries.yaml"
    countries.write_text(
        "countries:\n  italy:\n    label: Italy\n    google_geo: IT\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"

    assert main(
        [
            "collect-google-trends",
            "--config",
            str(topics),
            "--countries-config",
            str(countries),
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-31",
            "--plan-only",
            "--data-dir",
            str(data_dir),
        ]
    ) == 0

    output = capsys.readouterr().out
    assert "1 planned request(s)" in output
    assert "separate 0-100 scaling group" in output
    state = RunStore(data_dir).list()[0]
    assert state.source == "google_trends_unofficial"
    assert state.provider_options["country_geos"] == {"italy": "IT"}
    assert state.provider_options["request_interval_seconds"] == 30.0
    assert len(state.resumable_windows()) == 1


def test_collect_ngrams_plan_only_freezes_billing_cap_and_queries(tmp_path, capsys):
    topics = tmp_path / "topics.yaml"
    topics.write_text(
        "topics:\n  climate:\n    label: Climate\n"
        "    queries: ['\"climate change\"']\n",
        encoding="utf-8",
    )
    countries = tmp_path / "countries.yaml"
    countries.write_text("countries:\n  italy: Italy\n", encoding="utf-8")
    data_dir = tmp_path / "data"

    assert main(
        [
            "collect-ngrams",
            "--config",
            str(topics),
            "--countries-config",
            str(countries),
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-31",
            "--billing-project",
            "research-project",
            "--maximum-gb-billed",
            "2.5",
            "--maximum-total-gb-billed",
            "75",
            "--plan-only",
            "--data-dir",
            str(data_dir),
        ]
    ) == 0

    output = capsys.readouterr().out
    assert "1 BigQuery job(s)" in output
    state = RunStore(data_dir).list()[0]
    assert state.source == "gdelt_ngrams"
    assert state.provider_options["billing_project"] == "research-project"
    assert state.provider_options["maximum_bytes_billed"] == 2_500_000_000
    assert state.provider_options["maximum_total_bytes_billed"] == 75_000_000_000
    assert state.provider_options["preflight_estimated_bytes"] is None
    assert state.provider_options["topic_phrases"]["climate"][0] == {
        "text": "climate change",
        "language": None,
        "segmentation": "space",
        "translation_status": "validated",
        "notes": "legacy query fallback",
    }
    assert state.provider_options["include_denominator"] is False
    assert state.provider_options["batch_topics"] is True


def test_export_articles_writes_reviewable_political_csv(tmp_path, capsys):
    data_dir = tmp_path / "data"
    storage = LocalParquetStorage(data_dir)
    storage.write_matched_articles(
        [
            PoliticalArticleSample(
                record_id="article-1",
                date=date(2025, 1, 1),
                topic_id="climate_change",
                geography="italy",
                url="https://example.it/climate",
                title="Climate policy",
                language="it",
                political_actor=True,
                match_evidence=[
                    ArticleMatchEvidence(
                        evidence_kind="topic",
                        dimension_id="climate_change",
                        phrase="climate change",
                        phrase_language="en",
                        segmentation="space",
                        context="about climate change policy",
                    )
                ],
                match_evidence_total=1,
                collected_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
                metadata={"complete_article_panel": True},
            )
        ]
    )
    output = tmp_path / "exports" / "articles.csv"

    assert main(
        [
            "export-articles",
            "--start",
            "2025-01-01",
            "--end",
            "2025-01-01",
            "--data-dir",
            str(data_dir),
            "--output",
            str(output),
        ]
    ) == 0

    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["political"] == "True"
    assert rows[0]["political_actor"] == "True"
    assert rows[0]["title"] == "Climate policy"
    assert rows[0]["matched_topic_phrases"] == "climate change"
    assert "about climate change policy" in rows[0]["match_evidence_json"]
    assert '"complete_article_panel": true' in rows[0]["metadata_json"]
    assert "Exported 1 article classification row" in capsys.readouterr().out
