"""YAML topic configuration loading and validation."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from .models import ID_PATTERN, StrictModel, TopicConfig


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


class Country(StrictModel):
    """A stable source-country dimension and its display label."""

    id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1)
    enabled: bool = True
    google_geo: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class CountryConfig(StrictModel):
    schema_version: Literal[1] = 1
    countries: list[Country]

    @model_validator(mode="after")
    def country_ids_are_unique(self) -> "CountryConfig":
        ids = [country.id for country in self.countries]
        if not ids:
            raise ValueError("at least one country is required")
        if len(ids) != len(set(ids)):
            raise ValueError("country ids must be unique")
        return self

    def enabled_countries(self, selected: set[str] | None = None) -> list[Country]:
        known = {country.id for country in self.countries}
        unknown = (selected or set()) - known
        if unknown:
            raise ValueError(f"unknown country id(s): {', '.join(sorted(unknown))}")
        return [
            country
            for country in self.countries
            if country.enabled and (selected is None or country.id in selected)
        ]


def load_country_config(path: str | Path) -> CountryConfig:
    config_path = Path(path)
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read country config {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError("country configuration root must be a mapping")
    raw = document.get("countries")
    if not isinstance(raw, dict):
        raise ConfigError("'countries' must be a mapping keyed by GDELT country id")
    countries: list[dict[str, Any]] = []
    for country_id, value in raw.items():
        if isinstance(value, str):
            countries.append({"id": country_id, "label": value})
        elif isinstance(value, dict):
            countries.append({"id": country_id, **value})
        else:
            raise ConfigError(f"country {country_id!r} must be a label or mapping")
    try:
        return CountryConfig.model_validate(
            {
                "schema_version": document.get("schema_version", 1),
                "countries": countries,
            }
        )
    except ValidationError as exc:
        raise ConfigError(f"invalid country configuration:\n{exc}") from exc
