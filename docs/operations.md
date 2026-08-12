# Operations guide

## Start with a pilot

Validate configuration, then run one topic and a few countries over at least eight
days. A 30-day example is:

```bash
climate-attention validate-config --config config/topics.example.yaml
climate-attention validate-countries --config config/countries.world.yaml

climate-attention collect-trends \
  --config config/topics.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics clean_energy \
  --countries australia india unitedstates \
  --start 2026-07-12 \
  --end 2026-08-10
```

The default plan has one global topic request; the collector retains the three
selected country series from the response. The default 65-second pacing is a minimum,
not a guarantee of acceptance. Add `--country-batch-size 3` to perform the same pilot
with an explicit three-country filter for comparison.
Use `--trend-mode raw-counts` when the pilot specifically needs article counts and
denominators; that equivalent plan has three baseline and three topic requests.

For the unofficial Google fallback, begin with one literal query, one country, and
one month. `config/topics.google.smoke.yaml` is suitable:

```bash
climate-attention collect-google-trends \
  --config config/topics.google.smoke.yaml \
  --countries-config config/countries.world.yaml \
  --countries italy \
  --start 2026-07-01 \
  --end 2026-07-31
```

Confirm that the run completes, `attention_index` is populated, and
`metadata_json.time_resolution` is `daily` before widening the pilot. Do not run
multiple Google collectors in parallel. A 429 is a recoverable provider failure, not
permission to add account automation or rotating proxies.

## Rate-limit recovery

HTTP 429 and server errors receive exponential retries. If the run still fails:

```bash
climate-attention runs inspect <run-id> --data-dir data
climate-attention runs retry <run-id> \
  --data-dir data \
  --max-retries 5 \
  --backoff-seconds 120 \
  --request-interval 90
```

Retries use the frozen configs and skip successful windows. Do not start several
collectors against the public GDELT API in parallel. For thousands of requests,
prefer a selected-country design or the BigQuery NGrams comparison adapter.
GDELT's June 2026 guidance asks researchers to use its downloadable non-consumptive
NGrams data while the legacy search infrastructure is migrated. The implemented
adapter is not interchangeable with the DOC timeline API; its country attribution
and original-language matching must first be validated.

## Matched API and BigQuery overnight validation

Run both collectors over identical dates, topics, and selected countries. The API
still makes one global request per topic; country selection controls retained output.
Use a long interval because GDELT's legacy search capacity is currently constrained:

```bash
caffeinate -i climate-attention collect-trends \
  --config config/topics.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics climate_change clean_energy clean_transport electric_vehicles \
  --countries italy unitedkingdom unitedstates india brazil \
  --start 2026-01-01 \
  --end 2026-08-11 \
  --trend-mode country-share \
  --request-interval 600 \
  --backoff-seconds 1800 \
  --max-retries 4 \
  --timeout 60 \
  --data-dir data
```

In another terminal, authenticate against a dedicated research project and estimate
the four NGram jobs before execution:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_RESEARCH_PROJECT

climate-attention estimate-ngrams \
  --config config/topics.multilingual.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics climate_change clean_energy clean_transport electric_vehicles \
  --countries italy unitedkingdom unitedstates india brazil \
  --start 2026-01-01 \
  --end 2026-08-11 \
  --billing-project YOUR_RESEARCH_PROJECT
```

Omit `--countries` to return every configured country from each topic/window query.
Before doing so, audit the historical domain map:

```bash
climate-attention audit-ngram-countries \
  --countries-config config/countries.world.yaml \
  --billing-project YOUR_RESEARCH_PROJECT
```

Rows with `country_mapping_supported=false` are structurally unavailable and must
not be analyzed as zero-attention days. Review draft translations and inspect the
stored per-language counts before expanding the date range.

Set `--maximum-gb-billed` slightly above the largest reported job, not an arbitrary
large allowance, and then run `collect-ngrams` with the same arguments. BigQuery jobs
do not need pacing; the byte cap controls exposure. Finally run `compare-sources` as
shown in the README. Its default metrics are API `country_attention_share` and NGram
`matched_count`; the NGram denominator is omitted to avoid an expensive GAL scan.
If a normalized NGram share is required, add `--include-denominator` to a fresh
estimate and collection rather than assuming the counts-only estimate applies. Do
not interpret correlation alone as validity: inspect country mapping coverage,
zero-day rates, spikes, anchor-token sensitivity, and differences caused by
original-language versus translated search.

## Verify completeness

```bash
climate-attention runs list --data-dir data
climate-attention runs inspect <run-id> --data-dir data --json
```

Only use a run as a complete requested panel when its status is `complete` and its
failed, pending, and running window counts are all zero. Partial successes are valid
but already exist in the shared Parquet paths.

## Load the data

PyArrow is installed with the package:

```python
import pyarrow.parquet as pq

table = pq.read_table(
    "data/trends/source=gdelt/topic_id=clean_energy/"
    "geography=italy/language=all/daily.parquet"
)
frame = table.to_pandas()
analysis = frame[[
    "date",
    "matched_count",
    "country_monitored_count",
    "country_attention_share",
]]
```

In the default mode, check that `country_attention_share` is populated;
`matched_count` and `country_monitored_count` are expected to be null. In raw mode,
null country denominators mean the corresponding baseline has not been collected or
its denominator was zero.

For Google data, load the matching `source=google_trends_unofficial` partition and
select `date`, `attention_index`, and `metadata_json`. Compare changes only within a
single `scaling_group_id` unless the analysis implements and validates an anchoring
method.

## Preserve provenance

Archive the applicable `data/manifests/<run-id>.json` and
`data/runs/<run-id>/` directory with analytical outputs. They preserve the exact
dates, frozen configs, expanded queries, runtime settings, request outcomes, and
software version. Avoid editing snapshots inside a run directory.
