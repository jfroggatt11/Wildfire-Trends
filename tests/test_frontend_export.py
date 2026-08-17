from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from climate_attention.config import load_country_config
from climate_attention.geography import load_country_boundaries, load_region_boundaries
from scripts.export_frontend_data import FRONTEND_TOPIC_IDS, contiguous_date_ranges


def test_frontend_topic_scope_is_the_two_topic_mvp():
    assert FRONTEND_TOPIC_IDS == {"climate_change", "electric_vehicles"}


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


def test_cornwall_event_point_resolves_to_united_kingdom() -> None:
    countries = load_country_config(ROOT / "config/countries.world.yaml")
    boundaries = load_country_boundaries(
        ROOT / "data/reference/ne_50m_admin_0_countries.geojson",
        countries.countries,
    )

    match = boundaries.assign(-4.75, 50.4167)

    assert match is not None
    assert match.country_id == "unitedkingdom"
    assert match.iso3 == "GBR"


def test_cornwall_event_point_resolves_to_first_order_region() -> None:
    boundaries = load_region_boundaries(
        ROOT / "data/reference/ne_10m_admin_1_states_provinces.geojson.gz"
    )

    match = boundaries.assign(-4.75, 50.4167)

    assert match is not None
    assert match.label == "Cornwall"
    assert match.country_iso3 == "GBR"
