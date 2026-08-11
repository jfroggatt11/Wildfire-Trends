"""Provider-neutral daily aggregation."""

from __future__ import annotations

from collections import Counter

from .models import AttentionRecord, DailyAttention


def aggregate_daily(records: list[AttentionRecord]) -> list[DailyAttention]:
    """Deduplicate records and count observations by analytical dimensions."""
    unique = {record.record_id: record for record in records}
    counts: Counter[tuple[object, ...]] = Counter()
    for record in unique.values():
        key = (
            record.published_at.date(),
            record.source,
            record.topic_id,
            record.query_id,
            record.geography,
            record.language,
        )
        counts[key] += 1
    return sorted(
        (
            DailyAttention(
                date=key[0],
                source=key[1],
                topic_id=key[2],
                query_id=key[3],
                geography=key[4],
                language=key[5],
                count=count,
            )
            for key, count in counts.items()
        ),
        key=lambda item: (
            item.date,
            item.source,
            item.topic_id,
            item.query_id,
            item.geography or "",
            item.language or "",
        ),
    )

