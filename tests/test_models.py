from datetime import date

import pytest
from pydantic import ValidationError

from climate_attention.models import CollectionRequest, Query, QuerySpec, Topic


def test_date_range_is_inclusive_and_must_be_ordered():
    topic = Topic(label="Climate", id="climate", queries=[QuerySpec(expression="climate")])
    request = CollectionRequest(
        start=date(2024, 1, 1), end=date(2024, 1, 1), topics=[topic]
    )
    assert request.start == request.end

    with pytest.raises(ValidationError, match="end date"):
        CollectionRequest(
            start=date(2024, 1, 2), end=date(2024, 1, 1), topics=[topic]
        )


def test_topic_and_query_mapping_combines_terms():
    topic = Topic(
        id="climate",
        label="Climate",
        include_terms=["policy"],
        exclude_terms=["sports"],
        queries=[
            QuerySpec(
                id="warming",
                expression='"global warming"',
                include_terms=["government"],
                exclude_terms=["movie"],
            )
        ],
    )
    query = Query.from_topic(topic)[0]
    assert query.topic_id == "climate"
    assert query.query_id == "warming"
    assert query.include_terms == ["policy", "government"]
    assert query.exclude_terms == ["sports", "movie"]

