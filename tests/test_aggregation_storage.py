from __future__ import annotations

from datetime import datetime, timezone

from climate_attention.aggregation import aggregate_daily
from climate_attention.storage import LocalParquetStorage
from climate_attention.models import DailyCountryCoverage, DailyTrend


def test_aggregation_deduplicates_and_groups(record_factory):
    first = record_factory()
    duplicate = first.model_copy(deep=True)
    french = record_factory(
        record_id="record-2",
        url="https://example.com/fr",
        language="French",
    )
    rows = aggregate_daily([first, duplicate, french])
    assert [(row.language, row.count) for row in rows] == [
        ("English", 1),
        ("French", 1),
    ]


def test_parquet_storage_round_trip_and_idempotency(tmp_path, record_factory):
    storage = LocalParquetStorage(tmp_path / "data")
    record = record_factory()
    assert storage.write_records([record]) == 1
    assert storage.write_records([record]) == 0

    restored = storage.read_records(source="gdelt")
    assert len(restored) == 1
    assert restored[0] == record
    assert restored[0].metadata["socialimage"].endswith("image.jpg")

    daily = aggregate_daily(restored)
    path = storage.write_daily(daily)
    assert path.exists()
    assert storage.read_daily() == daily


def test_storage_date_filter(tmp_path, record_factory):
    storage = LocalParquetStorage(tmp_path / "data")
    storage.write_records(
        [
            record_factory(),
            record_factory(
                record_id="later",
                published_at=datetime(2024, 2, 2, tzinfo=timezone.utc),
            ),
        ]
    )
    result = storage.read_records(
        start=datetime(2024, 2, 1).date(), end=datetime(2024, 2, 28).date()
    )
    assert [record.record_id for record in result] == ["later"]


def test_trend_storage_round_trip_and_upsert(tmp_path):
    storage = LocalParquetStorage(tmp_path / "data")
    trend = DailyTrend(
        record_id="trend-1",
        date=datetime(2024, 1, 2).date(),
        source="gdelt",
        topic_id="climate",
        query_id="topic_combined",
        query_expression="climate",
        geography="italy",
        matched_count=10,
        global_monitored_count=100,
        global_attention_share=0.1,
        collected_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        metadata={"geography_label": "Italy"},
    )
    assert storage.write_trends([trend]) == 1
    assert storage.write_trends([trend]) == 0
    restored = storage.read_trends(
        source="gdelt", topics={"climate"}, geographies={"italy"}
    )
    assert restored == [trend]


def test_google_trend_index_round_trip(tmp_path):
    storage = LocalParquetStorage(tmp_path / "data")
    trend = DailyTrend(
        record_id="google-trend-1",
        date=datetime(2024, 1, 2).date(),
        source="google_trends_unofficial",
        topic_id="climate",
        query_id="climate_phrase",
        query_expression="climate change",
        geography="italy",
        attention_index=73,
        collected_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        metadata={"scaling_group_id": "scale-1", "time_resolution": "daily"},
    )

    assert storage.write_trends([trend]) == 1
    assert storage.read_trends(source="google_trends_unofficial") == [trend]


def test_country_coverage_enriches_existing_and_new_trends(tmp_path):
    storage = LocalParquetStorage(tmp_path / "data")
    trend = DailyTrend(
        record_id="trend-1",
        date=datetime(2024, 1, 2).date(),
        source="gdelt",
        topic_id="climate",
        query_id="topic_combined",
        query_expression="climate",
        geography="italy",
        matched_count=10,
        global_monitored_count=1000,
        collected_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    storage.write_trends([trend])
    coverage = DailyCountryCoverage(
        record_id="coverage-1",
        date=trend.date,
        source="gdelt",
        geography="italy",
        country_monitored_count=200,
        global_monitored_count=1000,
        collected_at=trend.collected_at,
    )
    assert storage.write_country_coverages([coverage]) == 1

    restored = storage.read_trends()
    assert restored[0].country_monitored_count == 200
    assert restored[0].country_attention_share == 0.05
    assert restored[0].global_attention_share == 0.01
    assert restored[0].metadata["country_coverage_record_id"] == "coverage-1"
    assert storage.read_country_coverages() == [coverage]


def test_complementary_trend_modes_merge_without_losing_counts(tmp_path):
    storage = LocalParquetStorage(tmp_path / "data")
    day = datetime(2024, 1, 2).date()
    collected_at = datetime(2024, 2, 1, tzinfo=timezone.utc)
    normalized = DailyTrend(
        record_id="shared-trend",
        date=day,
        source="gdelt",
        topic_id="climate",
        query_id="topic_combined",
        query_expression="climate",
        geography="italy",
        country_attention_share=0.04,
        collected_at=collected_at,
        metadata={"collection_mode": "timelinesourcecountry"},
    )
    raw = normalized.model_copy(
        update={
            "matched_count": 8,
            "global_monitored_count": 1000,
            "global_attention_share": 0.008,
            "country_attention_share": None,
            "metadata": {"raw_mode": "timelinevolraw"},
        }
    )

    assert storage.write_trends([normalized]) == 1
    assert storage.write_trends([raw]) == 0
    restored = storage.read_trends()[0]
    assert restored.matched_count == 8
    assert restored.global_attention_share == 0.008
    assert restored.country_attention_share == 0.04
    assert restored.metadata["collection_mode"] == "timelinesourcecountry"
    assert restored.metadata["raw_mode"] == "timelinevolraw"
