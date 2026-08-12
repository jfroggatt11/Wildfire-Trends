from datetime import date, datetime, timezone

import pytest

from climate_attention.comparison import compare_attention_shares
from climate_attention.models import DailyTrend


def _trend(source, day, value):
    return DailyTrend(
        record_id=f"{source}-{day}",
        date=date(2026, 1, day),
        source=source,
        topic_id="climate",
        query_id="combined",
        query_expression="climate",
        geography="italy",
        country_attention_share=value,
        collected_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )


def test_compare_attention_shares_pairs_dates_and_computes_correlation():
    trends = [
        _trend("gdelt", 1, 0.01),
        _trend("gdelt", 2, 0.02),
        _trend("gdelt", 3, 0.03),
        _trend("gdelt_ngrams", 1, 0.1),
        _trend("gdelt_ngrams", 2, 0.2),
        _trend("gdelt_ngrams", 3, 0.3),
    ]

    result = compare_attention_shares(
        trends, left_source="gdelt", right_source="gdelt_ngrams"
    )

    assert len(result) == 1
    assert result[0].paired_days == 3
    assert result[0].pearson_correlation == 1.0
    assert result[0].left_mean == 0.02
    assert result[0].right_mean == pytest.approx(0.2)
