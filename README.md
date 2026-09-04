# Climate Attention

`climate-attention` is the initial data-collection layer for research on how major
events affect media and search attention around climate change and clean transport.
This version collects canonical daily GDELT media-attention trends, optional
article-level samples, and an explicitly unofficial Google Trends search-interest
index. It also collects an independent global event layer from NASA FIRMS and
GDACS, and includes a research frontend with an optional Supabase serving layer.
Causal event-study estimation remains future work.

GDELT `TimelineSourceCountry` aggregates are the canonical comparable trend input;
optional `TimelineVolRaw` requests add exact counts for selected validation panels.
Article-list records remain useful for auditing spikes and future classification, but
their 250-result API limit makes them unsuitable as the authoritative count.
The BigQuery-backed Web NGrams mode provides a scalable, distinct-URL comparison
series and is being validated before it replaces any canonical API measure.

## Frontend MVP

`frontend/` contains the Netlify-ready Climate Attention Atlas: a React and
TypeScript map explorer for GDACS events, media-market comparisons, aggregate topic
and political-attention counts, and a multi-event Analysis Lab. The Lab compares
wildfire and flood events across climate-change and electric-vehicle attention,
retains only complete daily windows, and flags same-country overlaps. Orange and
Red alerts remain the primary cohort; Green alerts and the complete catalogue are
available as sensitivity filters. A stable period control supports either year, the
whole available 2025–2026 series, and a custom start/end range shared by every Lab
tab. Timeline markers can use either GDACS alert tiers or wildfire burned-area
bands; no comparable flood-size category is inferred from the current export. The
comparison view can overlay GDACS start-date cumulative wildfire hectares, MODIS
daily observed burned hectares, or both against either attention topic on a separately
labelled axis. The two burn measures remain distinct, and event onset lines and
diamonds can be hidden independently. When MODIS vegetation aggregates have been
imported, another option compares attention with same-season surface
greenness/browning (NDVI anomaly) and adds a date-linked brown-to-green country map.

Export the current Parquet datasets to compact browser assets, then run the app:

```bash
.venv/bin/python scripts/export_frontend_data.py
cd frontend
npm install
npm run dev
```

Event-point countries use the pinned Natural Earth 1:50m Admin-0 file in
`data/reference/`. Regional labels use the Natural Earth 1:10m Admin-1 states and
provinces GeoJSON (version 5.1.1), stored locally as
`data/reference/ne_10m_admin_1_states_provinces.geojson.gz`. These labels describe
the point supplied by GDACS; they do not replace GDACS's affected-country list.

The root `netlify.toml` builds and publishes the Vite app. Article-level Parquet is
retained locally for validation, but the public interface is not an article finder
and does not publish URLs or detailed article records.

### MODIS satellite aggregates

The vegetation workflow streams only the NDVI or EVI band from NASA's monthly global
MOD13C2 version 6.1 product through Earthdata Cloud OPeNDAP. Each roughly 8–10 MB
NetCDF subset is aggregated to countries and deleted before the next month, so no
source-raster archive is retained. Credentials are read only from
`EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` (or `EARTHDATA_TOKEN`). Install the
optional dependencies, load the credentials, and collect the baseline plus display
period in one resumable command:

```bash
python -m pip install -e '.[satellite]'
set -a; source .env; set +a
climate-attention collect-modis-vegetation \
  --countries-config config/countries.world.yaml \
  --start 2001-01-01 --end 2020-12-31 \
  --metric ndvi
climate-attention collect-modis-vegetation \
  --countries-config config/countries.world.yaml \
  --start 2025-01-01 --end 2026-08-27 \
  --metric ndvi
```

The collector writes every completed month immediately and records it in
`data/satellite/mod13c2-progress.json`. If interrupted, rerun the same command;
completed country-months are skipped. It computes latitude-area-weighted
country, World, and EU27 means and same-month anomalies against the 2001–2020
climatology. MOD13C2's 0.05-degree grid is appropriate to this country-level view but
not to local land-surface analysis. The older MOD13A2 AppEEARS commands remain
available for targeted high-resolution extracts, not the global baseline.

MCD64 burned area uses `Burn_Date` rasters because an average ordinal burn date
cannot produce hectares. Install the optional raster reader, request the burned-area
metric in native projection, and import the downloaded rasters:

