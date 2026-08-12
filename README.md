# Climate Attention

`climate-attention` is the initial data-collection layer for research on how major
events affect media and search attention around climate change and clean transport.
This version collects canonical daily GDELT media-attention trends, optional
article-level samples, and an explicitly unofficial Google Trends search-interest
index. It does not include event data, event-study analysis, a frontend, or a
database service.

GDELT `TimelineSourceCountry` aggregates are the canonical comparable trend input;
optional `TimelineVolRaw` requests add exact counts for selected validation panels.
Article-list records remain useful for auditing spikes and future classification, but
their 250-result API limit makes them unsuitable as the authoritative count.
The BigQuery-backed Web NGrams mode provides a scalable, distinct-URL comparison
series and is being validated before it replaces any canonical API measure.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Configuration

Copy the example, then edit it without changing Python code:

```bash
cp config/topics.example.yaml config/topics.yaml
climate-attention validate-config --config config/topics.yaml
climate-attention validate-countries --config config/countries.world.yaml
```

Topics are keyed by a stable id and contain one or more query expressions. Queries
may be strings or mappings with an explicit `id`, `expression`, `enabled`, and
optional overrides for `include_terms`, `exclude_terms`, `languages`, and
`geographies`. The same optional fields are available as topic defaults. An omitted
query id is a stable hash of its expression.

For article sampling, `languages` and `geographies` become GDELT `sourcelang:` and
`sourcecountry:` query operators. Values must use terms understood by GDELT. Multiple values generate
separate observations so the requested dimensions remain explicit. Omit these fields
or use empty lists for global, all-language collection. GDELT searches English query
terms across its machine-translated coverage, while each record retains the source's
original language and country. Trend collection instead takes source countries from
`config/countries.world.yaml`, keeping the topic taxonomy separate from the geography
catalog.

The Google mode treats every configured query as one literal search term. It strips
matching outer quotes but does not translate GDELT Boolean syntax, include/exclude
terms, language filters, or topic-level geography fields. Use a separate query entry
for each Google term. Country labels are resolved to ISO country codes; an explicit
`google_geo: IT` value can override resolution in the country YAML.

## Collecting five-year daily trends

The trend command combines all enabled query alternatives within a topic into one
GDELT OR expression. An article matching both `"climate change"` and
`"global warming"` is therefore counted once for the conceptual `climate_change`
topic. The geography dimension is the publishing outlet's source country, not a
country mentioned in the article.

Collect five inclusive years for selected themes and countries:

```bash
climate-attention collect-trends \
  --config config/topics.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics climate_change clean_energy clean_transport electric_vehicles \
  --countries unitedstates unitedkingdom italy france germany china india brazil \
  --start 2021-08-12 \
  --end 2026-08-11
```

Omit `--countries` to retain every enabled country in the world catalog. Omit
`--topics` to use every enabled topic. The default `country-share` mode makes one
global GDELT `TimelineSourceCountry` request per topic and time window, then selects
the requested country series from that response. Each work unit covers at most 366
days and is independently resumable. Use `--country-batch-size 7` to force explicit
country-filtered batches for an audit or fallback; change `--window-days` only after
live validation.

Each output row contains:

```text
date, source, topic_id, query_id, query_expression,
geography, language, matched_count, global_monitored_count,
country_monitored_count, global_attention_share,
country_attention_share, attention_index, collected_at, metadata_json
```

In the default mode, `country_attention_share` is GDELT's native percentage of the
selected country's monitored coverage matching the topic, converted from percent to
a fraction. `matched_count` and the denominator fields are null because this API mode
does not expose them. This normalized share is the preferred measure for comparisons
through time or between countries.

Raw counts remain available as an optional companion collection:

```bash
climate-attention collect-trends \
  --config config/topics.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics clean_energy \
  --countries unitedstates unitedkingdom italy \
  --start 2021-08-12 \
  --end 2026-08-11 \
  --trend-mode raw-counts
```

Raw mode populates `matched_count`, obtains a separate country coverage denominator,
and computes both shares. Stable record identities allow raw results and native
country shares to merge without creating duplicate daily rows.

## Collecting unofficial Google Trends indices

The optional fallback uses `pytrends-modern`'s standard HTTP client. It does not
launch a browser, log into Google, rotate user agents, or configure proxies:

```bash
climate-attention collect-google-trends \
  --config config/topics.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics climate_change clean_energy \
  --countries italy france germany unitedkingdom unitedstates \
  --start 2026-07-01 \
  --end 2026-07-31
```

Each `(query, country, requested date range)` is a separate request and scaling
group. Google normalizes the returned series within that group to `0..100`, stored
in `attention_index`; it is not a count, percentage, or share. Consequently, a raw
index of 80 for Italy is not evidence of twice the search volume represented by 40
in France, and separately requested query alternatives cannot be summed into a topic
total. Analyze within-group changes, or add an explicitly validated anchor/stitching
method before cross-request comparisons.

