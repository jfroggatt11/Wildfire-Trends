# Data dictionary

## Canonical topic trends

Path:
`data/trends/source=<provider>/topic_id=<topic>/geography=<country>/language=<language>/daily.parquet`

| Field | Type | Meaning |
| --- | --- | --- |
| `record_id` | string | Deterministic identity for provider, topic, query, dimension, and date. |
| `date` | date | Provider observation date. GDELT is daily; Google resolution is recorded in metadata. |
| `source` | string | Provider identifier: `gdelt` or `google_trends_unofficial`. |
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

## Article samples and derived counts

`data/raw/` contains article metadata returned by optional GDELT article-list
requests. It does not contain downloaded article bodies. `data/processed/` contains
counts rebuilt from those samples; because article-list responses are capped, these
are not the canonical trend counts.

Prototype Parquet files using `monitored_count` and `attention_share` are read as the
renamed `global_monitored_count` and `global_attention_share`. A partition is upgraded
to the current schema when it is next rewritten.
