"""Export compact, browser-friendly MVP datasets from canonical Parquet files."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from climate_attention.config import load_country_config
from climate_attention.event_study import build_event_study_files
from climate_attention.geography import load_country_boundaries, load_region_boundaries
from climate_attention.source_coverage import is_known_outage
from climate_attention.storage import LocalParquetStorage
from climate_attention.supabase_sync import dotenv_value


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "data"
SUPABASE_CONFIG = ROOT / "frontend" / "src" / "supabase-config.json"
FRONTEND_ATTENTION_SOURCES = {"gdelt_ngrams"}
FRONTEND_TOPIC_IDS = {"climate_change", "electric_vehicles"}
FRONTEND_HAZARD_TYPES = {"wildfire", "flood"}


def clean(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def write_json(name: str, payload: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def export_supabase_config() -> None:
    url = dotenv_value("VITE_SUPABASE_URL", ROOT / ".env")
    public_key = dotenv_value("VITE_SUPABASE_PUBLISHABLE_KEY", ROOT / ".env")
    if not url or not public_key:
        raise ValueError("VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY are required")
    SUPABASE_CONFIG.write_text(
        json.dumps(
            {"enabled": True, "url": url, "publicKey": public_key},
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n",
        encoding="utf-8",
    )


def contiguous_date_ranges(values: list[str]) -> list[dict[str, Any]]:
    """Compress actual observed dates without implying coverage across gaps."""
    days = sorted({date.fromisoformat(value[:10]) for value in values if value})
    if not days:
        return []
    ranges: list[dict[str, Any]] = []
    range_start = days[0]
    previous = days[0]
    for day in days[1:]:
        if day != previous + timedelta(days=1):
            ranges.append(
                {
                    "start": range_start.isoformat(),
                    "end": previous.isoformat(),
                    "dayCount": (previous - range_start).days + 1,
                }
            )
            range_start = day
        previous = day
    ranges.append(
        {
            "start": range_start.isoformat(),
            "end": previous.isoformat(),
            "dayCount": (previous - range_start).days + 1,
        }
    )
    return ranges


def requested_date_ranges(source: str) -> list[dict[str, Any]]:
    """Merge every successful requested window for collection-window sources."""
    manifests = ROOT / "data/manifests"
    windows: list[tuple[date, date]] = []
    for path in sorted(manifests.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        requested = payload.get("requested_date_range")
        if payload.get("source") == source and requested and not payload.get("error"):
            windows.append(
                (date.fromisoformat(requested["start"]), date.fromisoformat(requested["end"]))
            )
    merged: list[tuple[date, date]] = []
    for start, end in sorted(windows):
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return [
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "dayCount": (end - start).days + 1,
        }
        for start, end in merged
    ]


def export_events() -> list[dict[str, Any]]:
    source = ROOT / "data/events/source=gdacs/events.parquet"
    rows = pq.read_table(source).to_pylist()
    country_config = load_country_config(ROOT / "config/countries.world.yaml")
    country_labels = {country.id: country.label for country in country_config.countries}
    boundary_index = load_country_boundaries(
        ROOT / "data/reference/ne_50m_admin_0_countries.geojson",
        country_config.countries,
    )
    region_index = load_region_boundaries(
        ROOT / "data/reference/ne_10m_admin_1_states_provinces.geojson.gz"
    )
    features: list[dict[str, Any]] = []
    for row in rows:
        if row["hazard_type"] not in FRONTEND_HAZARD_TYPES:
            continue
        try:
            geometry = json.loads(row["geometry_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if geometry.get("type") != "Point":
            continue
        coordinates = geometry.get("coordinates") or []
        map_country = (
            boundary_index.assign(float(coordinates[0]), float(coordinates[1]))
            if len(coordinates) >= 2
            else None
        )
        map_region = (
            region_index.assign(float(coordinates[0]), float(coordinates[1]))
            if len(coordinates) >= 2
            else None
        )
        if map_country and map_region and map_region.country_iso3 != map_country.iso3:
            map_region = None
        properties = {
            "id": row["record_id"],
            "sourceEventId": row["source_event_id"],
            "hazardType": row["hazard_type"],
            "name": row["name"],
            "startAt": clean(row["start_at"]),
            "endAt": clean(row["end_at"]),
            "geographyIds": row["geography_ids"] or [],
            "countryIso3s": row["country_iso3s"] or [],
            "mapCountryId": map_country.country_id if map_country else None,
            "mapCountryIso3": map_country.iso3 if map_country else None,
            "mapCountryLabel": country_labels.get(map_country.country_id) if map_country else None,
            "mapRegionLabel": map_region.label if map_region else None,
            "mapRegionType": map_region.region_type if map_region else None,
            "alertLevel": row["alert_level"],
            "alertScore": row["alert_score"],
            "severity": row["severity"],
            "severityUnit": row["severity_unit"],
            "sourceUrl": row["source_url"],
        }
        features.append(
            {"type": "Feature", "id": row["record_id"], "properties": properties, "geometry": geometry}
        )
    write_json("events.geojson", {"type": "FeatureCollection", "features": features})
    return features


def export_world_map() -> None:
    """Publish a same-origin basemap so event rendering never depends on tile hosts."""
    source = ROOT / "data/reference/ne_50m_admin_0_countries.geojson"
    collection = json.loads(source.read_text(encoding="utf-8"))
    features = []
    for feature in collection.get("features", []):
        properties = feature.get("properties") or {}
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": properties.get("NAME_EN") or properties.get("NAME"),
                    "iso3": properties.get("ISO_A3"),
                    "continent": properties.get("CONTINENT"),
                },
                "geometry": feature.get("geometry"),
            }
        )
    write_json("world.geojson", {"type": "FeatureCollection", "features": features})


def summarize_attention() -> dict[str, Any]:
    source = ROOT / "data/trends"
    source_counts: Counter[str] = Counter()
    source_dates: dict[str, list[str]] = defaultdict(list)
    source_geographies: dict[str, set[str]] = defaultdict(set)
    topic_counts: Counter[str] = Counter()
    dates: list[str] = []
    for path in sorted(source.rglob("*.parquet")):
        for row in pq.read_table(path).to_pylist():
            if row["source"] not in FRONTEND_ATTENTION_SOURCES:
                continue
            if row["topic_id"] not in FRONTEND_TOPIC_IDS:
                continue
            day = clean(row["date"])
            if is_known_outage(row["source"], day):
                continue
            source_counts[row["source"]] += 1
            source_dates[row["source"]].append(day)
            source_geographies[row["source"]].add(row["geography"])
            topic_counts[row["topic_id"]] += 1
            dates.append(day)
    summary = {
        "rowCount": sum(source_counts.values()),
        "dateMin": min(dates) if dates else None,
        "dateMax": max(dates) if dates else None,
        "sources": dict(source_counts),
        "bySource": {
            source_id: {
                "rowCount": row_count,
                "dateMin": min(source_dates[source_id]),
                "dateMax": max(source_dates[source_id]),
                "observedDayCount": len(set(source_dates[source_id])),
                "dateRanges": contiguous_date_ranges(source_dates[source_id]),
                "geographyCount": len(source_geographies[source_id]),
            }
            for source_id, row_count in source_counts.items()
        },
        "topics": dict(topic_counts),
    }
    return summary


def summarize_articles() -> dict[str, Any]:
    source = ROOT / "data/articles"
    count = 0
    dates: set[str] = set()
    geographies: set[str] = set()
    if source.exists():
        for path in sorted(source.rglob("*.parquet")):
            for row in pq.read_table(path).to_pylist():
                if row["topic_id"] not in FRONTEND_TOPIC_IDS:
                    continue
                count += 1
                dates.add(clean(row["date"]))
                geographies.add(row["geography"])
    return {
        "count": count,
        "dates": dates,
        "geographyCount": len(geographies),
    }


def export_satellite_observations(
    coverage_start: str | None, coverage_end: str | None
) -> dict[str, Any]:
    """Publish only compact MODIS zonal statistics inside the attention window."""
    storage = LocalParquetStorage(ROOT / "data")
    observations = storage.read_land_surface(
        source="nasa_modis",
        metrics={"ndvi", "evi", "burned_area"},
        start=date.fromisoformat(coverage_start) if coverage_start else None,
        end=date.fromisoformat(coverage_end) if coverage_end else None,
    )
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now().astimezone().isoformat(),
        "source": "NASA MODIS",
        "products": sorted({item.product for item in observations}),
        "observations": [
            {
                "date": item.date.isoformat(),
                "geography": item.geography,
                "countryIso3": item.country_iso3,
                "metric": item.metric,
                "value": item.value,
                "unit": item.unit,
                "periodDays": item.period_days,
                "validPixelCount": item.valid_pixel_count,
                "anomaly": item.anomaly,
                "standardizedAnomaly": item.standardized_anomaly,
                "baselineStartYear": item.baseline_start_year,
                "baselineEndYear": item.baseline_end_year,
                "landCoverMask": item.land_cover_mask,
            }
            for item in observations
        ],
    }
    write_json("satellite-observations.json", payload)
    observed_dates = sorted({item.date.isoformat() for item in observations})
    return {
        "observationCount": len(observations),
        "dateMin": min((item.date.isoformat() for item in observations), default=None),
        "dateMax": max((item.date.isoformat() for item in observations), default=None),
        "observedDateCount": len(observed_dates),
        "dateRanges": contiguous_date_ranges(observed_dates),
        "metrics": sorted({item.metric for item in observations}),
        "geographyCount": len({item.geography for item in observations}),
    }


def source_summaries(
    events: list[dict[str, Any]],
    attention_summary: dict[str, Any],
    satellite_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    event_starts = [feature["properties"]["startAt"] for feature in events]
    event_ends = [feature["properties"]["endAt"] for feature in events]
    event_countries = {
        country
        for feature in events
        for country in feature["properties"]["countryIso3s"]
    }
    gdacs_ranges = requested_date_ranges("gdacs") or contiguous_date_ranges(event_starts)
    summaries = [
        {
            "id": "gdacs",
            "name": "GDACS event catalogue",
            "provider": "Global Disaster Alert and Coordination System",
            "role": "Extreme-weather events",
            "dateMin": gdacs_ranges[0]["start"] if gdacs_ranges else None,
            "dateMax": gdacs_ranges[-1]["end"] if gdacs_ranges else None,
            "dateRanges": gdacs_ranges,
            "observedDayCount": sum(item["dayCount"] for item in gdacs_ranges),
            "coverageBasis": "requested collection window",
            "recordCount": len(events),
            "recordLabel": "events",
            "geographyCount": len(event_countries),
            "status": "explorer",
            "description": "Named floods and wildfires with alert level, severity and affected countries.",
            "sourceUrl": "https://www.gdacs.org/",
        }
    ]

    attention_metadata = {
        "gdelt_ngrams": {
            "name": "GDELT Web NGrams 3.0",
            "provider": "GDELT Project",
            "role": "Global topic attention",
            "status": "explorer",
            "description": "Distinct matched news URLs by UTC day, topic and publishing-outlet source country.",
            "sourceUrl": "https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/",
        },
    }
    for source_id, coverage in attention_summary["bySource"].items():
        metadata = attention_metadata.get(source_id)
        if not metadata:
            continue
        summaries.append(
            {
                "id": source_id,
                **metadata,
                "dateMin": coverage["dateMin"],
                "dateMax": coverage["dateMax"],
                "dateRanges": coverage["dateRanges"],
                "observedDayCount": coverage["observedDayCount"],
                "coverageBasis": "stored observation dates",
                "recordCount": coverage["rowCount"],
                "recordLabel": "daily topic-market rows",
                "geographyCount": coverage["geographyCount"],
            }
        )

    if satellite_summary and satellite_summary["observationCount"]:
        summaries.append({
            "id": "nasa_modis",
            "name": "MODIS land-surface aggregates",
            "provider": "NASA Land Processes DAAC",
            "role": "Vegetation and burned area",
            "dateMin": satellite_summary["dateMin"],
            "dateMax": satellite_summary["dateMax"],
            "dateRanges": satellite_summary["dateRanges"],
            "observedDayCount": satellite_summary["observedDateCount"],
            "coverageBasis": "stored composite or burn dates",
            "recordCount": satellite_summary["observationCount"],
            "recordLabel": "country-period observations",
            "geographyCount": satellite_summary["geographyCount"],
            "status": "explorer",
            "description": "Country aggregates from MODIS NDVI composites and MCD64 burned pixels; source rasters are not shipped to the browser.",
            "sourceUrl": "https://appeears.earthdatacloud.nasa.gov/",
        })

    return summaries


def main() -> None:
    export_supabase_config()
    export_world_map()
    events = export_events()
    event_study_2025 = build_event_study_files(
        data_dir=ROOT / "data",
        json_path=OUT / "event-study.json",
        study_year=2025,
    )
    event_study_2026 = build_event_study_files(
        data_dir=ROOT / "data",
        json_path=OUT / "event-study-2026.json",
        parquet_path=ROOT / "data" / "analysis" / "event_effects_2026.parquet",
        study_year=2026,
    )
    attention_summary = summarize_attention()
    article_summary = summarize_articles()
    satellite_summary = export_satellite_observations(
        attention_summary["dateMin"], attention_summary["dateMax"]
    )
    country_config = load_country_config(ROOT / "config/countries.world.yaml")
    geography_labels = {country.id: country.label for country in country_config.countries}
    data_sources = source_summaries(events, attention_summary, satellite_summary)
    hazard_counts = Counter(feature["properties"]["hazardType"] for feature in events)
    alert_counts = Counter(feature["properties"]["alertLevel"] for feature in events)
    write_json(
        "manifest.json",
        {
            "generatedAt": datetime.now().astimezone().isoformat(),
            "events": {"count": len(events), "hazards": dict(hazard_counts), "alerts": dict(alert_counts)},
            "attention": attention_summary,
            "satellite": satellite_summary,
            "articles": {"count": article_summary["count"]},
            "geographyLabels": geography_labels,
            "dataSources": data_sources,
            "analysisStatus": "2025_2026_event_studies_ready",
            "notes": [
                "Media geography is publishing-outlet country, not event location.",
                "The Analysis Lab uses GDACS Orange and Red events with complete daily attention windows.",
                "Coverage intervals use actual stored dates; gaps are never rendered as continuous coverage.",
                "GDELT's confirmed 14 June–1 July 2025 infrastructure outage is excluded as missing data.",
            ],
        },
    )
    print(
        f"Exported {len(events)} events and a manifest covering "
        f"{attention_summary['rowCount']} attention rows and "
        f"{article_summary['count']} articles and "
        f"{len(event_study_2025['events']) + len(event_study_2026['events'])} "
        f"major-event study candidates across 2025 and 2026 to {OUT}. "
        "Aggregate attention is served by Supabase; article rows remain an offline validation archive."
    )


if __name__ == "__main__":
    main()