```bash
python -m pip install -e '.[satellite]'
climate-attention prepare-modis-request \
  --countries-config config/countries.world.yaml \
  --start 2025-01-01 --end 2025-12-31 \
  --metric burned_area \
  --output data/satellite/requests/burned-2025.json \
  --aid-map data/satellite/requests/burned-2025-aid-map.json
EARTHDATA_USERNAME=your_username EARTHDATA_PASSWORD=your_password \
  climate-attention run-appeears-task \
  --request data/satellite/requests/burned-2025.json \
  --include-burn-date-rasters
climate-attention import-modis-burned-area \
  --rasters data/satellite/appeears/TASK_ID/MCD64A1.061_Burn_Date_*.tif \
  --aid-map data/satellite/requests/burned-2025-aid-map.json
```

Finally rerun `scripts/export_frontend_data.py`. Its satellite JSON contains only
the attention-window aggregates required by the browser. The current vegetation MVP
covers all valid land pixels; a fixed grassland/cropland mask is a planned refinement
rather than an implied property of these values.

The frontend export also rebuilds the 2025 and 2026 major-event study assets. The
Analysis Lab exposes a study-period selector plus a date-range control and bounds
partial-period charts to actual stored attention coverage. Rebuild one analysis
without the other frontend assets with:

```bash
climate-attention build-event-study \
  --data-dir data \
  --year 2025 \
  --frontend-output frontend/public/data/event-study.json
```

The canonical flat effect table contains event, topic, mutually exclusive media
group, window, timing, completeness, overlap and pre/post measures. The compact
static file contains the primary major-event cohort and acts as a deployment
fallback.

Build the all-alert Analysis Lab warehouse and load its three derived tables into
Supabase:

```bash
climate-attention sync-analysis-supabase \
  --data-dir data \
  --year 2025 \
  --apply-migration
```

This materialises event-level effects, sparse country-day event activity, and daily
global/EU27 attention. The browser requests only the selected specification and
country, rather than downloading raw articles or millions of event-day rows. The
Event activity view offers Green/major/all-alert filters, 7- or 28-day rolling event
starts, both MVP attention topics, and exploratory lead/lag correlations. Event load
and attention use aligned panels rather than a dual axis; attention defaults to a
strict 7-day trailing average, with raw daily values available as a display option.
Positive lag means attention follows event activity. Lag series are faceted on a
shared scale and values inside |r| < 0.10 are labelled as descriptively negligible.
These correlations do not adjust for autocorrelation, seasonality or common news
shocks. Country comparison mode shows one selected attention topic and rolling event
starts for two to five countries. Country rankings default to at least three eligible events,
offer 1/2/3/5/10-event thresholds, and sort by event count or absolute response. The attention
chart defaults to a labelled symmetric 98%-range focus scale with a full-range
option, while the lead/lag axis adapts to the observed correlations. A separate
Attention timeline shows observed distinct-URL counts for the world, EU27, one
country or a custom country group. It can compare both MVP topics or draw separate
lines for up to eight publishing markets, using all or political matching URLs.
Daily counts and gap-aware 7-, 14- and 28-day rolling averages are available. The
marker filter supports Orange/Red, Green-only or all GDACS tiers; missing provider
dates remain visible gaps and are never imputed or smoothed across.

GDELT's confirmed infrastructure outage is treated as missing coverage from
14 June through 1 July 2025. Collection plans skip that interval, analytical windows
crossing it are incomplete, and the frontend renders a visible gap. To repair a
dataset created before this rule was added, run:

```bash
climate-attention repair-known-outages --data-dir data
```

Then rebuild the frontend and Analysis Lab exports and resync Supabase. The repair is
idempotent; it never converts missing dates to zero.

At the current 2025 scale the derived warehouse is small enough for Supabase and a
static frontend. A separate Render service is not required; it would become useful
only for scheduled multi-year recomputation or heavier statistical models.

Load the two MVP topics' daily aggregate counts into Supabase:

```bash
python -m pip install -e '.[supabase]'
climate-attention sync-supabase \
  --data-dir data \
  --start 2025-01-01 \
  --end 2025-03-31 \
  --apply-migration
```

