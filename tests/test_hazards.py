from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from climate_attention.cli import main
from climate_attention.config import Country
from climate_attention.geography import load_country_boundaries
from climate_attention.models import DailyHazard, HazardEvent
from climate_attention.sources.firms import FIRMSProvider, firms_map_key, plan_firms_windows
from climate_attention.sources.base import ProviderError
from climate_attention.sources.gdacs import GDACSProvider
from climate_attention.storage import LocalParquetStorage


def _countries():
    return [
        Country(id="italy", label="Italy", iso3="ITA"),
        Country(id="france", label="France", iso3="FRA"),
    ]


def _boundaries(tmp_path):
    path = tmp_path / "countries.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"ISO_A3": "ITA"},
                        "bbox": [10, 40, 15, 45],
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[10, 40], [15, 40], [15, 45], [10, 45], [10, 40]]
                            ],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"ISO_A3": "FRA"},
                        "bbox": [0, 40, 5, 45],
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[0, 40], [5, 40], [5, 45], [0, 45], [0, 40]]
                            ],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return load_country_boundaries(path, _countries())


def test_country_boundary_index_and_firms_window_plan(tmp_path):
    index = _boundaries(tmp_path)
    assert index.assign(12, 42).country_id == "italy"
    assert index.assign(2, 42).country_id == "france"
    assert index.assign(-20, 0) is None
    windows = plan_firms_windows(date(2025, 1, 1), date(2025, 1, 12))
    assert [(item.start.day, item.end.day) for item in windows] == [
        (1, 5),
        (6, 10),
        (11, 12),
    ]


def test_firms_map_key_loads_dotenv_and_environment_takes_precedence(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "# local secret\nFIRMS_MAP_KEY='dotenv-key'\n", encoding="utf-8"
    )
    assert firms_map_key() == "dotenv-key"
    monkeypatch.setenv("FIRMS_MAP_KEY", "shell-key")
    assert firms_map_key() == "shell-key"


def test_firms_filters_and_builds_complete_country_day_rows(tmp_path):
    csv_text = "\n".join(
        [
            "latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp,type",
            "42,12,2025-01-01,1200,N,VIIRS,n,10.5,0",
            "42,12,2025-01-01,1210,N,VIIRS,h,5.5,0",
            "42,12,2025-01-01,1220,N,VIIRS,l,99,0",
            "42,12,2025-01-01,1230,N,VIIRS,h,99,2",
            "0,-20,2025-01-02,1200,N,VIIRS,h,20,0",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/world/2/2025-01-01" in str(request.url)
        assert "secret" in str(request.url)
        return httpx.Response(200, text=csv_text)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FIRMSProvider(
        map_key="secret",
        source="VIIRS_SNPP_SP",
        boundary_index=_boundaries(tmp_path),
        countries=_countries(),
        cache_dir=tmp_path / "cache",
        client=client,
        request_interval_seconds=0,
        sleep=lambda _: None,
    )
    rows, requests, totals = provider.collect(date(2025, 1, 1), date(2025, 1, 2))
    by_key = {(item.date, item.geography): item for item in rows}
    italy = by_key[(date(2025, 1, 1), "italy")]
    assert len(rows) == 4
    assert italy.observation_count == 2
    assert italy.total_intensity == 16
    assert italy.mean_intensity == 8
    assert italy.max_intensity == 10.5
    assert italy.high_confidence_count == 1
    assert by_key[(date(2025, 1, 2), "france")].observation_count == 0
    assert totals == {
        "rows_received": 5,
        "rows_retained": 2,
        "rows_unassigned": 1,
        "rows_low_confidence": 1,
        "rows_non_vegetation": 1,
    }
    assert requests[0]["cached"] is False
    assert "secret" not in json.dumps(requests)

    def no_network(_: httpx.Request) -> httpx.Response:
        raise AssertionError("valid FIRMS cache should prevent another HTTP request")

    cached_provider = FIRMSProvider(
        map_key="different-secret",
        source="VIIRS_SNPP_SP",
        boundary_index=_boundaries(tmp_path),
        countries=_countries(),
        cache_dir=tmp_path / "cache",
        client=httpx.Client(transport=httpx.MockTransport(no_network)),
        request_interval_seconds=0,
    )
    _, cached_requests, _ = cached_provider.collect(
        date(2025, 1, 1), date(2025, 1, 2)
    )
    assert cached_requests[0]["cached"] is True


def test_firms_failure_does_not_expose_map_key(tmp_path):
    secret = "private-map-key"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="provider failure")

    provider = FIRMSProvider(
        map_key=secret,
        source="VIIRS_SNPP_SP",
        boundary_index=_boundaries(tmp_path),
        countries=_countries(),
        cache_dir=tmp_path / "cache",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
        sleep=lambda _: None,
    )
    with pytest.raises(ProviderError) as caught:
        provider.collect(date(2025, 1, 1), date(2025, 1, 1))
    assert secret not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)


