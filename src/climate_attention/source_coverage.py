"""Known provider outages and reproducible coverage corrections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class KnownOutage:
    source: str
    start: date
    end: date
    label: str
    evidence_url: str

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


KNOWN_OUTAGES = (
    KnownOutage(
        source="gdelt_ngrams",
        start=date(2025, 6, 14),
        end=date(2025, 7, 1),
        label="GDELT infrastructure outage",
        evidence_url=(
            "https://www.linkedin.com/posts/kalevleetaru_"
            "we-are-aware-of-multiple-gdelt-infrastructure-activity-"
            "7340435180601393154-_SDg"
        ),
    ),
)


def _day(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


def known_outages(source: str, *, year: int | None = None) -> tuple[KnownOutage, ...]:
    return tuple(
        outage
        for outage in KNOWN_OUTAGES
        if outage.source == source
        and (year is None or outage.start.year <= year <= outage.end.year)
    )


def is_known_outage(source: str, day: date | datetime | str) -> bool:
    value = _day(day)
    return any(outage.contains(value) for outage in known_outages(source))


def available_date_segments(
    source: str, start: date, end: date
) -> list[tuple[date, date]]:
    """Return inclusive date segments after removing confirmed provider outages."""
    if end < start:
        return []
    unavailable: set[date] = set()
    for outage in known_outages(source):
        for offset in range((outage.end - outage.start).days + 1):
            outage_day = outage.start + timedelta(days=offset)
            if start <= outage_day <= end:
                unavailable.add(outage_day)
    segments: list[tuple[date, date]] = []
    segment_start: date | None = None
    current = start
    while current <= end:
        if current in unavailable:
            if segment_start is not None:
                segments.append((segment_start, current - timedelta(days=1)))
                segment_start = None
        elif segment_start is None:
            segment_start = current
        current += timedelta(days=1)
    if segment_start is not None:
        segments.append((segment_start, end))
    return segments


def remove_known_outage_rows(
    data_dir: Path, *, source: str = "gdelt_ngrams"
) -> tuple[int, int]:
    """Atomically remove rows dated inside confirmed outages from trend Parquets."""
    root = data_dir / "trends" / f"source={source}"
    removed = 0
    changed_files = 0
    for path in sorted(root.rglob("daily.parquet")):
        table = pq.read_table(path)
        if "date" not in table.column_names:
            continue
        keep = [not is_known_outage(source, value) for value in table["date"].to_pylist()]
        removed_here = len(keep) - sum(keep)
        if not removed_here:
            continue
        filtered = table.filter(pa.array(keep))
        temporary = path.with_suffix(".parquet.tmp")
        pq.write_table(filtered, temporary, compression="zstd")
        temporary.replace(path)
        removed += removed_here
        changed_files += 1
    return removed, changed_files