The command idempotently upserts daily country-topic counts, including the distinct
political union and component counts. Complete GAL metadata, URLs, descriptions and
phrase-level match evidence remain in canonical local Parquet for validation.
`SUPABASE_DB_URL` is server-side only. The frontend uses only
`VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`, protected by read-only row
level security. Set `VITE_USE_SUPABASE=true` after the daily table is populated.
The frontend export script also writes these browser-safe values to
`frontend/src/supabase-config.json`, allowing Netlify Git builds to work when the
project role cannot manage hosted environment variables. Never place
`SUPABASE_DB_URL` in that file.

Run the frontend unit and browser regression suites with:

```bash
cd frontend
npm test
npm run test:e2e
```

The end-to-end tests automatically use an installed Chrome or Chromium. If
neither is available, install Playwright's managed browser once with
`npm run test:e2e:install`.

The browser suite covers media-scope combinations, date entry and empty/reversed
ranges, hazard and alert filters, event selection, embedded previews, and every
event-detail tab.

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
countries. All selected themes, phrases, languages, and countries share one BigQuery
scan per date window; the result is still separated into canonical topic-country-day
rows.

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
  --config config/topics.multilingual.example.yaml \
  --countries-config config/countries.world.yaml \
  --topics climate_change clean_energy clean_transport electric_vehicles \
  --countries italy unitedkingdom unitedstates india brazil \
  --start 2026-01-01 \
  --end 2026-08-11 \
  --billing-project YOUR_RESEARCH_PROJECT \
  --maximum-gb-billed MAX_GB_PER_JOB \
  --data-dir data
```

### Worldwide 2025 political-discourse MVP

The MVP enables two multilingual topics—climate change and electric vehicles—and
returns every country supported by the world configuration. The clean-energy and
clean-transport definitions remain available but disabled for historical comparison.
It adds three article-level signals—political
actors, government action, and party politics—plus an initial registry of government,
parliament, and party domains for the five European pilot countries. Exact counts
and their union are stored on each daily trend row. Every matched URL can also be
retained with all available GDELT Article List (GAL) metadata. This does not query
GDELT's Knowledge Graph.

In an August 2026 dry-run check for 6 January 2025, the two-topic political/article
query estimated 30.491 GB versus 34.882 GB for the previous four-topic query (12.6%
less). A Sunday check estimated 25.215 GB versus 28.398 GB (11.2% less). The political
signal vocabulary remains part of both scans, so halving the topic count does not
halve billed bytes. Dry runs are non-billable and every new range must be estimated.

Estimate the full calendar year first (dry runs do not incur query charges):

```bash
climate-attention estimate-ngrams \
  --config config/topics.multilingual.example.yaml \
  --countries-config config/countries.world.yaml \
  --political-config config/political_signals.europe5.yaml \
  --save-articles \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --window-days 31 \
  --billing-project YOUR_RESEARCH_PROJECT
```

Then run the identical workload with a cap just above the largest monthly estimate:

```bash
climate-attention collect-ngrams \
  --config config/topics.multilingual.example.yaml \
  --countries-config config/countries.world.yaml \
  --political-config config/political_signals.europe5.yaml \
  --save-articles \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --window-days 31 \
  --billing-project YOUR_RESEARCH_PROJECT \
  --maximum-gb-billed MAX_GB_PER_JOB \
  --data-dir data
```

Matched articles are written under `data/articles`. Retained fields are publication
time, URL, domain, outlet name/logo/Twitter handle, title, image, description,
language, author, topic/country and political flags. Each article also retains one
deterministically selected NGram context per matched topic or political phrase:
the phrase, configured language and segmentation, plus GDELT's `pre`, `ngram`, and
`post` fields. Up to 100 distinct phrase contexts are stored per article-topic row;
the exact total and a truncation flag are recorded. GAL may have no value for some
fields, which are then stored as null. The political translations and official-domain
registry are research seeds and must be audited before inferential analysis. The
official-domain flag currently has curated coverage only for the five pilot countries;
generic political phrase signals still apply in all configured languages worldwide.
Changing the requested output from five to all countries has little scan-cost effect
because BigQuery identifies topic URLs before country attribution.

Export any stored date range to a single reviewable CSV without querying BigQuery:

```bash
climate-attention export-articles \
  --start 2025-01-01 \
  --end 2025-01-01 \
  --data-dir data \
  --output data/exports/political-classifications-2025-01-01.csv
