"""Matched-panel comparison of trend sources."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .models import DailyTrend


@dataclass(frozen=True)
class SourceComparison:
    topic_id: str
    geography: str
    left_source: str
    right_source: str
    left_metric: str
    right_metric: str
    paired_days: int
    left_days: int
    right_days: int
    pearson_correlation: float | None
    left_mean: float
    right_mean: float
    left_zero_days: int
    right_zero_days: int


def compare_attention_shares(
    trends: list[DailyTrend], *, left_source: str, right_source: str
) -> list[SourceComparison]:
    """Compare country attention shares on dates present in both sources."""
    return compare_trends(
        trends,
        left_source=left_source,
        right_source=right_source,
        left_metric="country_attention_share",
        right_metric="country_attention_share",
    )


def compare_trends(
    trends: list[DailyTrend],
    *,
    left_source: str,
    right_source: str,
    left_metric: str,
    right_metric: str,
) -> list[SourceComparison]:
    """Compare two explicitly selected metrics on paired country-topic dates."""
    allowed = {"matched_count", "country_attention_share", "attention_index"}
    if left_metric not in allowed or right_metric not in allowed:
        raise ValueError("unsupported comparison metric")
    grouped: dict[tuple[str, str, str], dict[date, float]] = defaultdict(dict)
    for trend in trends:
        if trend.source not in {left_source, right_source}:
            continue
        metric = left_metric if trend.source == left_source else right_metric
        value = getattr(trend, metric)
        if trend.geography is None or value is None:
            continue
        key = (trend.source, trend.topic_id, trend.geography)
        existing = grouped[key].get(trend.date)
        if existing is not None and not math.isclose(
            existing, float(value)
        ):
            raise ValueError(
                f"multiple {trend.source} attention shares for {trend.topic_id}/"
                f"{trend.geography}/{trend.date}"
            )
        grouped[key][trend.date] = float(value)

    dimensions = {
        (topic, geography)
        for source, topic, geography in grouped
        if source in {left_source, right_source}
    }
    comparisons: list[SourceComparison] = []
    for topic, geography in sorted(dimensions):
        left = grouped.get((left_source, topic, geography), {})
        right = grouped.get((right_source, topic, geography), {})
        paired_dates = sorted(set(left) & set(right))
        if not paired_dates:
            continue
        left_values = [left[day] for day in paired_dates]
        right_values = [right[day] for day in paired_dates]
        comparisons.append(
            SourceComparison(
                topic_id=topic,
                geography=geography,
                left_source=left_source,
                right_source=right_source,
                left_metric=left_metric,
                right_metric=right_metric,
                paired_days=len(paired_dates),
                left_days=len(left),
                right_days=len(right),
                pearson_correlation=_pearson(left_values, right_values),
                left_mean=sum(left_values) / len(left_values),
                right_mean=sum(right_values) / len(right_values),
                left_zero_days=sum(value == 0 for value in left_values),
                right_zero_days=sum(value == 0 for value in right_values),
            )
        )
    return comparisons


def write_comparisons(path: str | Path, rows: list[SourceComparison]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(SourceComparison.__dataclass_fields__)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    return output


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right)
    )
    left_sum = sum((value - left_mean) ** 2 for value in left)
    right_sum = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_sum * right_sum)
    return numerator / denominator if denominator else None
