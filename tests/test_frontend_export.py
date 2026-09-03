import json
from datetime import date
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from climate_attention.config import load_country_config
from climate_attention.geography import load_country_boundaries, load_region_boundaries
from climate_attention.models import LandSurfaceObservation
from climate_attention.storage import LocalParquetStorage
from scripts.export_frontend_data import (
    FRONTEND_HAZARD_TYPES,
    FRONTEND_TOPIC_IDS,
    contiguous_date_ranges,
    export_satellite_observations,
    requested_date_ranges,
)


def test_frontend_topic_scope_is_the_two_topic_mvp():
    assert FRONTEND_TOPIC_IDS == {"climate_change", "electric_vehicles"}


def test_frontend_hazard_scope_excludes_cyclones():
    assert FRONTEND_HAZARD_TYPES == {"wildfire", "flood"}


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


def test_requested_date_ranges_merges_successful_collection_windows(tmp_path, monkeypatch) -> None:
    manifests = tmp_path / "data" / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "one.json").write_text(
        '{"source":"gdacs","requested_date_range":{"start":"2025-01-01","end":"2025-12-31"}}'
    )
    (manifests / "two.json").write_text(
        '{"source":"gdacs","requested_date_range":{"start":"2026-01-01","end":"2026-08-26"}}'
    )
    (manifests / "failed.json").write_text(
        '{"source":"gdacs","requested_date_range":{"start":"2027-01-01","end":"2027-01-31"},"error":"failed"}'
    )
    monkeypatch.setattr("scripts.export_frontend_data.ROOT", tmp_path)

    assert requested_date_ranges("gdacs") == [
        {"start": "2025-01-01", "end": "2026-08-26", "dayCount": 603}
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


def test_satellite_export_contains_only_compact_attention_window_rows(tmp_path, monkeypatch) -> None:
    store = LocalParquetStorage(tmp_path / "data")
    store.write_land_surface([
        LandSurfaceObservation(
            record_id="satellite:test",
            date=date(2025, 1, 17),
            source="nasa_modis",
            product="MOD13A2.061",
            metric="ndvi",
            geography="italy",
            country_iso3="ITA",
            value=0.55,
            unit="index",
            period_days=16,
            valid_pixel_count=100,
            anomaly=0.03,
            baseline_start_year=2001,
            baseline_end_year=2020,
        ),
        LandSurfaceObservation(
            record_id="satellite:outside",
            date=date(2024, 12, 19),
            source="nasa_modis",
            product="MOD13A2.061",
            metric="ndvi",
            geography="italy",
            country_iso3="ITA",
            value=0.50,
            unit="index",
            period_days=16,
            valid_pixel_count=100,
            anomaly=0.01,
        ),
    ])
    output = tmp_path / "public"
    monkeypatch.setattr("scripts.export_frontend_data.ROOT", tmp_path)
    monkeypatch.setattr("scripts.export_frontend_data.OUT", output)

    summary = export_satellite_observations("2025-01-01", "2025-12-31")
    payload = json.loads((output / "satellite-observations.json").read_text())

    assert summary["observationCount"] == 1
    assert payload["observations"][0]["geography"] == "italy"
    assert payload["observations"][0]["anomaly"] == 0.03
    assert "metadata" not in payload["observations"][0]
