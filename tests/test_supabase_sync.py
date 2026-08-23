from __future__ import annotations

from datetime import date, datetime, timezone

from climate_attention.models import DailyTrend
from climate_attention.storage import LocalParquetStorage
from climate_attention.supabase_sync import (
    MVP_TOPICS,
    _analysis_rows,
    attention_files,
    attention_rows,
    dotenv_value,
)


def test_dotenv_value_reads_named_value_without_mutating_environment(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "IGNORED=value\nSUPABASE_DB_URL='postgresql://example.test/db'\n",
        encoding="utf-8",
    )

    assert dotenv_value("SUPABASE_DB_URL", path) == "postgresql://example.test/db"


def test_attention_rows_map_and_filter_canonical_parquet(tmp_path):
    storage = LocalParquetStorage(tmp_path / "data")
    rows = [
        DailyTrend(
            record_id=f"trend-{day}",
            date=date(2025, 1, day),
            source="gdelt_ngrams",
            topic_id="climate_change",
            query_id="topic_distinct_urls",
            query_expression="climate_change",
            geography="italy",
            matched_count=day,
            political_count=1,
            collected_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
            metadata={"complete": True},
        )
        for day in (1, 2)
    ]
    storage.write_trends(rows)
    files = attention_files(tmp_path / "data", {"climate_change"})

    assert len(files) == 1
    selected = list(
        attention_rows(files[0], start=date(2025, 1, 2), end=date(2025, 1, 2))
    )
    assert len(selected) == 1
    assert selected[0]["record_id"] == "trend-2"
    assert selected[0]["observation_date"] == date(2025, 1, 2)
    assert selected[0]["matched_count"] == 2
    assert "query_expression" not in selected[0]
    assert "metadata" not in selected[0]


def test_supabase_scope_is_two_topic_mvp():
    assert MVP_TOPICS == {"climate_change", "electric_vehicles"}


def test_analysis_rows_map_camel_case_parquet_to_database_columns(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "activity.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [{"activityDate": date(2025, 1, 1), "eventsStarted": 2.0}]
        ),
        path,
    )

    assert list(
        _analysis_rows(
            path,
            {"activity_date": "activityDate", "events_started": "eventsStarted"},
            integer_columns={"events_started"},
        )
    ) == [{"activity_date": date(2025, 1, 1), "events_started": 2}]
