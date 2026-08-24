from datetime import date, datetime, timezone

from climate_attention.models import DailyTrend
from climate_attention.source_coverage import (
    available_date_segments,
    is_known_outage,
    remove_known_outage_rows,
)
from climate_attention.storage import LocalParquetStorage


def test_confirmed_gdelt_outage_is_inclusive_and_source_specific():
    assert is_known_outage("gdelt_ngrams", date(2025, 6, 14))
    assert is_known_outage("gdelt_ngrams", "2025-07-01")
    assert not is_known_outage("gdelt_ngrams", date(2025, 6, 13))
    assert not is_known_outage("gdelt_ngrams", date(2025, 7, 2))
    assert not is_known_outage("gdacs", date(2025, 6, 20))


def test_available_segments_split_around_confirmed_outage():
    assert available_date_segments(
        "gdelt_ngrams", date(2025, 6, 12), date(2025, 7, 3)
    ) == [
        (date(2025, 6, 12), date(2025, 6, 13)),
        (date(2025, 7, 2), date(2025, 7, 3)),
    ]


def test_repair_removes_only_known_outage_rows(tmp_path):
    data_dir = tmp_path / "data"
    storage = LocalParquetStorage(data_dir)
    storage.write_trends(
        [
            DailyTrend(
                record_id=f"trend-{day}",
                date=day,
                source="gdelt_ngrams",
                topic_id="climate_change",
                query_id="topic_distinct_urls",
                query_expression="climate change",
                geography="italy",
                matched_count=0,
                collected_at=datetime(2025, 7, 3, tzinfo=timezone.utc),
            )
            for day in (date(2025, 6, 13), date(2025, 6, 14), date(2025, 7, 1), date(2025, 7, 2))
        ]
    )

    removed, files = remove_known_outage_rows(data_dir)
    remaining = storage.read_trends(source="gdelt_ngrams")

    assert (removed, files) == (2, 1)
    assert [row.date for row in remaining] == [date(2025, 6, 13), date(2025, 7, 2)]
