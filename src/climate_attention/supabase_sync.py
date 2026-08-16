"""Bulk-load the canonical matched-article panel into Supabase Postgres."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


MVP_TOPICS = {"climate_change", "electric_vehicles"}
ARTICLE_COLUMNS = (
    "record_id",
    "article_date",
    "source",
    "topic_id",
    "geography",
    "url",
    "domain",
    "published_at",
    "outlet_name",
    "outlet_logo",
    "outlet_twitter",
    "title",
    "image_url",
    "description",
    "language",
    "author",
    "political_actor",
    "government_action",
    "party_politics",
    "official_source",
    "match_evidence",
    "match_evidence_total",
    "match_evidence_truncated",
    "collected_at",
    "metadata",
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


def article_files(data_dir: Path, topics: set[str]) -> list[Path]:
    root = data_dir / "articles" / "source=gdelt_ngrams"
    return sorted(
        path
        for topic in sorted(topics)
        for path in (root / f"topic_id={topic}").rglob("articles.parquet")
    )


def article_rows(
    path: Path, *, start: date | None = None, end: date | None = None
) -> Iterable[dict[str, Any]]:
    for row in pq.ParquetFile(path).read().to_pylist():
        day = row["date"]
        if (start is not None and day < start) or (end is not None and day > end):
            continue
        yield {
            "record_id": row["record_id"],
            "article_date": day,
            "source": row["source"],
            "topic_id": row["topic_id"],
            "geography": row["geography"],
            "url": row["url"],
            "domain": row["domain"],
            "published_at": row["published_at"],
            "outlet_name": row["outlet_name"],
            "outlet_logo": row["outlet_logo"],
            "outlet_twitter": row["outlet_twitter"],
            "title": row["title"],
            "image_url": row["image_url"],
            "description": row["description"],
            "language": row["language"],
            "author": row["author"],
            "political_actor": row["political_actor"],
            "government_action": row["government_action"],
            "party_politics": row["party_politics"],
            "official_source": row["official_source"],
            "match_evidence": json.loads(row.get("match_evidence_json") or "[]"),
            "match_evidence_total": row.get("match_evidence_total") or 0,
            "match_evidence_truncated": bool(row.get("match_evidence_truncated")),
            "collected_at": row["collected_at"],
            "metadata": json.loads(row.get("metadata_json") or "{}"),
        }


def sync_articles(
    *,
    database_url: str,
    data_dir: Path,
    migration_path: Path,
    topics: set[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    apply_migration: bool = False,
) -> tuple[int, int]:
    """Idempotently upsert selected Parquet article partitions via COPY."""
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError(
            "Supabase sync requires: python -m pip install -e '.[supabase]'"
        ) from exc

    selected_topics = set(topics or MVP_TOPICS)
    unsupported = selected_topics - MVP_TOPICS
    if unsupported:
        raise ValueError("unsupported Supabase topic(s): " + ", ".join(sorted(unsupported)))
    files = article_files(data_dir, selected_topics)
    if not files:
        raise ValueError(f"no matched article Parquet files found under {data_dir}")

    column_sql = ", ".join(ARTICLE_COLUMNS)
    update_sql = ", ".join(
        f"{column} = excluded.{column}"
        for column in ARTICLE_COLUMNS
        if column != "record_id"
    )
    copied = 0
    populated_files = 0
    with psycopg.connect(database_url) as connection:
        if apply_migration:
            connection.execute(migration_path.read_text(encoding="utf-8"))
            connection.commit()
        for path in files:
            rows = list(article_rows(path, start=start, end=end))
            if not rows:
                continue
            with connection.transaction():
                connection.execute(
                    "create temp table article_sync_stage "
                    "(like public.articles including defaults) on commit drop"
                )
                with connection.cursor().copy(
                    f"copy article_sync_stage ({column_sql}) from stdin"
                ) as copy:
                    for row in rows:
                        values = [row[column] for column in ARTICLE_COLUMNS]
                        values[ARTICLE_COLUMNS.index("match_evidence")] = Jsonb(
                            row["match_evidence"]
                        )
                        values[ARTICLE_COLUMNS.index("metadata")] = Jsonb(row["metadata"])
                        copy.write_row(values)
                connection.execute(
                    f"insert into public.articles ({column_sql}) "
                    f"select {column_sql} from article_sync_stage "
                    f"on conflict (record_id) do update set {update_sql}"
                )
            copied += len(rows)
            populated_files += 1
    return copied, populated_files
