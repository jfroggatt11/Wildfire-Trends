"""Provider-neutral domain models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from itertools import product
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ID_PATTERN = r"^[a-z][a-z0-9_-]*$"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generated_query_id(expression: str) -> str:
    """Return a stable identifier when a query id is omitted from YAML."""
    return f"q_{sha256(expression.encode('utf-8')).hexdigest()[:12]}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuerySpec(StrictModel):
    """A configured search expression belonging to one topic."""

    id: str | None = Field(default=None, pattern=ID_PATTERN)
    expression: str = Field(min_length=1)
    enabled: bool = True
    include_terms: list[str] | None = None
    exclude_terms: list[str] | None = None
    languages: list[str] | None = None
    geographies: list[str] | None = None
    notes: str | None = None

    @field_validator("expression")
    @classmethod
    def expression_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query expression must not be blank")
        return value

    @field_validator(
        "include_terms", "exclude_terms", "languages", "geographies"
    )
    @classmethod
    def lists_have_nonblank_unique_values(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("list values must not be blank")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("list values must be unique")
        return cleaned

    @model_validator(mode="after")
    def fill_id(self) -> "QuerySpec":
        if self.id is None:
            self.id = generated_query_id(self.expression)
        return self


class Topic(StrictModel):
    """A conceptual subject that may contain several search expressions."""

    id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1)
    enabled: bool = True
    queries: list[QuerySpec] = Field(min_length=1)
    include_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    geographies: list[str] = Field(default_factory=list)
    description: str | None = None
    notes: str | None = None

    @field_validator(
        "include_terms", "exclude_terms", "languages", "geographies"
    )
    @classmethod
    def nonblank_unique_values(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("list values must not be blank")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("list values must be unique")
        return cleaned

    @model_validator(mode="after")
    def query_ids_are_unique(self) -> "Topic":
        ids = [query.id for query in self.queries]
        if len(set(ids)) != len(ids):
            raise ValueError(f"query ids must be unique within topic {self.id!r}")
        return self


class TopicConfig(StrictModel):
    schema_version: Literal[1] = 1
    topics: list[Topic]

    @model_validator(mode="after")
    def topic_ids_are_unique(self) -> "TopicConfig":
        ids = [topic.id for topic in self.topics]
        if len(set(ids)) != len(ids):
            raise ValueError("topic ids must be unique")
        if not self.topics:
            raise ValueError("at least one topic is required")
        return self

    def enabled_topics(self, selected: set[str] | None = None) -> list[Topic]:
        known = {topic.id for topic in self.topics}
        unknown = (selected or set()) - known
        if unknown:
            raise ValueError(f"unknown topic id(s): {', '.join(sorted(unknown))}")
        return [
            topic
            for topic in self.topics
            if topic.enabled and (selected is None or topic.id in selected)
        ]


class Query(StrictModel):
    """A provider request after topic defaults and dimensions are expanded."""

    topic_id: str
    query_id: str
    expression: str
    include_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    language: str | None = None
    geography: str | None = None

    @classmethod
    def from_topic(cls, topic: Topic) -> list["Query"]:
        expanded: list[Query] = []
        for spec in topic.queries:
            if not spec.enabled:
                continue
            languages = spec.languages if spec.languages is not None else topic.languages
            geographies = (
                spec.geographies
                if spec.geographies is not None
                else topic.geographies
            )
            language_values: list[str | None] = languages or [None]
            geography_values: list[str | None] = geographies or [None]
            includes = [*topic.include_terms, *(spec.include_terms or [])]
            excludes = [*topic.exclude_terms, *(spec.exclude_terms or [])]
            for language, geography in product(language_values, geography_values):
                expanded.append(
                    cls(
                        topic_id=topic.id,
                        query_id=spec.id or generated_query_id(spec.expression),
                        expression=spec.expression,
                        include_terms=list(dict.fromkeys(includes)),
                        exclude_terms=list(dict.fromkeys(excludes)),
                        language=language,
                        geography=geography,
                    )
                )
        return expanded


class CollectionRequest(StrictModel):
    start: date
    end: date
    topics: list[Topic]

    @model_validator(mode="after")
    def valid_date_range(self) -> "CollectionRequest":
        if self.end < self.start:
            raise ValueError("end date must be on or after start date")
        if not self.topics:
            raise ValueError("no enabled topics were selected")
        return self


class AttentionRecord(StrictModel):
    """A raw or minimally normalized observation from any provider."""

    record_id: str
    source: str
    source_record_id: str | None = None
    topic_id: str
    query_id: str
    query_expression: str
    url: str | None = None
    title: str | None = None
    domain: str | None = None
    published_at: datetime
    language: str | None = None
    source_country: str | None = None
    geography: str | None = None
    collected_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("published_at", "collected_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class DailyAttention(StrictModel):
    date: date
    source: str
    topic_id: str
    query_id: str
    geography: str | None = None
    language: str | None = None
    count: int = Field(ge=0)


class RequestLog(StrictModel):
    query_id: str
    topic_id: str
    start: datetime
    end: datetime
    status: Literal["success", "failed"]
    attempts: int = Field(ge=1)
    records_returned: int = Field(ge=0)
    http_status: int | None = None
    error: str | None = None


class ProviderResult(StrictModel):
    records: list[AttentionRecord] = Field(default_factory=list)
    requests: list[RequestLog] = Field(default_factory=list)
