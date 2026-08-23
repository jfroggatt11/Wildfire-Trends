"""Reproducible multi-event attention study for the public research frontend."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq


STUDY_TOPICS = ("climate_change", "electric_vehicles")
STUDY_HAZARDS = {"wildfire", "flood"}
STUDY_ALERTS = {"Orange", "Red"}
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


def _study_events(rows: Iterable[dict[str, Any]], study_year: int) -> list[dict[str, Any]]:
    return sorted(
        (
            row
            for row in rows
            if row["hazard_type"] in STUDY_HAZARDS
            and row["alert_level"] in STUDY_ALERTS
            and _day(row["start_at"]).year == study_year
        ),
        key=lambda row: (_day(row["start_at"]), row["record_id"]),
    )


def _scope_geographies(
    scope: str, affected: set[str], available: set[str]
) -> list[str]:
    if scope == "affected":
        selected = affected
    elif scope == "other_eu27":
        selected = EU27 - affected
    elif scope == "rest_world":
        selected = available - EU27 - affected
    elif scope == "global":
        selected = available
    else:
        raise ValueError(f"unsupported event-study scope: {scope}")
    return sorted(selected & available)


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
) -> dict[str, Any]:
    """Build event-level effects and onset series from complete topic-country days."""
    attention: dict[tuple[date, str, str], tuple[float, float]] = {}
    geographies: set[str] = set()
    coverage_dates: set[date] = set()
    for row in attention_rows:
        day = _day(row["date"])
        topic = row["topic_id"]
        geography = row.get("geography")
        if (
            row.get("source") != "gdelt_ngrams"
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
        geographies.add(geography)
        coverage_dates.add(day)

    candidates = _study_events(event_rows, study_year)
    effects: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []

    def aggregate(day: date, topic: str, selected: list[str]) -> tuple[float, float] | None:
        values = [attention.get((day, topic, geography)) for geography in selected]
        if not selected or any(value is None for value in values):
            return None
        complete = [value for value in values if value is not None]
        return sum(value[0] for value in complete), sum(value[1] for value in complete)

    for event in candidates:
        event_start = _day(event["start_at"])
        event_end = _day(event["end_at"])
        affected = set(event.get("geography_ids") or [])
        for scope in STUDY_SCOPES:
            selected = _scope_geographies(scope, affected, geographies)
            for topic in STUDY_TOPICS:
                for timing in STUDY_TIMINGS:
                    origin = event_start if timing == "onset" else event_end + timedelta(days=1)
                    points: list[list[float | int | None]] = []
                    for relative_day in range(-max(STUDY_WINDOWS), max(STUDY_WINDOWS) + 1):
                        value = aggregate(origin + timedelta(days=relative_day), topic, selected)
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
                        before = [aggregate(day, topic, selected) for day in before_dates]
                        after = [aggregate(day, topic, selected) for day in after_dates]
                        complete = all(value is not None for value in before + after)
                        row: dict[str, Any] = {
                            "eventId": event["record_id"],
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
        },
        "topics": list(STUDY_TOPICS),
        "hazards": sorted(STUDY_HAZARDS),
        "alerts": sorted(STUDY_ALERTS),
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


def load_event_study_inputs(data_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    event_path = data_dir / "events" / "source=gdacs" / "events.parquet"
    if not event_path.exists():
        raise ValueError(f"missing GDACS event dataset: {event_path}")
    event_rows = pq.read_table(event_path).to_pylist()
    attention_rows: list[dict[str, Any]] = []
    trend_root = data_dir / "trends" / "source=gdelt_ngrams"
    for topic in STUDY_TOPICS:
        for path in sorted((trend_root / f"topic_id={topic}").rglob("daily.parquet")):
            attention_rows.extend(pq.read_table(path).to_pylist())
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


def build_event_study_files(
    *, data_dir: Path, json_path: Path, study_year: int = 2025
) -> dict[str, Any]:
    events, attention = load_event_study_inputs(data_dir)
    payload = build_event_study(events, attention, study_year=study_year)
    write_event_study(
        payload,
        parquet_path=data_dir / "analysis" / "event_effects.parquet",
        json_path=json_path,
    )
    return payload
