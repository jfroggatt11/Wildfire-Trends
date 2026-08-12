"""Storage abstraction and local Parquet implementation."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .models import AttentionRecord, DailyAttention, DailyCountryCoverage, DailyTrend


RECORD_SCHEMA = pa.schema(
    [
        ("record_id", pa.string()),
        ("source", pa.string()),
        ("source_record_id", pa.string()),
        ("topic_id", pa.string()),
        ("query_id", pa.string()),
        ("query_expression", pa.string()),
        ("url", pa.string()),
        ("title", pa.string()),
        ("domain", pa.string()),
        ("published_at", pa.timestamp("us", tz="UTC")),
        ("language", pa.string()),
        ("source_country", pa.string()),
        ("geography", pa.string()),
        ("collected_at", pa.timestamp("us", tz="UTC")),
        ("metadata_json", pa.string()),
    ]
)

DAILY_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("source", pa.string()),
        ("topic_id", pa.string()),
        ("query_id", pa.string()),
        ("geography", pa.string()),
        ("language", pa.string()),
        ("count", pa.int64()),
    ]
)

TREND_SCHEMA = pa.schema(
    [
        ("record_id", pa.string()),
        ("date", pa.date32()),
        ("source", pa.string()),
        ("topic_id", pa.string()),
        ("query_id", pa.string()),
        ("query_expression", pa.string()),
        ("geography", pa.string()),
        ("language", pa.string()),
        ("matched_count", pa.int64()),
        ("global_monitored_count", pa.int64()),
        ("country_monitored_count", pa.int64()),
        ("global_attention_share", pa.float64()),
        ("country_attention_share", pa.float64()),
        ("attention_index", pa.float64()),
        ("collected_at", pa.timestamp("us", tz="UTC")),
        ("metadata_json", pa.string()),
    ]
)

COUNTRY_COVERAGE_SCHEMA = pa.schema(
    [
        ("record_id", pa.string()),
        ("date", pa.date32()),
        ("source", pa.string()),
        ("geography", pa.string()),
        ("language", pa.string()),
        ("country_monitored_count", pa.int64()),
        ("global_monitored_count", pa.int64()),
        ("collected_at", pa.timestamp("us", tz="UTC")),
        ("metadata_json", pa.string()),
    ]
)


class AttentionStorage(ABC):
    @abstractmethod
    def write_records(self, records: list[AttentionRecord]) -> int:
        """Persist records and return the number newly added."""

        raise NotImplementedError

    @abstractmethod
    def read_records(
        self,
        *,
        source: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[AttentionRecord]:
        raise NotImplementedError

    @abstractmethod
    def write_daily(self, observations: list[DailyAttention]) -> Path:
        raise NotImplementedError


class LocalParquetStorage(AttentionStorage):
    """Partitioned article Parquet plus a compact daily Parquet dataset."""

    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)

    def write_records(self, records: list[AttentionRecord]) -> int:
        groups: dict[tuple[str, date, str, str], list[AttentionRecord]] = defaultdict(list)
        for record in records:
            groups[
                (
                    record.source,
                    record.published_at.date(),
                    record.topic_id,
                    record.query_id,
                )
            ].append(record)

        added = 0
        for (source, day, topic_id, query_id), incoming in groups.items():
            path = self._record_path(source, day, topic_id, query_id)
            existing = self._read_record_file(path) if path.exists() else []
            by_id = {record.record_id: record for record in existing}
            before = len(by_id)
            by_id.update({record.record_id: record for record in incoming})
            added += len(by_id) - before
            rows = [_record_to_row(record) for record in by_id.values()]
            table = pa.Table.from_pylist(rows, schema=RECORD_SCHEMA)
            _atomic_parquet_write(path, table)
        return added

    def read_records(
        self,
        *,
        source: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[AttentionRecord]:
        base = self.root / "raw"
        if source:
            paths = (base / f"source={source}").rglob("records.parquet")
        else:
            paths = base.rglob("records.parquet")
        records: list[AttentionRecord] = []
        for path in sorted(paths):
            records.extend(self._read_record_file(path))
        return [
            record
            for record in records
            if (start is None or record.published_at.date() >= start)
            and (end is None or record.published_at.date() <= end)
        ]

    def write_daily(self, observations: list[DailyAttention]) -> Path:
        path = self.root / "processed" / "daily_attention.parquet"
        rows = [item.model_dump() for item in observations]
        table = pa.Table.from_pylist(rows, schema=DAILY_SCHEMA)
        _atomic_parquet_write(path, table)
        return path

    def read_daily(self) -> list[DailyAttention]:
        path = self.root / "processed" / "daily_attention.parquet"
        if not path.exists():
            return []
        return [DailyAttention.model_validate(row) for row in pq.read_table(path).to_pylist()]

    def append_api_response(self, source: str, run_id: str, envelope: dict[str, Any]) -> Path:
        path = self.root / "api_responses" / source / f"{run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return path

    def write_manifest(self, run_id: str, manifest: dict[str, Any]) -> Path:
        path = self.root / "manifests" / f"{run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def write_trends(self, trends: list[DailyTrend]) -> int:
        """Upsert canonical provider aggregates by stable daily record id."""
        groups: dict[tuple[str, str, str | None, str | None], list[DailyTrend]] = (
            defaultdict(list)
        )
        for trend in trends:
            groups[
                (trend.source, trend.topic_id, trend.geography, trend.language)
            ].append(trend)
        added = 0
        for (source, topic_id, geography, language), incoming in groups.items():
            path = self._trend_path(source, topic_id, geography, language)
            existing = self._read_trend_file(path) if path.exists() else []
            by_id = {trend.record_id: trend for trend in existing}
            before = len(by_id)
            for trend in incoming:
                previous = by_id.get(trend.record_id)
                by_id[trend.record_id] = (
                    _merge_trends(previous, trend) if previous is not None else trend
                )
            added += len(by_id) - before
            coverage_by_date = self._coverage_by_date(source, geography, language)
            normalized = _apply_country_coverage(
                list(by_id.values()), coverage_by_date
            )
            rows = [_trend_to_row(trend) for trend in normalized]
            _atomic_parquet_write(
                path, pa.Table.from_pylist(rows, schema=TREND_SCHEMA)
            )
        return added

    def write_country_coverages(
        self, coverages: list[DailyCountryCoverage]
    ) -> int:
        """Upsert country denominators and refresh affected topic partitions."""
        groups: dict[
            tuple[str, str, str | None], list[DailyCountryCoverage]
        ] = defaultdict(list)
        for coverage in coverages:
            groups[(coverage.source, coverage.geography, coverage.language)].append(
                coverage
            )
        added = 0
        for (source, geography, language), incoming in groups.items():
            path = self._country_coverage_path(source, geography, language)
            existing = self._read_country_coverage_file(path) if path.exists() else []
            by_id = {coverage.record_id: coverage for coverage in existing}
            before = len(by_id)
            by_id.update({coverage.record_id: coverage for coverage in incoming})
            added += len(by_id) - before
            rows = [_country_coverage_to_row(item) for item in by_id.values()]
            _atomic_parquet_write(
                path, pa.Table.from_pylist(rows, schema=COUNTRY_COVERAGE_SCHEMA)
            )
            self._refresh_country_normalization(source, geography, language)
        return added

    def read_country_coverages(
        self,
        *,
        source: str | None = None,
        start: date | None = None,
        end: date | None = None,
        geographies: set[str] | None = None,
    ) -> list[DailyCountryCoverage]:
        base = self.root / "country_coverage"
        paths = (
            (base / f"source={source}").rglob("daily.parquet")
            if source
            else base.rglob("daily.parquet")
        )
        coverages: list[DailyCountryCoverage] = []
        for path in sorted(paths):
            coverages.extend(self._read_country_coverage_file(path))
        return sorted(
            (
                coverage
                for coverage in coverages
                if (start is None or coverage.date >= start)
                and (end is None or coverage.date <= end)
                and (
                    geographies is None
                    or coverage.geography in geographies
                )
            ),
            key=lambda coverage: (
                coverage.date,
                coverage.geography,
                coverage.language or "",
            ),
        )

    def read_trends(
        self,
        *,
        source: str | None = None,
        start: date | None = None,
        end: date | None = None,
        topics: set[str] | None = None,
        geographies: set[str] | None = None,
    ) -> list[DailyTrend]:
        base = self.root / "trends"
        paths = (
            (base / f"source={source}").rglob("daily.parquet")
            if source
            else base.rglob("daily.parquet")
        )
        trends: list[DailyTrend] = []
        for path in sorted(paths):
            trends.extend(self._read_trend_file(path))
        return sorted(
            (
                trend
                for trend in trends
                if (start is None or trend.date >= start)
                and (end is None or trend.date <= end)
                and (topics is None or trend.topic_id in topics)
                and (geographies is None or trend.geography in geographies)
            ),
            key=lambda trend: (
                trend.date,
                trend.topic_id,
                trend.geography or "",
                trend.language or "",
            ),
        )

    def _record_path(
        self, source: str, day: date, topic_id: str, query_id: str
    ) -> Path:
        return (
            self.root
            / "raw"
            / f"source={source}"
            / f"date={day.isoformat()}"
            / f"topic_id={topic_id}"
            / f"query_id={query_id}"
            / "records.parquet"
        )

    def _trend_path(
        self,
        source: str,
        topic_id: str,
        geography: str | None,
        language: str | None,
    ) -> Path:
        return (
            self.root
            / "trends"
            / f"source={source}"
            / f"topic_id={topic_id}"
            / f"geography={geography or 'all'}"
            / f"language={language or 'all'}"
            / "daily.parquet"
        )

    def _country_coverage_path(
        self, source: str, geography: str, language: str | None
    ) -> Path:
        return (
            self.root
            / "country_coverage"
            / f"source={source}"
            / f"geography={geography}"
            / f"language={language or 'all'}"
            / "daily.parquet"
        )

    def _coverage_by_date(
        self, source: str, geography: str | None, language: str | None
    ) -> dict[date, DailyCountryCoverage]:
        if geography is None:
            return {}
        path = self._country_coverage_path(source, geography, language)
        if not path.exists():
            return {}
        return {
            coverage.date: coverage
            for coverage in self._read_country_coverage_file(path)
        }

    def _refresh_country_normalization(
        self, source: str, geography: str, language: str | None
    ) -> None:
        coverage_by_date = self._coverage_by_date(source, geography, language)
        base = self.root / "trends" / f"source={source}"
        pattern = (
            f"topic_id=*/geography={geography}/"
            f"language={language or 'all'}/daily.parquet"
        )
        for path in base.glob(pattern):
            trends = _apply_country_coverage(
                self._read_trend_file(path), coverage_by_date
            )
            rows = [_trend_to_row(trend) for trend in trends]
            _atomic_parquet_write(
                path, pa.Table.from_pylist(rows, schema=TREND_SCHEMA)
            )

    @staticmethod
    def _read_record_file(path: Path) -> list[AttentionRecord]:
        rows = pq.read_table(path).to_pylist()
        records: list[AttentionRecord] = []
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json"))
            records.append(AttentionRecord.model_validate(row))
        return records

    @staticmethod
    def _read_trend_file(path: Path) -> list[DailyTrend]:
        rows = pq.read_table(path).to_pylist()
        trends: list[DailyTrend] = []
        for row in rows:
            # Read prototype files written before normalization scopes were named
            # explicitly. Rewriting the partition upgrades it to the current schema.
            if "global_monitored_count" not in row:
                row["global_monitored_count"] = row.pop("monitored_count", None)
            else:
                row.pop("monitored_count", None)
            if "global_attention_share" not in row:
                row["global_attention_share"] = row.pop("attention_share", None)
            else:
                row.pop("attention_share", None)
            row["metadata"] = json.loads(row.pop("metadata_json"))
            trends.append(DailyTrend.model_validate(row))
        return trends

    @staticmethod
    def _read_country_coverage_file(path: Path) -> list[DailyCountryCoverage]:
        rows = pq.read_table(path).to_pylist()
        coverages: list[DailyCountryCoverage] = []
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json"))
            coverages.append(DailyCountryCoverage.model_validate(row))
        return coverages


def _record_to_row(record: AttentionRecord) -> dict[str, Any]:
    row = record.model_dump(exclude={"metadata"})
    row["metadata_json"] = json.dumps(
        record.metadata, ensure_ascii=False, sort_keys=True, default=str
    )
    return row


def _trend_to_row(trend: DailyTrend) -> dict[str, Any]:
    row = trend.model_dump(exclude={"metadata"})
    row["metadata_json"] = json.dumps(
        trend.metadata, ensure_ascii=False, sort_keys=True, default=str
    )
    return row


def _country_coverage_to_row(coverage: DailyCountryCoverage) -> dict[str, Any]:
    row = coverage.model_dump(exclude={"metadata"})
    row["metadata_json"] = json.dumps(
        coverage.metadata, ensure_ascii=False, sort_keys=True, default=str
    )
    return row


def _apply_country_coverage(
    trends: list[DailyTrend],
    coverage_by_date: dict[date, DailyCountryCoverage],
) -> list[DailyTrend]:
    normalized: list[DailyTrend] = []
    for trend in trends:
        coverage = coverage_by_date.get(trend.date)
        country_count = (
            coverage.country_monitored_count if coverage is not None else None
        )
        country_share = (
            trend.matched_count / country_count
            if country_count and trend.matched_count is not None
            else trend.country_attention_share
        )
        global_share = (
            trend.matched_count / trend.global_monitored_count
            if trend.global_monitored_count and trend.matched_count is not None
            else trend.global_attention_share
        )
        metadata = dict(trend.metadata)
        if coverage is not None:
            metadata.update(
                {
                    "country_coverage_record_id": coverage.record_id,
                    "country_coverage_collected_at": (
                        coverage.collected_at.isoformat()
                    ),
                    "country_normalization_scope": (
                        "source_country_gdelt_monitored_articles"
                    ),
                }
            )
        normalized.append(
            trend.model_copy(
                update={
                    "country_monitored_count": country_count,
                    "country_attention_share": country_share,
                    "global_attention_share": global_share,
                    "metadata": metadata,
                }
            )
        )
    return normalized


def _merge_trends(existing: DailyTrend, incoming: DailyTrend) -> DailyTrend:
    """Merge complementary GDELT modes without erasing populated measurements."""
    comparable = (
        "date",
        "source",
        "topic_id",
        "query_id",
        "query_expression",
        "geography",
        "language",
    )
    mismatched = [
        field
        for field in comparable
        if getattr(existing, field) != getattr(incoming, field)
    ]
    if (
        existing.source == "gdelt_ngrams"
        and incoming.source == "gdelt_ngrams"
        and mismatched == ["query_expression"]
    ):
        # A native-language taxonomy upgrade replaces the canonical topic-day
        # measurement. Frozen manifests/raw envelopes retain both definitions.
        mismatched = []
    if mismatched:
        raise ValueError(
            f"trend record id collision with mismatched fields: {', '.join(mismatched)}"
        )
    metadata = dict(existing.metadata)
    metadata.update(incoming.metadata)
    updates: dict[str, Any] = {
        "collected_at": max(existing.collected_at, incoming.collected_at),
        "metadata": metadata,
    }
    if existing.source == "gdelt_ngrams":
        updates["query_expression"] = incoming.query_expression
    for field in (
        "matched_count",
        "global_monitored_count",
        "country_monitored_count",
        "global_attention_share",
        "country_attention_share",
        "attention_index",
    ):
        incoming_value = getattr(incoming, field)
        updates[field] = (
            incoming_value if incoming_value is not None else getattr(existing, field)
        )
    return existing.model_copy(update=updates)


def _atomic_parquet_write(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd")
    os.replace(temporary, path)
