"""YAML topic configuration loading and validation."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import QuerySpec, TopicConfig


class ConfigError(ValueError):
    """Raised when a topic configuration cannot be loaded or validated."""


def _normalize_query(value: Any) -> Any:
    if isinstance(value, str):
        return {"expression": value}
    return value


def _normalize_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ConfigError("configuration root must be a mapping")
    raw_topics = document.get("topics")
    if not isinstance(raw_topics, dict):
        raise ConfigError("'topics' must be a mapping keyed by topic id")

    topics: list[dict[str, Any]] = []
    for topic_id, raw_topic in raw_topics.items():
        if not isinstance(raw_topic, dict):
            raise ConfigError(f"topic {topic_id!r} must be a mapping")
        topic = {"id": topic_id, **raw_topic}
        raw_queries = topic.get("queries")
        if isinstance(raw_queries, list):
            topic["queries"] = [_normalize_query(value) for value in raw_queries]
        topics.append(topic)
    return {
        "schema_version": document.get("schema_version", 1),
        "topics": topics,
    }


def load_config(path: str | Path) -> TopicConfig:
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {config_path}: {exc}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
    try:
        return TopicConfig.model_validate(_normalize_document(document))
    except ValidationError as exc:
        raise ConfigError(f"invalid topic configuration:\n{exc}") from exc


def config_hash(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()

