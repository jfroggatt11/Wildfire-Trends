from __future__ import annotations

from datetime import datetime, timezone

from climate_attention.aggregation import aggregate_daily
from climate_attention.storage import LocalParquetStorage


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

