"""Reproducible multi-event attention study for the public research frontend."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq

from .source_coverage import is_known_outage, known_outages


STUDY_TOPICS = ("climate_change", "electric_vehicles")
STUDY_HAZARDS = {"wildfire", "flood"}
STUDY_ALERTS = {"Orange", "Red"}
ALL_ALERTS = {"Green", "Orange", "Red"}
STUDY_WINDOWS = (7, 14, 28)
STUDY_TIMINGS = ("onset", "persistence")
STUDY_SCOPES = ("affected", "other_eu27", "rest_world", "global")
EU27 = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czechrepublic",
    "denmark", "estonia", "finland", "france", "germany", "greece",
    "hungary", "ireland", "italy", "latvia", "lithuania", "luxembourg",
    "malta", "netherlands", "poland", "portugal", "romania", "slovakia",
    "slovenia", "spain", "sweden",
}


@dataclass(frozen=True)
class PeriodValue:
    pre_mean: float
    post_mean: float
    change: float
    percent_change: float | None


def _day(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


def _days(start: date, length: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(length)]


def _period_value(before: list[float], after: list[float]) -> PeriodValue:
    before_mean = sum(before) / len(before)
    after_mean = sum(after) / len(after)
    change = after_mean - before_mean
    return PeriodValue(
        pre_mean=before_mean,
        post_mean=after_mean,
        change=change,
        percent_change=(change / before_mean) * 100 if before_mean else None,
    )


def _study_events(
    rows: Iterable[dict[str, Any]], study_year: int, alerts: set[str]
) -> list[dict[str, Any]]:
    return sorted(
        (
            row
            for row in rows
            if row["hazard_type"] in STUDY_HAZARDS
            and row["alert_level"] in alerts
            and _day(row["start_at"]).year == study_year
        ),
        key=lambda row: (_day(row["start_at"]), row["record_id"]),
    )


def _overlaps(
    event: dict[str, Any], candidates: list[dict[str, Any]], window: int, timing: str
) -> bool:
    affected = set(event.get("geography_ids") or [])
    event_start = _day(event["start_at"])
    event_end = _day(event["end_at"])
    study_start = event_start - timedelta(days=window)
    study_end = (
        event_start + timedelta(days=window - 1)
        if timing == "onset"
        else event_end + timedelta(days=window)
    )
    for other in candidates:
        if other["record_id"] == event["record_id"]:
            continue
        if not affected.intersection(other.get("geography_ids") or []):
            continue
        if _day(other["start_at"]) <= study_end and _day(other["end_at"]) >= study_start:
            return True
    return False


def build_event_study(
    event_rows: Iterable[dict[str, Any]],
    attention_rows: Iterable[dict[str, Any]],
    *,
    study_year: int = 2025,
    alerts: set[str] | None = None,
    include_series: bool = True,
) -> dict[str, Any]:
    """Build event-level effects and onset series from complete topic-country days."""
    attention: dict[tuple[date, str, str], tuple[float, float]] = {}
    global_totals: dict[tuple[date, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    eu_totals: dict[tuple[date, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    geographies: set[str] = set()
    coverage_dates: set[date] = set()
    for row in attention_rows:
        day = _day(row["date"])
        topic = row["topic_id"]
        geography = row.get("geography")
        if (
            row.get("source") != "gdelt_ngrams"
            or is_known_outage("gdelt_ngrams", day)
            or topic not in STUDY_TOPICS
            or not geography
            or day.year != study_year
            or row.get("matched_count") is None
            or row.get("political_count") is None
        ):
            continue
        key = (day, topic, geography)
        value = (float(row["matched_count"]), float(row["political_count"]))
        if key in attention and attention[key] != value:
            raise ValueError(f"conflicting event-study observation: {key}")
        attention[key] = value
        totals = global_totals[(day, topic)]
        totals[0] += value[0]
        totals[1] += value[1]
        totals[2] += 1
        if geography in EU27:
            eu = eu_totals[(day, topic)]
            eu[0] += value[0]
            eu[1] += value[1]
            eu[2] += 1
        geographies.add(geography)
        coverage_dates.add(day)

    selected_alerts = set(alerts or STUDY_ALERTS)
    unsupported_alerts = selected_alerts - ALL_ALERTS
    if unsupported_alerts:
        raise ValueError("unsupported event-study alert(s): " + ", ".join(sorted(unsupported_alerts)))
    candidates = _study_events(event_rows, study_year, selected_alerts)
    effects: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []

    def sum_geographies(day: date, topic: str, selected: set[str]) -> tuple[float, float] | None:
        values = [attention.get((day, topic, geography)) for geography in selected]
        if not selected or any(value is None for value in values):
            return None
        complete = [value for value in values if value is not None]
        return sum(value[0] for value in complete), sum(value[1] for value in complete)

    def aggregate(
        day: date, topic: str, scope: str, affected: set[str]
    ) -> tuple[float, float] | None:
        totals = global_totals.get((day, topic))
        if totals is None or int(totals[2]) != len(geographies):
            return None
        affected_available = affected & geographies
        if scope == "global":
            return totals[0], totals[1]
        if scope == "affected":
            return sum_geographies(day, topic, affected_available)
        eu = eu_totals.get((day, topic), [0.0, 0.0, 0.0])
        affected_eu = sum_geographies(day, topic, affected_available & EU27) or (0.0, 0.0)
        if scope == "other_eu27":
            return eu[0] - affected_eu[0], eu[1] - affected_eu[1]
        if scope == "rest_world":
            affected_rest = sum_geographies(day, topic, affected_available - EU27) or (0.0, 0.0)
            return (
                totals[0] - eu[0] - affected_rest[0],
                totals[1] - eu[1] - affected_rest[1],
            )
        raise ValueError(f"unsupported event-study scope: {scope}")

    for event in candidates:
        event_start = _day(event["start_at"])
        event_end = _day(event["end_at"])
        affected = set(event.get("geography_ids") or [])
        for scope in STUDY_SCOPES:
            for topic in STUDY_TOPICS:
                if include_series:
                    for timing in STUDY_TIMINGS:
                        origin = event_start if timing == "onset" else event_end + timedelta(days=1)
                        points: list[list[float | int | None]] = []
                        for relative_day in range(-max(STUDY_WINDOWS), max(STUDY_WINDOWS) + 1):
                            value = aggregate(origin + timedelta(days=relative_day), topic, scope, affected)
                            points.append(
                                [relative_day, value[0], value[1]] if value is not None
                                else [relative_day, None, None]
                            )
                        series.append(
                            {
                                "eventId": event["record_id"],
                                "scope": scope,
                                "topicId": topic,
                                "timing": timing,
                                "points": points,
                            }
                        )

                for window in STUDY_WINDOWS:
                    before_dates = _days(event_start - timedelta(days=window), window)
                    for timing in STUDY_TIMINGS:
                        after_start = event_start if timing == "onset" else event_end + timedelta(days=1)
                        after_dates = _days(after_start, window)
                        before = [aggregate(day, topic, scope, affected) for day in before_dates]
                        after = [aggregate(day, topic, scope, affected) for day in after_dates]
                        complete = all(value is not None for value in before + after)
                        row: dict[str, Any] = {
                            "eventId": event["record_id"],
                            "hazardType": event["hazard_type"],
                            "alertLevel": event["alert_level"],
                            "startAt": event_start.isoformat(),
                            "endAt": event_end.isoformat(),
                            "geographyIds": sorted(affected),
                            "scope": scope,
                            "topicId": topic,
                            "windowDays": window,
                            "timing": timing,
                            "complete": complete,
                            "missingDays": sum(value is None for value in before + after),
                            "overlap": _overlaps(event, candidates, window, timing),
                            "matchedPreMean": None,
                            "matchedPostMean": None,
                            "matchedChange": None,
                            "matchedPercentChange": None,
                            "politicalPreMean": None,
                            "politicalPostMean": None,
                            "politicalChange": None,
                            "politicalPercentChange": None,
                            "politicalSharePre": None,
                            "politicalSharePost": None,
                            "politicalShareChange": None,
                        }
                        if complete:
                            before_values = [value for value in before if value is not None]
                            after_values = [value for value in after if value is not None]
                            matched = _period_value(
                                [value[0] for value in before_values],
                                [value[0] for value in after_values],
                            )
                            political = _period_value(
                                [value[1] for value in before_values],
                                [value[1] for value in after_values],
                            )
                            before_matched = sum(value[0] for value in before_values)
                            after_matched = sum(value[0] for value in after_values)
                            before_share = (
                                sum(value[1] for value in before_values) / before_matched * 100
                                if before_matched else None
                            )
                            after_share = (
                                sum(value[1] for value in after_values) / after_matched * 100
                                if after_matched else None
                            )
                            row.update(
                                {
                                    "matchedPreMean": matched.pre_mean,
                                    "matchedPostMean": matched.post_mean,
                                    "matchedChange": matched.change,
                                    "matchedPercentChange": matched.percent_change,
                                    "politicalPreMean": political.pre_mean,
                                    "politicalPostMean": political.post_mean,
                                    "politicalChange": political.change,
                                    "politicalPercentChange": political.percent_change,
                                    "politicalSharePre": before_share,
                                    "politicalSharePost": after_share,
                                    "politicalShareChange": (
                                        after_share - before_share
                                        if after_share is not None and before_share is not None
                                        else None
                                    ),
                                }
                            )
                        effects.append(row)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "studyYear": study_year,
        "coverage": {
            "start": min(coverage_dates).isoformat() if coverage_dates else None,
            "end": max(coverage_dates).isoformat() if coverage_dates else None,
            "observedDays": len(coverage_dates),
            "geographies": len(geographies),
            "excludedPeriods": [
                {
                    "start": outage.start.isoformat(),
                    "end": outage.end.isoformat(),
                    "label": outage.label,
                    "evidenceUrl": outage.evidence_url,
                }
                for outage in known_outages("gdelt_ngrams", year=study_year)
            ],
        },
        "topics": list(STUDY_TOPICS),
        "hazards": sorted(STUDY_HAZARDS),
        "alerts": sorted(selected_alerts),
        "windows": list(STUDY_WINDOWS),
        "timings": list(STUDY_TIMINGS),
        "scopes": list(STUDY_SCOPES),
        "events": [
            {
                "id": event["record_id"],
                "name": event["name"],
                "hazardType": event["hazard_type"],
                "alertLevel": event["alert_level"],
                "alertScore": event.get("alert_score"),
                "startAt": _day(event["start_at"]).isoformat(),
                "endAt": _day(event["end_at"]).isoformat(),
                "geographyIds": list(event.get("geography_ids") or []),
            }
            for event in candidates
        ],
        "effects": effects,
        "series": series,
        "method": {
            "cohort": "GDACS Orange and Red wildfire and flood events starting in the study year",
            "baseline": "Mean daily distinct matched URLs in the selected pre-event window",
            "onset": "Event start through the following N-1 days",
            "persistence": "N days beginning the day after the event ends",
            "politicalShare": "Political URLs divided by all matched topic URLs within each period",
            "overlap": "Another major event affects at least one same country during the analysis window",
        },
    }


def load_event_study_inputs(
    data_dir: Path, *, study_year: int | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    event_path = data_dir / "events" / "source=gdacs" / "events.parquet"
    if not event_path.exists():
        raise ValueError(f"missing GDACS event dataset: {event_path}")
    event_columns = [
        "record_id", "hazard_type", "name", "start_at", "end_at",
        "geography_ids", "alert_level", "alert_score",
    ]
    event_rows = pq.read_table(event_path, columns=event_columns).to_pylist()
    attention_rows: list[dict[str, Any]] = []
    trend_root = data_dir / "trends" / "source=gdelt_ngrams"
    attention_columns = [
        "date", "source", "topic_id", "geography", "matched_count",
        "political_count", "political_actor_count", "government_action_count",
        "party_politics_count", "official_source_count",
    ]
    for topic in STUDY_TOPICS:
        for path in sorted((trend_root / f"topic_id={topic}").rglob("daily.parquet")):
            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(columns=attention_columns, batch_size=16_384):
                rows = batch.to_pylist()
                if study_year is not None:
                    rows = [row for row in rows if _day(row["date"]).year == study_year]
                attention_rows.extend(rows)
    if not attention_rows:
        raise ValueError(f"missing GDELT NGrams attention data under {trend_root}")
    return event_rows, attention_rows


def write_event_study(
    payload: dict[str, Any], *, parquet_path: Path, json_path: Path
) -> tuple[Path, Path]:
    """Write a canonical flat effect table and compact browser payload."""
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(payload["effects"]), parquet_path, compression="zstd")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return parquet_path, json_path


def build_daily_event_activity(
    event_rows: Iterable[dict[str, Any]], *, study_year: int = 2025
) -> list[dict[str, Any]]:
    """Count event starts, active events and endings by affected country-day."""
    first_day = date(study_year, 1, 1)
    last_day = date(study_year, 12, 31)
    counters: dict[tuple[date, str, str, str], list[int]] = defaultdict(
        lambda: [0, 0, 0]
    )
    for event in event_rows:
        hazard = event.get("hazard_type")
        alert = event.get("alert_level")
        if hazard not in STUDY_HAZARDS or alert not in ALL_ALERTS:
            continue
        start = _day(event["start_at"])
        end = _day(event["end_at"])
        if end < first_day or start > last_day or end < start:
            continue
        affected = set(event.get("geography_ids") or [])
        locations = set(affected)
        locations.add("__global__")
        if affected & EU27:
            locations.add("__eu27__")
        active_start = max(start, first_day)
        active_end = min(end, last_day)
        active_days = _days(active_start, (active_end - active_start).days + 1)
        for geography in locations:
            if first_day <= start <= last_day:
                counters[(start, geography, hazard, alert)][0] += 1
            for day in active_days:
                counters[(day, geography, hazard, alert)][1] += 1
            if first_day <= end <= last_day:
                counters[(end, geography, hazard, alert)][2] += 1
    return [
        {
            "activityDate": day.isoformat(),
            "geography": geography,
            "hazardType": hazard,
            "alertLevel": alert,
            "eventsStarted": values[0],
            "eventsActive": values[1],
            "eventsEnded": values[2],
        }
        for (day, geography, hazard, alert), values in sorted(counters.items())
    ]


def build_daily_attention_regions(
    attention_rows: Iterable[dict[str, Any]], *, study_year: int = 2025
) -> list[dict[str, Any]]:
    """Aggregate the existing country panel into global and EU27 daily rows."""
    totals: dict[tuple[date, str, str], dict[str, float]] = defaultdict(
        lambda: {
            "matchedCount": 0.0,
            "politicalCount": 0.0,
            "politicalActorCount": 0.0,
            "governmentActionCount": 0.0,
            "partyPoliticsCount": 0.0,
            "officialSourceCount": 0.0,
        }
    )
    component_fields = {
        "politicalActorCount": "political_actor_count",
        "governmentActionCount": "government_action_count",
        "partyPoliticsCount": "party_politics_count",
        "officialSourceCount": "official_source_count",
    }
    for row in attention_rows:
        day = _day(row["date"])
        topic = row.get("topic_id")
        geography = row.get("geography")
        if (
            row.get("source") != "gdelt_ngrams"
            or is_known_outage("gdelt_ngrams", day)
            or topic not in STUDY_TOPICS
            or not geography
            or day.year != study_year
            or row.get("matched_count") is None
            or row.get("political_count") is None
        ):
            continue
        regions = ["global"] + (["eu27"] if geography in EU27 else [])
        for region in regions:
            values = totals[(day, region, topic)]
            values["matchedCount"] += float(row["matched_count"])
            values["politicalCount"] += float(row["political_count"])
            for output_field, input_field in component_fields.items():
                values[output_field] += float(row.get(input_field) or 0)
    return [
        {
            "observationDate": day.isoformat(),
            "regionId": region,
            "topicId": topic,
            **values,
            "politicalShare": (
                values["politicalCount"] / values["matchedCount"] * 100
                if values["matchedCount"] else None
            ),
        }
        for (day, region, topic), values in sorted(totals.items())
    ]


def build_analysis_warehouse(
    *, data_dir: Path, study_year: int = 2025
) -> dict[str, Any]:
    """Build all-alert effect and daily activity tables for Supabase serving."""
    events, attention = load_event_study_inputs(data_dir, study_year=study_year)
    study = build_event_study(
        events,
        attention,
        study_year=study_year,
        alerts=ALL_ALERTS,
        include_series=False,
    )
    activity = build_daily_event_activity(events, study_year=study_year)
    regions = build_daily_attention_regions(attention, study_year=study_year)
    output = data_dir / "analysis"
    output.mkdir(parents=True, exist_ok=True)
    effect_path = output / "event_effects_all.parquet"
    activity_path = output / "daily_event_activity.parquet"
    region_path = output / "daily_attention_regions.parquet"
    pq.write_table(pa.Table.from_pylist(study["effects"]), effect_path, compression="zstd")
    pq.write_table(pa.Table.from_pylist(activity), activity_path, compression="zstd")
    pq.write_table(pa.Table.from_pylist(regions), region_path, compression="zstd")
    return {
        "events": len(study["events"]),
        "effects": len(study["effects"]),
        "activityRows": len(activity),
        "regionRows": len(regions),
        "effectPath": effect_path,
        "activityPath": activity_path,
        "regionPath": region_path,
    }


def build_event_study_files(
    *,
    data_dir: Path,
    json_path: Path,
    study_year: int = 2025,
    parquet_path: Path | None = None,
) -> dict[str, Any]:
    events, attention = load_event_study_inputs(data_dir, study_year=study_year)
    payload = build_event_study(events, attention, study_year=study_year)
    write_event_study(
        payload,
        parquet_path=parquet_path or data_dir / "analysis" / "event_effects.parquet",
        json_path=json_path,
    )
    return payload
