# Climate Attention

`climate-attention` is the initial data-collection layer for research on how major
events affect media and search attention around climate change and clean transport.
This version collects canonical daily GDELT media-attention trends and optional
article-level samples. It does not include event data, event-study analysis, a
frontend, or a database service.

GDELT `TimelineVolRaw` aggregates are the canonical trend input. Article-list records
remain useful for auditing spikes and future classification, but their 250-result API
limit makes them unsuitable as the authoritative count.

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

Omit `--countries` to plan every enabled country in the world catalog. Omit
`--topics` to use every enabled topic. The default work unit is at most 366 days, so
a five-year topic-country series is split into five independently resumable requests.
Change this with `--window-days` if live GDELT testing establishes a different
reliable range.

Each output row contains:

```text
date, source, topic_id, query_id, query_expression,
geography, language, matched_count, monitored_count,
attention_share, collected_at, metadata_json
```

`matched_count` is the raw number of distinct matching articles reported by GDELT.
`monitored_count` is GDELT's `norm` value for that interval and
`attention_share = matched_count / monitored_count`. The raw count is the requested
country-by-theme measure; retain the normalized series for longitudinal sensitivity
analysis because GDELT's total monitoring volume varies over time.

A whole-world run is intentionally slow. With four themes, roughly 196 countries,
five annual windows, and the default ten-second interval, it plans about 3,900 API
requests and can take eleven hours or more before retries. It is safe to interrupt
and resume. Start with a few countries to validate the taxonomy before launching the
full catalog.

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

Both collection modes create a durable run before making their first HTTP request. The run
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
between article-list requests or ten seconds between timeline requests. They can be
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
├── trends/source=gdelt/topic_id=.../geography=.../language=.../daily.parquet
├── raw/source=gdelt/date=YYYY-MM-DD/topic_id=.../query_id=.../records.parquet
├── processed/daily_attention.parquet
├── api_responses/gdelt/<run-id>.jsonl
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

## Google Trends

`GoogleTrendsProvider` implements the provider interface but intentionally raises an
informative error until official Google Trends API access and credentials are added.
The project does not use `pytrends` or unofficial scraping. A future official adapter
can emit the same provider-neutral records without changing configuration, storage,
aggregation, or CLI orchestration.
