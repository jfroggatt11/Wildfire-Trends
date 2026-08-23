"""Bulk-load canonical daily attention counts into Supabase Postgres."""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


MVP_TOPICS = {"climate_change", "electric_vehicles"}
ATTENTION_COLUMNS = (
    "record_id",
    "observation_date",
    "source",
    "topic_id",
    "query_id",
    "geography",
    "language",
    "matched_count",
    "country_attention_share",
    "attention_index",
    "political_count",
    "political_actor_count",
    "government_action_count",
    "party_politics_count",
    "official_source_count",
    "collected_at",
)
ATTENTION_SYNC_BATCH_SIZE = 50_000
ANALYSIS_SYNC_BATCH_SIZE = 50_000

EVENT_EFFECT_COLUMNS = (
    "event_id", "hazard_type", "alert_level", "start_at", "end_at",
    "geography_ids", "scope", "topic_id", "window_days", "timing", "complete",
    "missing_days", "overlap", "matched_pre_mean", "matched_post_mean",
    "matched_change", "matched_percent_change", "political_pre_mean",
    "political_post_mean", "political_change", "political_percent_change",
    "political_share_pre", "political_share_post", "political_share_change",
)
EVENT_ACTIVITY_COLUMNS = (
    "activity_date", "geography", "hazard_type", "alert_level", "events_started",
    "events_active", "events_ended",
)
REGION_ATTENTION_COLUMNS = (
    "observation_date", "region_id", "topic_id", "matched_count",
    "political_count", "political_actor_count", "government_action_count",
    "party_politics_count", "official_source_count", "political_share",
)


def dotenv_value(name: str, path: Path = Path(".env")) -> str | None:
    """Read one dotenv value without mutating the process environment."""
    environment = os.environ.get(name)
    if environment:
        return environment.strip()
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("'\"") or None
    return None


def attention_files(data_dir: Path, topics: set[str]) -> list[Path]:
    root = data_dir / "trends" / "source=gdelt_ngrams"
    return sorted(
        path
        for topic in sorted(topics)
        for path in (root / f"topic_id={topic}").rglob("daily.parquet")
    )


def attention_rows(
    path: Path, *, start: date | None = None, end: date | None = None
) -> Iterable[dict[str, Any]]:
    for row in pq.ParquetFile(path).read().to_pylist():
        day = row["date"]
        if (start is not None and day < start) or (end is not None and day > end):
            continue
        yield {
            "record_id": row["record_id"],
            "observation_date": day,
            "source": row["source"],
            "topic_id": row["topic_id"],
            "query_id": row["query_id"],
            "geography": row["geography"],
            "language": row["language"],
            "matched_count": row["matched_count"],
            "country_attention_share": row["country_attention_share"],
            "attention_index": row["attention_index"],
            "political_count": row["political_count"],
            "political_actor_count": row["political_actor_count"],
            "government_action_count": row["government_action_count"],
            "party_politics_count": row["party_politics_count"],
            "official_source_count": row["official_source_count"],
            "collected_at": row["collected_at"],
        }


