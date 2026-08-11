from __future__ import annotations

import pytest

from climate_attention.config import ConfigError, load_config
from climate_attention.models import Query


def test_parses_string_and_object_queries(tmp_path):
    path = tmp_path / "topics.yaml"
    path.write_text(
        """
topics:
  climate_change:
    label: Climate change
    languages: [English]
    queries:
      - '"climate change"'
      - id: crisis
        expression: '"climate crisis"'
        exclude_terms: [film]
""",
        encoding="utf-8",
    )

    config = load_config(path)

    topic = config.topics[0]
    assert topic.id == "climate_change"
    assert topic.queries[0].id.startswith("q_")
    assert topic.queries[1].id == "crisis"
    expanded = Query.from_topic(topic)
    assert expanded[0].topic_id == "climate_change"
    assert expanded[1].exclude_terms == ["film"]
    assert all(item.language == "English" for item in expanded)


def test_query_dimensions_expand_and_query_override_wins(tmp_path):
    path = tmp_path / "topics.yaml"
    path.write_text(
        """
topics:
  transport:
    label: Transport
    languages: [English, French]
    geographies: [US, FR]
    queries:
      - expression: rail
        languages: [German]
""",
        encoding="utf-8",
    )
    query_values = Query.from_topic(load_config(path).topics[0])
    assert {(item.language, item.geography) for item in query_values} == {
        ("German", "US"),
        ("German", "FR"),
    }


@pytest.mark.parametrize(
    "yaml_text, expected",
    [
        ("topics: []", "must be a mapping"),
        ("topics: {}", "at least one topic"),
        (
            "topics:\n  Bad ID:\n    label: Test\n    queries: [test]",
            "string_pattern_mismatch",
        ),
        (
            "topics:\n  valid:\n    label: Test\n    queries: ['  ']",
            "must not be blank",
        ),
    ],
)
def test_config_validation_errors_are_useful(tmp_path, yaml_text, expected):
    path = tmp_path / "topics.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ConfigError, match=expected):
        load_config(path)


def test_unknown_topic_filter_is_rejected(tmp_path):
    path = tmp_path / "topics.yaml"
    path.write_text(
        "topics:\n  climate:\n    label: Climate\n    queries: [climate]",
        encoding="utf-8",
    )
    config = load_config(path)
    with pytest.raises(ValueError, match="unknown topic"):
        config.enabled_topics({"missing"})


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "topics.yaml"
    path.write_text(
        "schema_version: 2\ntopics:\n  climate:\n    label: Climate\n    queries: [climate]",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="schema_version"):
        load_config(path)