```

The CSV includes every article row, compact `matched_topic_phrases` and
`matched_political_phrases` columns, full `match_evidence_json`, a computed
`political` union flag, and the four component flags. Add `--political-only`,
`--topics`, or `--countries` to produce
a narrower review file. Exporting reads local Parquet only and incurs no API cost.

Every date-window job is dry-run again immediately before execution and is rejected
if its estimate exceeds the frozen cap. The default query is counts-only: it scans
the NGram table once for all selected topics, reconstructs configured literal phrases
from context, assigns every match to its topic or topics, and counts each URL at most
once per topic, country, and day. An article matching two different topics is validly
counted once in each. It joins URLs to GDELT's
`domainsbycountry_alllangs_april2015` table by longest domain suffix. Ambiguous and
unmapped domains are excluded, and an overall matched-URL attribution rate is
retained in metadata.

Space-segmented phrases use exact unpunctuated lower- and title-case anchor tokens;
character-segmented phrases use a centered character anchor. This lets BigQuery
prune the clustered `ngram` table but intentionally misses some punctuation and case
forms; treat that as a sensitivity test before production. All translated matches
are deduplicated to one URL per topic/day before country attribution. Batch
checkpointing is per date window, while stored topic IDs and record IDs remain
compatible with the older per-topic jobs. Adding
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

## Collecting global wildfire and major-event data

The event layer deliberately does not infer physical extreme-weather events from the
same news coverage used as the outcome. NASA FIRMS supplies daily physical wildfire
activity; GDACS supplies named major wildfires, floods, and tropical cyclones to the
canonical archive. The public MVP exports only GDACS wildfires and floods.

Request a free NASA FIRMS `MAP_KEY`, copy the environment template, and place the
key in the ignored project-root `.env` file:

```bash
cp .env.example .env
```

```dotenv
FIRMS_MAP_KEY=your-personal-key
```

An exported shell variable with the same name takes precedence over `.env`. Preview
the 2025 global workload with:

```bash

climate-attention collect-firms \
  --countries-config config/countries.world.yaml \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --plan-only
```

Run it by removing `--plan-only`. The collector uses the FIRMS `world` area and
non-overlapping windows of at most five days. Every raw response is cached by product
and date window, so rerunning after interruption does not repeat completed downloads.
The default product is science-quality `VIIRS_SNPP_SP`; it is appropriate for the
historical panel but arrives months after near-real-time products. The collector
retains presumed vegetation fires (`type=0`), excludes low-confidence detections,
assigns points to all 197 configured countries using a checksummed, revision-pinned
Natural Earth boundary file, and derives daily detection and fire-radiative-power
metrics. The map key is never stored.

FIRMS is free, but NASA charges large responses against a transaction allowance. A
global response can contain tens of thousands of detections per day. Keep the cached
windows, use the conservative 25-second pacing default, and do not launch overlapping
runs. A 365-day plan contains 73 requests and therefore has roughly 30 minutes of
deliberate pacing, in addition to download and processing time.

Collect the corresponding GDACS catalogue independently:

```bash
climate-attention collect-gdacs \
  --countries-config config/countries.world.yaml \
  --start 2025-01-01 \
  --end 2025-12-31
```

GDACS results are fetched in pages of 100 and cached as GeoJSON. Canonical records
preserve provider event ids, start/end timestamps, affected ISO3 countries, alert
level and score, severity, geometry, source URLs, modification time, and extra
provider metadata. FIRMS hotspots are not treated as named disasters: use the GDACS
wildfire catalogue to identify major events and FIRMS to measure their physical
country-day intensity.

GDELT searches about extreme weather can later measure an event's media salience or
audit missing catalogue entries. They should not define the main event treatment,
because deriving both the event and attention outcome from GDELT would introduce
circular selection and additional BigQuery scanning cost.

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
├── hazards/source=firms/hazard_type=wildfire/daily.parquet
├── events/source=gdacs/events.parquet
├── raw_events/firms/<product>/<start>_<end>.csv
├── raw_events/gdacs/<start>_<end>_pageNNNN.geojson
├── reference/ne_50m_admin_0_countries.geojson
├── reference/ne_10m_admin_1_states_provinces.geojson.gz
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
