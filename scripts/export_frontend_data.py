"""Export compact, browser-friendly MVP datasets from canonical Parquet files."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from climate_attention.config import load_country_config
from climate_attention.geography import load_country_boundaries


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "data"
FRONTEND_ATTENTION_SOURCES = {"gdelt_ngrams"}
FRONTEND_TOPIC_IDS = {"climate_change", "electric_vehicles"}


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


def latest_requested_range(source: str) -> dict[str, Any] | None:
    """Return the latest successful requested window for collection-window sources."""
    manifests = ROOT / "data/manifests"
    for path in sorted(manifests.glob("*.json"), reverse=True):
        payload = json.loads(path.read_text(encoding="utf-8"))
        requested = payload.get("requested_date_range")
        if payload.get("source") == source and requested and not payload.get("error"):
            start = requested["start"]
            end = requested["end"]
            return {
                "start": start,
                "end": end,
                "dayCount": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1,
            }
    return None


def export_events() -> list[dict[str, Any]]:
    source = ROOT / "data/events/source=gdacs/events.parquet"
    rows = pq.read_table(source).to_pylist()
    country_config = load_country_config(ROOT / "config/countries.world.yaml")
    country_labels = {country.id: country.label for country in country_config.countries}
    boundary_index = load_country_boundaries(
        ROOT / "data/reference/ne_50m_admin_0_countries.geojson",
        country_config.countries,
    )
    features: list[dict[str, Any]] = []
    for row in rows:
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


def export_attention() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = ROOT / "data/trends"
    output: list[dict[str, Any]] = []
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
            source_counts[row["source"]] += 1
            source_dates[row["source"]].append(day)
            source_geographies[row["source"]].add(row["geography"])
            topic_counts[row["topic_id"]] += 1
            dates.append(day)
            output.append(
                {
                    "date": day,
                    "source": row["source"],
                    "topicId": row["topic_id"],
                    "geography": row["geography"],
                    "matchedCount": row.get("matched_count"),
                    "attentionShare": row.get("country_attention_share", row.get("attention_share")),
                    "attentionIndex": row.get("attention_index"),
                    "politicalCount": row.get("political_count"),
                    "politicalActorCount": row.get("political_actor_count"),
                    "governmentActionCount": row.get("government_action_count"),
                    "partyPoliticsCount": row.get("party_politics_count"),
                    "officialSourceCount": row.get("official_source_count"),
                }
            )
    write_json("attention.json", output)
    summary = {
        "rowCount": len(output),
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
    return output, summary


def export_articles() -> list[dict[str, Any]]:
    source = ROOT / "data/articles"
    output: list[dict[str, Any]] = []
    if source.exists():
        for path in sorted(source.rglob("*.parquet")):
            for row in pq.read_table(path).to_pylist():
                if row["topic_id"] not in FRONTEND_TOPIC_IDS:
                    continue
                output.append(
                    {
                        "id": row["record_id"],
                        "date": clean(row["date"]),
                        "topicId": row["topic_id"],
                        "geography": row["geography"],
                        "url": row["url"],
                        "domain": row["domain"],
                        "publishedAt": clean(row["published_at"]),
                        "outletName": row["outlet_name"],
                        "title": row["title"],
                        "language": row["language"],
                        "politicalActor": row["political_actor"],
                        "governmentAction": row["government_action"],
                        "partyPolitics": row["party_politics"],
                        "officialSource": row["official_source"],
                    }
                )
    write_json("articles.json", output)
    return output


def source_summaries(
    events: list[dict[str, Any]],
    attention_summary: dict[str, Any],
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    event_starts = [feature["properties"]["startAt"] for feature in events]
    event_ends = [feature["properties"]["endAt"] for feature in events]
    event_countries = {
        country
        for feature in events
        for country in feature["properties"]["countryIso3s"]
    }
    gdacs_requested = latest_requested_range("gdacs")
    gdacs_ranges = [gdacs_requested] if gdacs_requested else contiguous_date_ranges(event_starts)
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
            "description": "Named floods, wildfires and tropical cyclones with alert level, severity and affected countries.",
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

    article_dates = [article["date"] for article in articles]
    article_ranges = contiguous_date_ranges(article_dates)
    summaries.append(
        {
            "id": "gdelt_articles",
            "name": "GDELT Web NGrams article evidence",
            "provider": "GDELT Project",
            "role": "Article-level evidence",
            "dateMin": min(article_dates) if article_dates else None,
            "dateMax": max(article_dates) if article_dates else None,
            "dateRanges": article_ranges,
            "observedDayCount": len(set(article_dates)),
            "coverageBasis": "stored publication dates",
            "recordCount": len(articles),
            "recordLabel": "articles",
            "geographyCount": len({article["geography"] for article in articles}),
            "status": "explorer",
            "description": "Candidate article links and political-framing signals; articles are not yet linked to individual events.",
            "sourceUrl": "https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/",
        }
    )
    return summaries


def main() -> None:
    export_world_map()
    events = export_events()
    attention, attention_summary = export_attention()
    articles = export_articles()
    country_config = load_country_config(ROOT / "config/countries.world.yaml")
    geography_labels = {country.id: country.label for country in country_config.countries}
    data_sources = source_summaries(events, attention_summary, articles)
    hazard_counts = Counter(feature["properties"]["hazardType"] for feature in events)
    alert_counts = Counter(feature["properties"]["alertLevel"] for feature in events)
    write_json(
        "manifest.json",
        {
            "generatedAt": datetime.now().astimezone().isoformat(),
            "events": {"count": len(events), "hazards": dict(hazard_counts), "alerts": dict(alert_counts)},
            "attention": attention_summary,
            "articles": {"count": len(articles)},
            "geographyLabels": geography_labels,
            "dataSources": data_sources,
            "analysisStatus": "continuous_event windows_pending",
            "notes": [
                "Article geography is publishing-outlet country, not event location.",
                "Stored articles are not yet linked to individual GDACS events.",
                "Event effects require continuous daily attention coverage around each event.",
                "Coverage intervals use actual stored dates; gaps are never rendered as continuous coverage.",
            ],
        },
    )
    print(f"Exported {len(events)} events, {len(attention)} attention rows, and {len(articles)} articles to {OUT}")


if __name__ == "__main__":
    main()
