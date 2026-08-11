from __future__ import annotations

from datetime import datetime, timezone

import pytest

from climate_attention.models import AttentionRecord


@pytest.fixture
def record_factory():
    def make(**overrides):
        values = {
            "record_id": "record-1",
            "source": "gdelt",
            "source_record_id": "source-1",
            "topic_id": "climate_change",
            "query_id": "climate_phrase",
            "query_expression": '"climate change"',
            "url": "https://example.com/story",
            "title": "A story",
            "domain": "example.com",
            "published_at": datetime(2024, 1, 2, 12, tzinfo=timezone.utc),
            "language": "English",
            "source_country": "United States",
            "geography": None,
            "collected_at": datetime(2024, 2, 1, 12, tzinfo=timezone.utc),
            "metadata": {"socialimage": "https://example.com/image.jpg"},
        }
        values.update(overrides)
        return AttentionRecord(**values)

    return make