def sync_daily_attention(
    *,
    database_url: str,
    data_dir: Path,
    migration_path: Path,
    topics: set[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    apply_migration: bool = False,
) -> tuple[int, int]:
    """Idempotently upsert selected daily trend partitions via COPY."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Supabase sync requires: python -m pip install -e '.[supabase]'"
        ) from exc

    selected_topics = set(topics or MVP_TOPICS)
    unsupported = selected_topics - MVP_TOPICS
    if unsupported:
        raise ValueError("unsupported Supabase topic(s): " + ", ".join(sorted(unsupported)))
    files = attention_files(data_dir, selected_topics)
    if not files:
        raise ValueError(f"no daily trend Parquet files found under {data_dir}")

    column_sql = ", ".join(ATTENTION_COLUMNS)
    update_sql = ", ".join(
        f"{column} = excluded.{column}"
        for column in ATTENTION_COLUMNS
        if column != "record_id"
    )
    copied = 0
    populated_files = 0
    with psycopg.connect(database_url) as connection:
        if apply_migration:
            connection.execute(migration_path.read_text(encoding="utf-8"))
            connection.commit()

        def upsert_batch(rows: list[dict[str, Any]]) -> None:
            with connection.transaction():
                connection.execute(
                    "create temp table daily_attention_sync_stage "
                    "(like public.daily_attention including defaults) on commit drop"
                )
                with connection.cursor().copy(
                    f"copy daily_attention_sync_stage ({column_sql}) from stdin"
                ) as copy:
                    for row in rows:
                        values = [row[column] for column in ATTENTION_COLUMNS]
                        copy.write_row(values)
                connection.execute(
                    f"insert into public.daily_attention ({column_sql}) "
                    f"select {column_sql} from daily_attention_sync_stage "
                    f"on conflict (record_id) do update set {update_sql}"
                )

        batch: list[dict[str, Any]] = []
        for path in files:
            file_rows = list(attention_rows(path, start=start, end=end))
            if file_rows:
                populated_files += 1
            for row in file_rows:
                batch.append(row)
                copied += 1
                if len(batch) >= ATTENTION_SYNC_BATCH_SIZE:
                    upsert_batch(batch)
                    batch = []
        if batch:
            upsert_batch(batch)
    return copied, populated_files


def _analysis_rows(
    path: Path,
    mapping: dict[str, str],
    *,
    integer_columns: set[str] | None = None,
) -> Iterable[dict[str, Any]]:
    integer_columns = integer_columns or set()
    for row in pq.ParquetFile(path).read().to_pylist():
        result = {output: row[input_name] for output, input_name in mapping.items()}
        for column in integer_columns:
            if result[column] is not None:
                result[column] = int(result[column])
        yield result


def sync_analysis_warehouse(
    *,
    database_url: str,
    data_dir: Path,
    migration_path: Path,
    apply_migration: bool = False,
) -> dict[str, int]:
    """Idempotently upsert derived Analysis Lab tables via COPY."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Supabase sync requires: python -m pip install -e '.[supabase]'"
        ) from exc

    analysis_dir = data_dir / "analysis"
    specifications = [
        (
            "event_effects",
            analysis_dir / "event_effects_all.parquet",
            EVENT_EFFECT_COLUMNS,
            {
                "event_id": "eventId", "hazard_type": "hazardType",
                "alert_level": "alertLevel", "start_at": "startAt", "end_at": "endAt",
                "geography_ids": "geographyIds", "scope": "scope", "topic_id": "topicId",
                "window_days": "windowDays", "timing": "timing", "complete": "complete",
                "missing_days": "missingDays", "overlap": "overlap",
                "matched_pre_mean": "matchedPreMean", "matched_post_mean": "matchedPostMean",
                "matched_change": "matchedChange", "matched_percent_change": "matchedPercentChange",
                "political_pre_mean": "politicalPreMean", "political_post_mean": "politicalPostMean",
                "political_change": "politicalChange",
                "political_percent_change": "politicalPercentChange",
                "political_share_pre": "politicalSharePre",
                "political_share_post": "politicalSharePost",
                "political_share_change": "politicalShareChange",
            },
            "event_id, scope, topic_id, window_days, timing",
            {"window_days", "missing_days"},
        ),
        (
            "daily_event_activity",
            analysis_dir / "daily_event_activity.parquet",
            EVENT_ACTIVITY_COLUMNS,
            {
                "activity_date": "activityDate", "geography": "geography",
                "hazard_type": "hazardType", "alert_level": "alertLevel",
                "events_started": "eventsStarted", "events_active": "eventsActive",
                "events_ended": "eventsEnded",
            },
            "activity_date, geography, hazard_type, alert_level",
            {"events_started", "events_active", "events_ended"},
        ),
        (
            "daily_attention_regions",
            analysis_dir / "daily_attention_regions.parquet",
            REGION_ATTENTION_COLUMNS,
            {
                "observation_date": "observationDate", "region_id": "regionId",
                "topic_id": "topicId", "matched_count": "matchedCount",
                "political_count": "politicalCount",
                "political_actor_count": "politicalActorCount",
                "government_action_count": "governmentActionCount",
                "party_politics_count": "partyPoliticsCount",
                "official_source_count": "officialSourceCount",
                "political_share": "politicalShare",
            },
            "observation_date, region_id, topic_id",
            {
                "matched_count", "political_count", "political_actor_count",
                "government_action_count", "party_politics_count",
                "official_source_count",
            },
        ),
    ]
    for _, path, _, _, _, _ in specifications:
        if not path.exists():
            raise ValueError(f"missing analysis Parquet file: {path}")

    counts: dict[str, int] = {}
    with psycopg.connect(database_url) as connection:
        if apply_migration:
            connection.execute(migration_path.read_text(encoding="utf-8"))
            connection.commit()
        for table, path, columns, mapping, conflict_columns, integer_columns in specifications:
            column_sql = ", ".join(columns)
            update_sql = ", ".join(
                f"{column} = excluded.{column}"
                for column in columns
                if column not in {item.strip() for item in conflict_columns.split(",")}
            )
            rows = _analysis_rows(path, mapping, integer_columns=integer_columns)
            copied = 0
            batch: list[dict[str, Any]] = []

            def upsert_batch(selected: list[dict[str, Any]]) -> None:
                with connection.transaction():
                    stage = f"{table}_sync_stage"
                    connection.execute(
                        f"create temp table {stage} "
                        f"(like public.{table} including defaults) on commit drop"
                    )
                    with connection.cursor().copy(
                        f"copy {stage} ({column_sql}) from stdin"
                    ) as copy:
                        for item in selected:
                            copy.write_row([item[column] for column in columns])
                    connection.execute(
                        f"insert into public.{table} ({column_sql}) "
                        f"select {column_sql} from {stage} "
                        f"on conflict ({conflict_columns}) do update set {update_sql}"
                    )

            for row in rows:
                batch.append(row)
                copied += 1
                if len(batch) >= ANALYSIS_SYNC_BATCH_SIZE:
                    upsert_batch(batch)
                    batch = []
            if batch:
                upsert_batch(batch)
            counts[table] = copied
    return counts