Google chooses the temporal resolution. A month commonly returns daily observations,
whereas a five-year request commonly returns weekly observations. The actual
`time_resolution`, `is_partial`, and `scaling_group_id` are retained in
`metadata_json`; this mode never labels weekly values as daily. Preview a workload
with `--plan-only`. The conservative defaults are 30 seconds between requests, two
retries, and a 60-second exponential backoff. All work units are checkpointed and
resumable with `runs retry`.

This source is an operational stand-in, not a stable official API. Google can change
or block its web endpoints, results are sampled and normalized, and reproducibility
requires archiving manifests and raw response envelopes. Prefer the official Google
Trends API when project access becomes available.

## Collecting GDELT Web NGrams through BigQuery

Install the optional SDK and authenticate Application Default Credentials:

```bash
python -m pip install -e '.[bigquery,dev]'
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_RESEARCH_PROJECT
```

Use a dedicated research or BigQuery sandbox project—not an unrelated production
project. First request non-billable dry-run estimates:

```bash
climate-attention estimate-ngrams \
  --config config/topics.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics climate_change clean_energy clean_transport electric_vehicles \
  --countries italy unitedkingdom unitedstates india brazil \
  --start 2026-01-01 \
  --end 2026-08-11 \
  --billing-project YOUR_RESEARCH_PROJECT
```

For original-language global matching, use
`config/topics.multilingual.example.yaml`. Its `ngram_phrases` groups associate each
literal with a GDELT language code and either `space` or `character` segmentation.
The bundled English terms are validated against the canonical queries; the nine
translated language groups are research seeds marked `draft` and need native-speaker
review before inferential use. Omitting `--countries` requests all 197 configured
countries in the same topic/window query—it does not create one query per country.

Audit the historical country-domain map before interpreting zeros:

```bash
climate-attention audit-ngram-countries \
  --countries-config config/countries.world.yaml \
  --billing-project YOUR_RESEARCH_PROJECT \
  --output data/audits/ngram-country-map.csv
```

The audit reports mapped-domain counts, sample domains, and possible label matches.
An unsupported mapping is not evidence of zero coverage.

Only after reviewing those estimates, execute with a hard per-job limit slightly
above the reported largest job:

```bash
climate-attention collect-ngrams \
  --config config/topics.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics climate_change clean_energy clean_transport electric_vehicles \
  --countries italy unitedkingdom unitedstates india brazil \
  --start 2026-01-01 \
  --end 2026-08-11 \
  --billing-project YOUR_RESEARCH_PROJECT \
  --maximum-gb-billed MAX_GB_PER_JOB \
  --data-dir data
```

Every job is dry-run again immediately before execution and is rejected if its
estimate exceeds the frozen cap. The default query is counts-only: it reconstructs
configured literal phrases from NGram context and counts each matching URL once per
topic, country, and day. It joins URLs to GDELT's
`domainsbycountry_alllangs_april2015` table by longest domain suffix. Ambiguous and
unmapped domains are excluded, and an overall matched-URL attribution rate is
retained in metadata.

Space-segmented phrases use exact unpunctuated lower- and title-case anchor tokens;
character-segmented phrases use a centered character anchor. This lets BigQuery
prune the clustered `ngram` table but intentionally misses some punctuation and case
forms; treat that as a sensitivity test before production. All translated matches
are deduplicated to one URL per topic/day before country attribution. Adding
`--include-denominator` scans the much larger Article List (`gal`) table and derives
`country_attention_share`, but is optional and can be dramatically more expensive.
Always estimate that mode separately.

This is not semantically identical to the DOC API. NGrams search original-language
article text while the DOC API searches GDELT's English machine translations. The
domain-country table is also a 2015 snapshot. Every row records whether the requested
country has mapped domains, its mapped-domain count, and daily per-language matched
counts. Treat the NGrams output as a candidate measure until the matched-panel
comparison is satisfactory:

```bash
climate-attention compare-sources \
  --left-source gdelt \
  --right-source gdelt_ngrams \
  --topics climate_change clean_energy clean_transport electric_vehicles \
  --countries italy unitedkingdom unitedstates india brazil \
  --start 2026-01-01 \
  --end 2026-08-11 \
  --data-dir data
```

By default the comparison relates the API's `country_attention_share` to the NGram
`matched_count`. The CSV records the selected metrics, paired-day coverage, means,
zero-day counts, and Pearson correlation for each topic-country series. Use explicit
`--left-metric` and `--right-metric` options for other valid comparisons.

A whole-world run is intentionally slow. Live testing showed that GDELT's available
capacity is variable: requests may be rejected even more than a minute apart, while
later retries can succeed. The conservative default is 65 seconds plus exponential
backoff. With four themes and five annual windows, the default global country plan
has 20 requests and takes at least 21.7 minutes before response latency and retries.
The equivalent all-country raw-count plan has 4,925 requests and takes at least 89
hours. It is safe to
interrupt and resume, but the public DOC API is best used for selected study
countries; a complete world backfill will ultimately benefit from GDELT's bulk
datasets. GDELT's [June 2026 guidance](https://blog.gdeltproject.org/using-the-new-web-ngrams-dataset-to-find-relevant-coverage/)
specifically asks high-volume researchers to use its downloadable NGrams while the
legacy search backend is migrated.

Preview and persist the full workload without making an HTTP request:

