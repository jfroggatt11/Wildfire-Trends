# Climate Attention

`climate-attention` is the initial data-collection layer for research on how major
events affect media and search attention around climate change and clean transport.
This version collects article-level GDELT observations and derives daily counts. It
does not include event data, event-study analysis, a frontend, or a database service.

Article records remain the canonical input. Daily counts can therefore be rebuilt as
the taxonomy and analytical choices evolve.

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
```

Topics are keyed by a stable id and contain one or more query expressions. Queries
may be strings or mappings with an explicit `id`, `expression`, `enabled`, and
optional overrides for `include_terms`, `exclude_terms`, `languages`, and
`geographies`. The same optional fields are available as topic defaults. An omitted
query id is a stable hash of its expression.

`languages` and `geographies` become GDELT `sourcelang:` and `sourcecountry:` query
operators. Values must use terms understood by GDELT. Multiple values generate
separate observations so the requested dimensions remain explicit.

## Collecting GDELT data

Dates are inclusive and interpreted as UTC:

```bash
climate-attention collect \
  --source gdelt \
  --config config/topics.yaml \
  --start 2024-01-01 \
  --end 2024-01-31
```

Select a subset of enabled topics with:

```bash
climate-attention collect \
  --source gdelt \
  --config config/topics.yaml \
  --topics climate_change electric_vehicles \
  --start 2024-01-01 \
  --end 2024-01-31
```

GDELT DOC requests are initially split into one-day UTC windows. A window that
reaches the API's 250-record ceiling is recursively divided. If a 15-minute window
still reaches the ceiling, collection fails explicitly because completeness cannot
be guaranteed. HTTP 429 and server errors are retried with exponential backoff;
`Retry-After` is honored. GDELT's own searchable-history limits still apply—an API
rejection is recorded as a failed run rather than hidden.

## Generated data

The default `data/` layout is:

```text
data/
├── raw/source=gdelt/date=YYYY-MM-DD/topic_id=.../query_id=.../records.parquet
├── processed/daily_attention.parquet
├── api_responses/gdelt/<run-id>.jsonl
└── manifests/<run-id>.json
```

Parquet article partitions are merged by deterministic `record_id`, making repeated
collection idempotent for the same source/topic/query/dimensions/article. Complete
GDELT article objects are also retained in each record's `metadata_json`; response
envelopes are preserved as JSONL. Manifests record the config hash, requested dates,
topic definitions, expanded query dimensions, request outcomes, counts, timestamps,
and software versions. A failed run may retain completed earlier windows; rerunning
the same command safely deduplicates them and is the recovery mechanism in this
version.

## Rebuilding aggregates

Rebuild the canonical daily dataset from all locally stored article records:

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
