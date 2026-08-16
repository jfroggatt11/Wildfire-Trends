from scripts.export_frontend_data import contiguous_date_ranges


def test_contiguous_date_ranges_preserves_gaps() -> None:
    values = [
        "2025-01-01",
        "2025-02-01",
        "2025-02-02",
        "2025-02-14",
        "2025-02-14",
    ]

    assert contiguous_date_ranges(values) == [
        {"start": "2025-01-01", "end": "2025-01-01", "dayCount": 1},
        {"start": "2025-02-01", "end": "2025-02-02", "dayCount": 2},
        {"start": "2025-02-14", "end": "2025-02-14", "dayCount": 1},
    ]


def test_contiguous_date_ranges_accepts_timestamp_values() -> None:
    assert contiguous_date_ranges(["2025-01-01T01:00:00+00:00", "2025-01-02T01:00:00+00:00"]) == [
        {"start": "2025-01-01", "end": "2025-01-02", "dayCount": 2}
    ]