def _gdacs_feature(event_id: int, event_type: str, iso3: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [12.0, 42.0]},
        "properties": {
            "eventtype": event_type,
            "eventid": event_id,
            "episodeid": 1,
            "name": f"Event {event_id}",
            "alertlevel": "Orange",
            "alertscore": 1.2,
            "fromdate": "2025-01-02T01:00:00",
            "todate": "2025-01-04T01:00:00",
            "datemodified": "2025-01-05T12:00:00",
            "iso3": iso3,
            "affectedcountries": [{"iso3": iso3}],
            "severitydata": {
                "severity": 9.5,
                "severityunit": "km2",
                "severitytext": "Magnitude 9.5 km2",
            },
            "url": {"report": f"https://example.test/{event_id}"},
            "source": "test",
        },
    }


def test_gdacs_paginates_and_maps_affected_countries(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page = int(request.url.params["pageNumber"])
        features = (
            [_gdacs_feature(1, "WF", "ITA"), _gdacs_feature(2, "FL", "FRA")]
            if page == 1
            else [_gdacs_feature(3, "TC", "XXX")]
        )
        return httpx.Response(
            200, json={"type": "FeatureCollection", "features": features}
        )

    provider = GDACSProvider(
        countries=_countries(),
        cache_dir=tmp_path / "gdacs",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        page_size=2,
        request_interval_seconds=0,
        sleep=lambda _: None,
    )
    events, requests = provider.collect(date(2025, 1, 1), date(2025, 1, 31))
    assert len(calls) == 2
    assert len(requests) == 2
    by_id = {item.source_event_id: item for item in events}
    assert {item.hazard_type for item in events} == {
        "wildfire",
        "flood",
        "tropical_cyclone",
    }
    assert by_id["WF:1"].geography_ids == ["italy"]
    assert by_id["FL:2"].geography_ids == ["france"]
    assert by_id["TC:3"].geography_ids == []
    assert by_id["TC:3"].metadata["unmatched_country_iso3s"] == ["XXX"]
    assert by_id["WF:1"].start_at.tzinfo == timezone.utc


def test_hazard_and_event_storage_round_trip(tmp_path):
    storage = LocalParquetStorage(tmp_path / "data")
    hazard = DailyHazard(
        record_id="firms:one",
        date=date(2025, 1, 1),
        source="firms",
        hazard_type="wildfire",
        geography="italy",
        country_iso3="ITA",
        observation_count=3,
        total_intensity=15,
        mean_intensity=5,
        max_intensity=7,
        high_confidence_count=1,
        request_complete=True,
        boundary_supported=True,
        collected_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        metadata={"unit": "MW"},
    )
    event = HazardEvent(
        record_id="gdacs:WF:1",
        source="gdacs",
        source_event_id="WF:1",
        hazard_type="wildfire",
        name="Test fire",
        start_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        geography_ids=["italy"],
        country_iso3s=["ITA"],
        geometry={"type": "Point", "coordinates": [12, 42]},
        metadata={"episode_id": 1},
    )
    assert storage.write_hazards([hazard]) == 1
    assert storage.write_hazards([hazard]) == 0
    assert storage.read_hazards() == [hazard]
    assert storage.write_events([event]) == 1
    assert storage.write_events([event]) == 0
    assert storage.read_events() == [event]


def test_event_collection_plan_commands_need_no_credentials(tmp_path, capsys):
    countries = tmp_path / "countries.yaml"
    countries.write_text("countries:\n  italy:\n    label: Italy\n    iso3: ITA\n")
    common = [
        "--countries-config",
        str(countries),
        "--start",
        "2025-01-01",
        "--end",
        "2025-01-06",
        "--plan-only",
        "--data-dir",
        str(tmp_path / "data"),
    ]
    assert main(["collect-firms", *common]) == 0
    assert "2 non-overlapping request(s)" in capsys.readouterr().out
    assert main(["collect-gdacs", *common]) == 0
    assert "wildfire, flood, and tropical-cyclone" in capsys.readouterr().out
