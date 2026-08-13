"""YAML topic configuration loading and validation."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from .models import ID_PATTERN, NGramPhrase, StrictModel, TopicConfig


class ConfigError(ValueError):
    """Raised when a topic configuration cannot be loaded or validated."""


def _normalize_query(value: Any) -> Any:
    if isinstance(value, str):
        return {"expression": value}
    return value


def _normalize_ngram_phrases(value: Any, *, topic_id: str) -> list[dict[str, Any]]:
    """Expand compact language mappings into validated phrase records."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        raise ConfigError(
            f"topic {topic_id!r} 'ngram_phrases' must be a mapping or list"
        )
    normalized: list[dict[str, Any]] = []
    for language, raw_group in value.items():
        segmentation = "space"
        translation_status = "draft"
        notes = None
        phrases = raw_group
        if isinstance(raw_group, dict):
            phrases = raw_group.get("phrases")
            segmentation = raw_group.get("segmentation", "space")
            translation_status = raw_group.get("translation_status", "draft")
            notes = raw_group.get("notes")
        if not isinstance(phrases, list):
            raise ConfigError(
                f"topic {topic_id!r} NGram language {language!r} must contain "
                "a phrase list"
            )
        for phrase in phrases:
            if isinstance(phrase, str):
                normalized.append(
                    {
                        "text": phrase,
                        "language": language,
                        "segmentation": segmentation,
                        "translation_status": translation_status,
                        "notes": notes,
                    }
                )
            elif isinstance(phrase, dict):
                normalized.append(
                    {
                        "language": language,
                        "segmentation": segmentation,
                        "translation_status": translation_status,
                        "notes": notes,
                        **phrase,
                    }
                )
            else:
                raise ConfigError(
                    f"topic {topic_id!r} NGram phrase must be text or a mapping"
                )
    return normalized


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
        topic["ngram_phrases"] = _normalize_ngram_phrases(
            topic.get("ngram_phrases"), topic_id=topic_id
        )
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
    iso3: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    gdelt_ngram_label: str | None = Field(default=None, min_length=1)

    @property
    def ngram_label(self) -> str:
        return self.gdelt_ngram_label or self.label


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


class PoliticalSignal(StrictModel):
    """One interpretable political-discourse dimension."""

    id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1)
    phrases: list[NGramPhrase] = Field(min_length=1)
    description: str | None = None


class PoliticalConfig(StrictModel):
    schema_version: Literal[1] = 1
    signals: list[PoliticalSignal]
    official_domains: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def political_dimensions_are_valid(self) -> "PoliticalConfig":
        ids = [signal.id for signal in self.signals]
        if len(ids) != len(set(ids)):
            raise ValueError("political signal ids must be unique")
        required = {"political_actor", "government_action", "party_politics"}
        missing = required - set(ids)
        if missing:
            raise ValueError(
                "political configuration is missing signals: "
                + ", ".join(sorted(missing))
            )
        for country_id, domains in self.official_domains.items():
            if not country_id or not domains:
                raise ValueError("official-domain groups must not be empty")
            cleaned = [domain.strip().lower().lstrip(".") for domain in domains]
            if any(not domain or "/" in domain for domain in cleaned):
                raise ValueError("official domains must be bare host names")
            if len(cleaned) != len(set(cleaned)):
                raise ValueError(f"duplicate official domain for {country_id!r}")
            self.official_domains[country_id] = cleaned
        return self

    def phrase_mapping(self) -> dict[str, list[dict[str, Any]]]:
        return {
            signal.id: [phrase.model_dump(mode="json") for phrase in signal.phrases]
            for signal in self.signals
        }


def load_political_config(path: str | Path) -> PoliticalConfig:
    config_path = Path(path)
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read political config {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError("political configuration root must be a mapping")
    raw_signals = document.get("signals")
    if not isinstance(raw_signals, dict):
        raise ConfigError("'signals' must be a mapping keyed by political signal id")
    signals: list[dict[str, Any]] = []
    for signal_id, raw_signal in raw_signals.items():
        if not isinstance(raw_signal, dict):
            raise ConfigError(f"political signal {signal_id!r} must be a mapping")
        raw_phrases = raw_signal.get("phrases")
        signals.append(
            {
                "id": signal_id,
                **raw_signal,
                "phrases": _normalize_ngram_phrases(
                    raw_phrases, topic_id=f"political signal {signal_id}"
                ),
            }
        )
    try:
        return PoliticalConfig.model_validate(
            {
                "schema_version": document.get("schema_version", 1),
                "signals": signals,
                "official_domains": document.get("official_domains", {}),
            }
        )
    except ValidationError as exc:
        raise ConfigError(f"invalid political configuration:\n{exc}") from exc
