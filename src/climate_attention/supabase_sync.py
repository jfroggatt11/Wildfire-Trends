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
