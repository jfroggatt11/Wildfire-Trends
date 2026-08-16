"""Export compact, browser-friendly MVP datasets from canonical Parquet files."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "data"


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


def export_events() -> list[dict[str, Any]]:
    source = ROOT / "data/events/source=gdacs/events.parquet"
    rows = pq.read_table(source).to_pylist()
    features: list[dict[str, Any]] = []
    for row in rows:
        try:
            geometry = json.loads(row["geometry_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if geometry.get("type") != "Point":
            continue
        properties = {
            "id": row["record_id"],
            "sourceEventId": row["source_event_id"],
            "hazardType": row["hazard_type"],
            "name": row["name"],
            "startAt": clean(row["start_at"]),
            "endAt": clean(row["end_at"]),
            "geographyIds": row["geography_ids"] or [],
            "countryIso3s": row["country_iso3s"] or [],
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
                        "description": row["description"],
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
    summaries = [
        {
            "id": "gdacs",
            "name": "GDACS event catalogue",
            "provider": "Global Disaster Alert and Coordination System",
            "role": "Extreme-weather events",
            "dateMin": min(event_starts) if event_starts else None,
            "dateMax": max(event_ends) if event_ends else None,
            "recordCount": len(events),
            "recordLabel": "events",
            "geographyCount": len(event_countries),
            "status": "explorer",
            "description": "Named floods, wildfires and tropical cyclones with alert level, severity and affected countries.",
            "sourceUrl": "https://www.gdacs.org/",
        }
    ]

    firms_path = ROOT / "data/hazards/source=firms/hazard_type=wildfire/daily.parquet"
    if firms_path.exists():
        firms_rows = pq.read_table(firms_path, columns=["date", "geography"]).to_pylist()
        firms_dates = [clean(row["date"]) for row in firms_rows]
        summaries.append(
            {
                "id": "firms",
                "name": "NASA FIRMS wildfire detections",
                "provider": "NASA Fire Information for Resource Management System",
                "role": "Physical wildfire intensity",
                "dateMin": min(firms_dates) if firms_dates else None,
                "dateMax": max(firms_dates) if firms_dates else None,
                "recordCount": len(firms_rows),
                "recordLabel": "country-days",
                "geographyCount": len({row["geography"] for row in firms_rows}),
                "status": "supporting",
                "description": "Daily country-level satellite fire detections retained as an independent physical severity layer.",
                "sourceUrl": "https://firms.modaps.eosdis.nasa.gov/",
            }
        )

    attention_metadata = {
        "gdelt_ngrams": {
            "name": "GDELT Web NGrams 3.0",
            "provider": "GDELT Project",
            "role": "Global topic attention",
            "status": "explorer",
            "description": "Distinct matched news URLs by UTC day, topic and publishing-outlet source country.",
            "sourceUrl": "https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/",
        },
        "gdelt": {
            "name": "GDELT DOC 2.0 topic timelines",
            "provider": "GDELT Project",
            "role": "API comparison series",
            "status": "validation",
            "description": "Short-run topic attention series retained for source comparison and validation.",
            "sourceUrl": "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
        },
        "google_trends_unofficial": {
            "name": "Google Trends comparison series",
            "provider": "Unofficial Google Trends connector",
            "role": "Search-interest validation",
            "status": "validation",
            "description": "Unofficial search-interest observations used only as a comparison source, not a canonical media measure.",
            "sourceUrl": "https://trends.google.com/trends/",
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
                "recordCount": coverage["rowCount"],
                "recordLabel": "daily topic-market rows",
                "geographyCount": coverage["geographyCount"],
            }
        )

    article_dates = [article["date"] for article in articles]
    summaries.append(
        {
            "id": "gdelt_articles",
            "name": "GDELT DOC 2.0 article sample",
            "provider": "GDELT Project",
            "role": "Article-level evidence",
            "dateMin": min(article_dates) if article_dates else None,
            "dateMax": max(article_dates) if article_dates else None,
            "recordCount": len(articles),
            "recordLabel": "articles",
            "geographyCount": len({article["geography"] for article in articles}),
            "status": "explorer",
            "description": "Candidate article links and political-framing signals; articles are not yet linked to individual events.",
            "sourceUrl": "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
        }
    )
    return summaries


def main() -> None:
    export_world_map()
    events = export_events()
    attention, attention_summary = export_attention()
    articles = export_articles()
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
            "dataSources": data_sources,
            "analysisStatus": "continuous_event windows_pending",
            "notes": [
                "Article geography is publishing-outlet country, not event location.",
                "Stored articles are not yet linked to individual GDACS events.",
                "Event effects require continuous daily attention coverage around each event.",
            ],
        },
    )
    print(f"Exported {len(events)} events, {len(attention)} attention rows, and {len(articles)} articles to {OUT}")


if __name__ == "__main__":
    main()
