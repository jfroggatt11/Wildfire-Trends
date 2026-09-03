from datetime import date

import pytest

from climate_attention.config import Country
from climate_attention.geography import CountryBoundary, CountryBoundaryIndex
from climate_attention.models import LandSurfaceObservation
from climate_attention.satellite import (
    MODIS_NDVI_LAYER,
    add_burned_area_region_rollups,
    add_region_rollups,
    add_seasonal_anomalies,
    build_appeears_area_task,
    burned_area_observations_from_values,
    parse_appeears_vegetation_statistics,
)
from climate_attention.storage import LocalParquetStorage


def _observation(year: int, geography: str, value: float, pixels: int = 100):
    return LandSurfaceObservation(
        record_id=f"sat:{year}:{geography}",
        date=date(year, 7, 12),
        source="nasa_modis",
        product="MOD13A2.061",
        metric="ndvi",
        geography=geography,
        country_iso3="ITA" if geography == "italy" else "FRA",
        value=value,
        unit="index",
        period_days=16,
        valid_pixel_count=pixels,
    )


def test_build_appeears_request_has_stable_country_feature_mapping():
    square = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    }
    boundaries = CountryBoundaryIndex([
        CountryBoundary("italy", "ITA", (0, 0, 1, 1), square),
        CountryBoundary("france", "FRA", (0, 0, 1, 1), square),
    ])
    task, aid_map = build_appeears_area_task(
        countries=[Country(id="italy", label="Italy"), Country(id="france", label="France")],
        boundaries=boundaries,
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        task_name="test",
    )

    assert task["params"]["layers"] == [
        {"product": "MOD13A2.061", "layer": MODIS_NDVI_LAYER}
    ]
    assert [feature["id"] for feature in task["params"]["geo"]["features"]] == [
        "aid0001", "aid0002"
    ]
    assert aid_map["aid0001"]["geography"] == "france"
    assert aid_map["aid0002"]["geography"] == "italy"


def test_parse_statistics_and_calculate_same_season_anomaly(tmp_path):
    statistics_path = tmp_path / "MOD13A2-061-Statistics.csv"
    statistics_path.write_text(
        "File Name,Dataset,aid,Date,Count,Minimum,Maximum,Range,Mean\n"
        "MOD13A2.061_NDVI_20250712_aid0001,_1_km_16_days_NDVI,aid0001,07/12/2025,42,-0.1,0.9,1.0,0.62\n",
        encoding="utf-8",
    )
    parsed = parse_appeears_vegetation_statistics(
        statistics_path,
        aid_map={"aid0001": {"geography": "italy", "country_iso3": "ITA"}},
    )

    assert len(parsed) == 1
    assert parsed[0].geography == "italy"
    assert parsed[0].value == 0.62
    assert parsed[0].valid_pixel_count == 42

    baseline = [_observation(year, "italy", 0.40 + (year - 2001) * 0.01) for year in range(2001, 2006)]
    normalized = add_seasonal_anomalies([*baseline, parsed[0]])
    current = next(item for item in normalized if item.date.year == 2025)
    assert current.anomaly == pytest.approx(0.2)
    assert current.standardized_anomaly is not None


def test_region_rollups_weight_by_valid_pixels_and_storage_round_trips(tmp_path):
    observations = [
        _observation(2025, "italy", 0.6, pixels=100),
        _observation(2025, "france", 0.3, pixels=300),
    ]
    rolled = add_region_rollups(observations)
    global_row = next(item for item in rolled if item.geography == "__global__")
    eu_row = next(item for item in rolled if item.geography == "__eu27__")
    assert global_row.value == 0.375
    assert eu_row.value == 0.375
    assert global_row.valid_pixel_count == 400

    store = LocalParquetStorage(tmp_path)
    assert store.write_land_surface(rolled) == 4
    restored = store.read_land_surface(metrics={"ndvi"})
    assert len(restored) == 4
    assert restored[-1].metric == "ndvi"


def test_burn_date_pixels_become_daily_hectares_and_region_totals():
    italy = burned_area_observations_from_values(
        [0, 32, 32, 33, -1],
        year=2025,
        pixel_area_hectares=25,
        geography="italy",
        country_iso3="ITA",
        total_pixel_count=5,
    )
    france = burned_area_observations_from_values(
        [32],
        year=2025,
        pixel_area_hectares=25,
        geography="france",
        country_iso3="FRA",
        total_pixel_count=1,
    )

    assert [(item.date.isoformat(), item.value) for item in italy] == [
        ("2025-02-01", 50),
        ("2025-02-02", 25),
    ]
    rolled = add_burned_area_region_rollups([*italy, *france])
    world = next(
        item for item in rolled
        if item.geography == "__global__" and item.date.isoformat() == "2025-02-01"
    )
    assert world.value == 75