```bash
climate-attention collect-trends \
  --config config/topics.example.yaml \
  --countries-config config/countries.world.yaml \
  --start 2021-08-12 \
  --end 2026-08-11 \
  --plan-only
```

The command prints its run id, number of windows, and minimum pacing time. Start the
saved plan later with `climate-attention runs retry <run-id>`.

## Collecting article samples

Dates are inclusive and interpreted as UTC:

```bash
climate-attention collect \
  --source gdelt \
  --config config/topics.yaml \
  --start 2024-01-01 \
  --end 2024-01-31
```

All collection modes create a durable run before making their first HTTP request. The run
id is printed immediately. Successful article windows are written to Parquet and
checkpointed as they finish, rather than being held until the entire command ends.

Select a subset of enabled topics with:

```bash
climate-attention collect \
  --source gdelt \
  --config config/topics.yaml \
  --topics climate_change electric_vehicles \
  --start 2024-01-01 \
  --end 2024-01-31
```

For a lower-volume live connectivity check, `config/topics.smoke.yaml` contains one
global `"climate crisis"` query with no country or language restriction. Replace the
dates with a recent UTC day:

```bash
climate-attention collect \
  --source gdelt \
  --config config/topics.smoke.yaml \
  --start 2026-08-10 \
  --end 2026-08-10
```

Article-list requests are initially split into one-day UTC windows. A window that
reaches the API's 250-record ceiling is recursively divided. If a 15-minute window
still reaches the ceiling, collection fails explicitly because completeness cannot
be guaranteed. HTTP 429 and server errors are retried with exponential backoff;
`Retry-After` is honored. Requests are serialized with a conservative six-second
pause after each completed request to reduce pressure on GDELT's shared service.
GDELT's own searchable-history limits still apply—an API rejection is recorded as a
failed run rather than hidden.

The defaults are three retries, a 30-second initial retry delay, and six seconds
between article-list requests or 65 seconds between timeline requests. They can be
changed for a run with `--max-retries`,
`--backoff-seconds`, `--request-interval`, and `--timeout`. Avoid aggressive values
on GDELT's shared public service.

## Resuming and inspecting runs

List durable runs and their successful, failed, and pending window counts:

```bash
climate-attention runs list --data-dir data
```

Inspect one run, including its frozen config snapshot and last error:

```bash
climate-attention runs inspect <run-id> --data-dir data
climate-attention runs inspect <run-id> --data-dir data --json
```

Retry only pending, interrupted, or failed leaf windows:

```bash
climate-attention runs retry <run-id> --data-dir data
```

The equivalent collection form is:

```bash
climate-attention collect --resume <run-id> --data-dir data
```

Runtime settings may be overridden on retry, for example:

```bash
climate-attention runs retry <run-id> \
  --data-dir data \
  --max-retries 5 \
  --backoff-seconds 60 \
  --request-interval 10
```

Completed windows are never requested again. For article sampling, saturated parents remain
marked `split`; only their incomplete descendants are resumed. Ctrl-C records the
run as `interrupted`, persists partial records and aggregates, and leaves its active
window eligible for retry.

## Generated data

The default `data/` layout is:

```text
data/
├── trends/source=.../topic_id=.../geography=.../language=.../daily.parquet
├── country_coverage/source=gdelt/geography=.../language=.../daily.parquet
├── raw/source=gdelt/date=YYYY-MM-DD/topic_id=.../query_id=.../records.parquet
├── processed/daily_attention.parquet
├── api_responses/gdelt/<run-id>.jsonl
├── api_responses/google_trends_unofficial/<run-id>.jsonl
├── runs/<run-id>/
│   ├── state.json
│   ├── config.yaml
│   └── countries.yaml
└── manifests/<run-id>.json
```

Trend and article Parquet partitions are merged by deterministic `record_id`, making
repeated collection idempotent. Complete
GDELT article objects are also retained in each record's `metadata_json`; response
envelopes are preserved as JSONL. Manifests record the config hash, requested dates,
topic definitions, expanded query dimensions, request outcomes, counts, timestamps,
and software versions. `runs/<run-id>/state.json` is the atomically updated
operational request ledger, while `config.yaml` and `countries.yaml` freeze the exact
taxonomy and source-country catalog used by a trend run. The manifest is a
research-facing summary regenerated after each invocation.

Successful windows are written into the shared Parquet datasets immediately. A
dataset can therefore contain valid rows from an incomplete run. Check the relevant
manifest or `runs inspect` output before treating a requested range as complete.

See [methodology](docs/methodology.md), the
[data dictionary](docs/data-dictionary.md), and the
[operations guide](docs/operations.md) before analysis or a long backfill.

## Rebuilding aggregates

The command below rebuilds the legacy article-derived daily sample counts; it does
not overwrite canonical timeline trends:

```bash
climate-attention aggregate --data-dir data
```

Rows contain `date`, `source`, `topic_id`, `query_id`, requested `geography`, article
`language`, and `count`. Query-level rows can later be combined into conceptual topic
metrics with an explicitly chosen cross-query deduplication policy.

## Tests

Tests use mocked HTTP transports and never call live APIs:

```bash
pytest
```
