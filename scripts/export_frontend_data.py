"""Export compact, browser-friendly MVP datasets from canonical Parquet files."""

from __future__ import annotations

import json
from collections import Counter
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
    topic_counts: Counter[str] = Counter()
    dates: list[str] = []
    for path in sorted(source.rglob("*.parquet")):
        for row in pq.read_table(path).to_pylist():
            day = clean(row["date"])
            source_counts[row["source"]] += 1
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


def main() -> None:
    export_world_map()
    events = export_events()
    attention, attention_summary = export_attention()
    articles = export_articles()
    hazard_counts = Counter(feature["properties"]["hazardType"] for feature in events)
    alert_counts = Counter(feature["properties"]["alertLevel"] for feature in events)
    write_json(
        "manifest.json",
        {
            "generatedAt": datetime.now().astimezone().isoformat(),
            "events": {"count": len(events), "hazards": dict(hazard_counts), "alerts": dict(alert_counts)},
            "attention": attention_summary,
            "articles": {"count": len(articles)},
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
