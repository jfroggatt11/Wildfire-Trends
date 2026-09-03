# Data dictionary

## Canonical topic trends

Path:
`data/trends/source=<provider>/topic_id=<topic>/geography=<country>/language=<language>/daily.parquet`

| Field | Type | Meaning |
| --- | --- | --- |
| `record_id` | string | Deterministic identity for provider, topic, query, dimension, and date. |
| `date` | date | Provider observation date. GDELT is daily; Google resolution is recorded in metadata. |
| `source` | string | Provider identifier: `gdelt`, `gdelt_ngrams`, or `google_trends_unofficial`. |
| `topic_id` | string | Stable configured conceptual topic id. |
| `query_id` | string | `topic_combined` for canonical topic trends. |
| `query_expression` | string | Exact combined expression sent with provider filters. |
| `geography` | string | Requested GDELT publishing-outlet source country id. |
| `language` | string/null | Requested original source language; null means all supported languages. |
| `matched_count` | integer/null | Distinct matching articles; null in native country-share mode. |
| `global_monitored_count` | integer/null | All articles GDELT monitored globally that day (`norm`). |
| `country_monitored_count` | integer/null | All articles monitored for the requested source country/language that day. |
| `global_attention_share` | float/null | `matched_count / global_monitored_count`. |
| `country_attention_share` | float/null | Native GDELT country percentage divided by 100, or the equivalent raw-count ratio. |
| `attention_index` | float/null | Google Trends request-normalized interest index in `0..100`; null for GDELT. |
| `collected_at` | UTC timestamp | Retrieval time for this provider response. |
| `metadata_json` | JSON string | Query details, series label, geography label, query scope, response series count, and normalization scopes. |

For `google_trends_unofficial`, `matched_count`, denominator, and share fields are
null. Metadata includes the provider geo, requested range, actual time resolution,
partial-point flag, and `scaling_group_id`. Record identity includes that group, so
overlapping ranges with different normalization contexts are not silently merged.
Indexes from different scaling groups are not raw-level comparable.

For `gdelt_ngrams`, `matched_count` is the number of distinct URLs matching any
configured literal phrase for the topic, country, and date. The default counts-only
mode leaves `country_monitored_count` and `country_attention_share` null. With the
optional denominator mode, `country_monitored_count` is the number of distinct URLs
in GDELT's GAL table attributed to the country that day, and
`country_attention_share` is their ratio. Metadata records phrases, anchor-variant
policy, BigQuery job and byte details, URL deduplication, attribution rate, and
country-map limitations. Multilingual runs also record `configured_languages`, daily
`language_counts`, `country_mapping_supported`, and `mapped_domain_count`. Batched
runs record `bigquery_collection_mode=multi_topic_batch` and
`bigquery_batch_topic_ids`; these are operational metadata and do not alter canonical
topic-level identity.

## Country coverage baselines

Path:
`data/country_coverage/source=gdelt/geography=<country>/language=<language>/daily.parquet`

| Field | Type | Meaning |
| --- | --- | --- |
| `record_id` | string | Deterministic identity for provider, dimension, and date. |
| `date` | date | UTC calendar day. |
| `source` | string | Provider identifier. |
| `geography` | string | GDELT source country id. |
| `language` | string/null | Original-language restriction, if any. |
| `country_monitored_count` | integer | Raw articles returned by the country-only baseline query. |
| `global_monitored_count` | integer/null | Global GDELT `norm` for the same interval. |
| `collected_at` | UTC timestamp | Baseline retrieval time. |
| `metadata_json` | JSON string | Provider query details and display label. |

Country baselines are auxiliary observations. Writing a baseline automatically
updates matching topic partitions with `country_monitored_count` and
`country_attention_share`, including topic rows collected by an earlier run.

Native country-share and raw-count observations use the same deterministic record
identity. Storage merges their non-null measurements, so collecting raw counts later
augments rather than duplicates the canonical daily row.

## Physical hazard country-days

Path: `data/hazards/source=firms/hazard_type=wildfire/daily.parquet`

| Field | Type | Meaning |
| --- | --- | --- |
| `record_id` | string | Stable provider/product/hazard/date/country identity. |
| `date` | date | UTC FIRMS acquisition date. |
| `source` | string | `firms`. |
| `hazard_type` | string | `wildfire`. |
| `geography` | string | Stable id from the configured country catalogue. |
| `country_iso3` | string | Three-letter country code used for spatial/event joins. |
| `observation_count` | integer/null | Retained active-fire detections; null if boundary support is unavailable. |
| `total_intensity` | float/null | Sum of retained fire radiative power in MW. |
| `mean_intensity` | float/null | Mean retained fire radiative power in MW. |
| `max_intensity` | float/null | Maximum retained fire radiative power in MW. |
| `high_confidence_count` | integer/null | Retained detections marked high confidence. |
| `request_complete` | boolean | All source windows needed for this emitted row completed. |
| `boundary_supported` | boolean | Country has a matching polygon; false rows contain nulls rather than false zeroes. |
| `collected_at` | UTC timestamp | Aggregation time. |
| `metadata_json` | JSON string | Product, unit, world scope, and filtering policy. |

A measured zero means the complete API responses contained no retained detection in
the country polygon that day. It does not prove absence of fire where satellite
observations were obscured or unavailable.

## Major hazard events

Path: `data/events/source=gdacs/events.parquet`

Each row is one GDACS event, not one country-day. Important fields are
`source_event_id`, `hazard_type`, `name`, `start_at`, `end_at`, `geography_ids`,
`country_iso3s`, `alert_level`, `alert_score`, `severity`, `severity_unit`,
`source_url`, `source_updated_at`, and `geometry_json`. `metadata_json` preserves the
episode id, GDACS hazard/source codes, episode alert, severity text, detail/geometry
URLs, and any affected ISO3 code not found in the configured country catalogue.

Event records are mutable upstream. A later collection with the same stable event id
and a newer provider modification timestamp replaces the canonical record instead of
creating a duplicate.

For GDACS wildfires, `severity` with `severity_unit = "ha"` is the cumulative
reported burned area. The Attention Timeline assigns that whole-event value to the
event start date, or sums start-date values in its trailing-window views. This is
not a daily perimeter series or a measure of unique non-overlapping land burned.

## Article samples and derived counts

`data/raw/` contains article metadata returned by optional GDELT article-list
requests. It does not contain downloaded article bodies. `data/processed/` contains
counts rebuilt from those samples; because article-list responses are capped, these
are not the canonical trend counts.

Prototype Parquet files using `monitored_count` and `attention_share` are read as the
renamed `global_monitored_count` and `global_attention_share`. A partition is upgraded
to the current schema when it is next rewritten.
