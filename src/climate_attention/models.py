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


class NGramPhrase(StrictModel):
    """A native-language literal used only by the Web NGrams adapter."""

    text: str = Field(min_length=1)
    language: str = Field(pattern=r"^[a-z]{2,3}$")
    segmentation: Literal["space", "character"] = "space"
    translation_status: Literal["draft", "validated"] = "draft"
    notes: str | None = None

    @field_validator("text", "language")
    @classmethod
    def phrase_values_are_trimmed(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("NGram phrase values must not be blank")
        return cleaned


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
    ngram_phrases: list[NGramPhrase] = Field(default_factory=list)
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
        phrase_keys = [
            (item.text.casefold(), item.language, item.segmentation)
            for item in self.ngram_phrases
        ]
        if len(phrase_keys) != len(set(phrase_keys)):
            raise ValueError(f"NGram phrases must be unique within topic {self.id!r}")
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
    geographies: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def geography_modes_are_exclusive(self) -> "Query":
        if self.geography is not None and self.geographies:
            raise ValueError("query cannot define both geography and geographies")
        if len(set(self.geographies)) != len(self.geographies):
            raise ValueError("query geographies must be unique")
        if any(not geography.strip() for geography in self.geographies):
            raise ValueError("query geographies must not be blank")
        return self

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


class DailyTrend(StrictModel):
    """A dated provider trend observation for one configured dimension."""

    record_id: str
    date: date
    source: str
    topic_id: str
    query_id: str
    query_expression: str
    geography: str | None = None
    language: str | None = None
    matched_count: int | None = Field(default=None, ge=0)
    global_monitored_count: int | None = Field(default=None, ge=0)
    country_monitored_count: int | None = Field(default=None, ge=0)
    global_attention_share: float | None = Field(default=None, ge=0)
    country_attention_share: float | None = Field(default=None, ge=0)
    attention_index: float | None = Field(default=None, ge=0, le=100)
    political_count: int | None = Field(default=None, ge=0)
    political_actor_count: int | None = Field(default=None, ge=0)
    government_action_count: int | None = Field(default=None, ge=0)
    party_politics_count: int | None = Field(default=None, ge=0)
    official_source_count: int | None = Field(default=None, ge=0)
    political_share_of_matched: float | None = Field(default=None, ge=0, le=1)
    collected_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("collected_at")
    @classmethod
    def collection_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collection timestamp must include a timezone")
        return value.astimezone(timezone.utc)


class MatchedArticle(StrictModel):
    """A topic-matched article and all retained GDELT Article List metadata."""

    record_id: str
    date: date
    source: str = "gdelt_ngrams"
    topic_id: str
    geography: str
    url: str
    domain: str | None = None
    published_at: datetime | None = None
    outlet_name: str | None = None
    outlet_logo: str | None = None
    outlet_twitter: str | None = None
    title: str | None = None
    image_url: str | None = None
    description: str | None = None
    language: str | None = None
    author: str | None = None
    political_actor: bool = False
    government_action: bool = False
    party_politics: bool = False
    official_source: bool = False
    collected_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def political(self) -> bool:
        return (
            self.political_actor
            or self.government_action
            or self.party_politics
            or self.official_source
        )

    @field_validator("collected_at")
    @classmethod
    def article_sample_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collection timestamp must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("published_at")
    @classmethod
    def publication_timestamp_must_be_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("publication timestamp must include a timezone")
        return value.astimezone(timezone.utc)


# Backward-compatible name for runs created while article output was sample-only.
PoliticalArticleSample = MatchedArticle


class DailyCountryCoverage(StrictModel):
    """Total GDELT coverage for one source country and day."""

    record_id: str
    date: date
    source: str
    geography: str
    language: str | None = None
    country_monitored_count: int = Field(ge=0)
    global_monitored_count: int | None = Field(default=None, ge=0)
    collected_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("collected_at")
    @classmethod
    def coverage_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collection timestamp must include a timezone")
        return value.astimezone(timezone.utc)


class DailyHazard(StrictModel):
    """A provider-neutral physical hazard measurement for one country-day."""

    record_id: str
    date: date
    source: str
    hazard_type: str
    geography: str
    country_iso3: str = Field(pattern=r"^[A-Z]{3}$")
    observation_count: int | None = Field(default=None, ge=0)
    total_intensity: float | None = Field(default=None, ge=0)
    mean_intensity: float | None = Field(default=None, ge=0)
    max_intensity: float | None = Field(default=None, ge=0)
    high_confidence_count: int | None = Field(default=None, ge=0)
    request_complete: bool
    boundary_supported: bool
    collected_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("collected_at")
    @classmethod
    def hazard_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collection timestamp must include a timezone")
        return value.astimezone(timezone.utc)


class HazardEvent(StrictModel):
    """A named major event from an external disaster catalogue."""

    record_id: str
    source: str
    source_event_id: str
    hazard_type: str
    name: str
    start_at: datetime
    end_at: datetime | None = None
    geography_ids: list[str] = Field(default_factory=list)
    country_iso3s: list[str] = Field(default_factory=list)
    alert_level: str | None = None
    alert_score: float | None = None
    severity: float | None = None
    severity_unit: str | None = None
    source_url: str | None = None
    source_updated_at: datetime | None = None
    collected_at: datetime = Field(default_factory=utc_now)
    geometry: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("start_at", "end_at", "source_updated_at", "collected_at")
    @classmethod
    def event_timestamps_must_be_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def event_date_range_is_valid(self) -> "HazardEvent":
        if self.end_at is not None and self.end_at < self.start_at:
            raise ValueError("event end must not precede event start")
        if len(self.geography_ids) != len(set(self.geography_ids)):
            raise ValueError("event geography ids must be unique")
        if len(self.country_iso3s) != len(set(self.country_iso3s)):
            raise ValueError("event country ISO3 codes must be unique")
        return self


class RequestLog(StrictModel):
    window_id: str | None = None
    parent_window_id: str | None = None
    query_id: str
    topic_id: str
    start: datetime
    end: datetime
    status: Literal["success", "failed", "split"]
    attempts: int = Field(ge=0)
    records_returned: int = Field(ge=0)
    http_status: int | None = None
    error: str | None = None


class ProviderResult(StrictModel):
    records: list[AttentionRecord] = Field(default_factory=list)
    requests: list[RequestLog] = Field(default_factory=list)


class TrendProviderResult(StrictModel):
    trends: list[DailyTrend] = Field(default_factory=list)
    country_coverages: list[DailyCountryCoverage] = Field(default_factory=list)
    requests: list[RequestLog] = Field(default_factory=list)
