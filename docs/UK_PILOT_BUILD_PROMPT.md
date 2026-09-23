# UK Attention Atlas — Codex initial-build prompt

Build the initial UK Attention Atlas pilot in:

`../Climate_Attention_Atlas_UK`

The destination repository is currently empty. It will be owned and operated by T&E.
Use Codex as the implementation partner: inspect the specification and reference
repository, write a milestone plan, implement one milestone at a time, run the
relevant tests/builds, repair failures before continuing, and keep a durable status
and decision log in the new repository.

## Read these inputs first

Treat these as the project specification and visual product reference:

- `/Users/jonahfroggatt/Downloads/UK Attention Atlas - One-Pager.md`
- `/Users/jonahfroggatt/Downloads/UK Attention Atlas — Technical Plan (2).md`
- `../Wildfire-Trends/docs/UK_PILOT_PLAN.md`
- `../Wildfire-Trends/docs/UK_DATA_LAYER_AUDIT_2026-09-23.md`
- `../Wildfire-Trends/docs/ARCHITECTURE_BRIEFING_2026-09-15.md`
- `../Wildfire-Trends/docs/UK_APP_SCREEN_DESIGN.md`
- `../Wildfire-Trends/docs/UK_APP_SCREEN_MOCKUP.html`

Copy the two approved planning documents into the new repository under `docs/` with
permanent filenames. Also copy the screen design and mockup into `docs/` as the
initial frontend reference. Adapt the mockup into the working React interface; do
not leave it as a disconnected static demo.

Use `../Wildfire-Trends` as a read-only reference and source of selected initial
files. Copy code deliberately; do not copy credentials, `.env` files, generated
research datasets, cached API responses, historical exports, local databases, or the
entire old interface. The old repository must remain unchanged.

At the start, create:

- `PLAN.md`: milestones, acceptance checks and decisions still needed;
- `STATUS.md`: current milestone, verification commands, known issues and next step;
- `docs/`: copied specifications, architecture notes, data dictionary and methods.

## Product and research scope

The pilot is a UK-focused research and monitoring tool for measuring attention and
its relationship with events and real-world conditions. The initial topics are:

- Climate change
- Cost of living
- Clean transport
- Electric vehicles as a separately selectable subtopic

The initial attention channels are:

- GDELT Web NGrams news attention;
- a small, explicitly labelled Bluesky social-posting line;
- the existing MODIS UK greenness line;
- official Google Trends after T&E receives API access.

X is optional and must not block the first pilot. Predictive modelling, causal claims,
full article-text analysis, and a complete national social-media measure are later
work.

The project should eventually support temperature and rainfall anomalies, vegetation,
wildfires, floods, oil and fuel prices, inflation, train disruption, policy events,
elections, COP meetings, product launches, energy shocks and geopolitical events.
Build source and event contracts so these can be added without rewriting the core
attention model.

All topic phrases in the initial configuration are **test definitions**. Record their
language, translation status, notes and configuration version. Do not describe them
as validated classifiers until native-speaker review and precision/recall work has
been completed. Record language gaps, including Welsh and other UK language coverage.

## Data sources: reuse first, add second

The new project must reuse these existing MVP data sources and adapters where they
remain appropriate:

1. **GDELT Web NGrams through BigQuery.** Reuse the UK topic configuration, phrase
   matching, distinct-URL logic, article URL/metadata retention, article evidence,
   political co-occurrence flags, deterministic article samples, scan estimates,
   run manifests and resumable collector. This is the primary news source.
2. **GDELT DOC/timeline API.** Keep the existing collector as a secondary comparison
   and validation path. Do not merge its values with Web NGrams until population,
   scaling and coverage comparability is demonstrated.
3. **GDACS.** Reuse named wildfire/flood events, alert levels, dates, affected
   countries and event geometry as one event source. It is not a complete UK local
   incident register and is not automatically independent of media reporting.
4. **NASA FIRMS.** Reuse active-fire detection and UK country-day aggregation. Keep
   hotspots separate from named events and burned area. Move credentials to T&E-owned
   secrets and preserve source limits and availability metadata.
5. **NASA MODIS MCD64 and MOD13C2.** Reuse burned-area processing and the existing
   monthly UK NDVI anomaly series. The existing frontend already plots NDVI against
   attention. Refresh it for the pilot before the demo.
6. **Experimental Google Trends collector.** Reuse only its request planning,
   pacing and test fixtures for smoke tests. It is not the production search source;
   integrate the official API only after T&E access is granted.
7. **Existing political signal configuration.** Use it as a starting schema for
   article review, alongside an outlet registry. It is derived classification, not
   an independent source and not evidence that an article expresses a particular
   political stance.

The first pilot adds genuinely new source integrations for Bluesky, official Google
Trends, DESNZ fuel prices, ONS, HadUK-Grid, Environment Agency data, rail data, oil
prices, stocks and local disruption measures. Do not pretend these are already
implemented just because an interface exists for them.

### Bluesky first-demo requirement

Bluesky must be available as a demonstrable social-attention line, but define the
measure narrowly and honestly:

- start with a reviewed panel of UK accounts, such as politicians, T&E, relevant
  organisations, journalists and transport/climate commentators;
- store stable account DIDs, handles, category, review status, post URI, timestamp,
  text/available metadata, delete/update status and collection cursor;
- calculate daily topic-matching post counts and the share of all posts from the
  monitored panel mentioning each topic;
- label the result **“posts from monitored Bluesky accounts”**, not “UK social
  attention”;
- use public AppView reads for the first quick demonstration and a filtered Jetstream
  collection for durable refresh/history after the panel is agreed;
- preserve rate-limit, completeness and panel-coverage metadata.

No source subscription should be assumed for public Bluesky reads/streams, but
bandwidth, storage, compute and operational limits still apply. The social line must
remain a separate construct from GDELT news attention and Google search interest.

### MODIS first-demo requirement

Use the existing UK monthly MODIS NDVI anomaly as the physical-context line. It is a
surface greenness/browning measure based on a country-scale 0.05-degree product and
valid cells; it is not literal grass greenness and is not a county-level measure.
Refresh the export and show baseline years, valid-area coverage and monthly timing.
Do not make Sentinel-2 a prerequisite for the first release. Add local aggregation,
quality masking and grassland/cropland masks only as separately validated extensions.

## Architecture constraints

- Keep deployment **non-GCP** for this pilot.
- Use React, TypeScript and Vite for the frontend.
- Deploy the frontend through Netlify.
- Use Supabase/Postgres for prepared serving tables and geographic queries.
- Use Python for collection, validation, analysis and export.
- Use versioned Parquet, cached source responses and run manifests as the research
  archive.
- BigQuery is allowed for GDELT NGrams estimation/collection. Treat GDELT/BigQuery
  as the only planned billable data-analysis source for the first pilot. Free/public
  sources may still have quotas, credentials, infrastructure and staff costs.
- Do not add Cloud Run, Cloud Storage, BigQuery GIS or a GCP-hosted application.
- T&E owns the repository, Netlify site, Supabase project, BigQuery billing project,
  credentials, backup/retention decisions and access approvals.
- A Netlify build must never be treated as a data refresh. Collection, analysis,
  synchronisation, export and publication are separate observable steps.
- Every published release must carry one dataset release ID tying together source
  snapshots, configuration hashes, Parquet outputs, Supabase rows and frontend
  assets.

## Code to port or extract from the MVP

Copy or adapt selected, tested parts of the reference repository before creating
parallel implementations:

- provider interfaces and explicit provider errors;
- retry/backoff, request pacing, bounded windows and failure handling;
- resumable run state and `runs inspect/retry` workflows;
- typed models, configuration validation and configuration hashes;
- manifests, request logs, cached responses and deterministic IDs;
- partitioned Parquet storage and atomic writes;
- source coverage, missingness, unsupported-geography and outage rules;
- country/region boundary indexing and point-in-polygon utilities;
- GDELT, GDACS, FIRMS and MODIS collectors described above;
- Supabase staged upserts, migrations and prepared aggregate access;
- compact frontend export and freshness/source-status metadata;
- frontend timeline, event markers, map layer controls, shareable URL state and
  NDVI overlay patterns;
- Python/frontend tests covering retries, missing days, genuine zeros, unsupported
  markets, duplicates, outages, cross-year windows and export contracts.

Generalise, rather than copy unchanged, the MVP's hard-coded two-topic union,
2025/2026 study files, wildfire/flood labels, `MVP_TOPICS`, Supabase topic checks,
country-only geography and GDELT-only frontend exporter. Do not copy the whole large
old `App.tsx`; split reusable domain logic from presentation as the new UI grows.

## Core data contracts

Define and document versioned schemas for:

- `topic_definition`
- `outlet_registry`
- `account_panel`
- `article_record`
- `article_match_evidence`
- `daily_attention`
- `daily_news_denominator`
- `social_post`
- `search_interest`
- `event_record`
- `physical_observation`
- `run_manifest`
- `dataset_release`

Article records must support URL, canonical URL, publication time, title where
available, outlet/domain, outlet classification, topic and phrase evidence, source,
publishing geography, mentioned geography where available, configuration/classifier
version, collection run and retrieval status. Preserve article URLs for the smaller
UK dataset, subject to source terms and republication policy.

Every record needs source, observed time, collection time, release/version, geography
definition, units, quality/completeness status and provenance. Missing must remain
missing; a provider outage or unsupported geography must never become an observed
zero.

## First reliable vertical slice

Build one end-to-end slice before integrating every planned source:

1. Validate the UK topic configuration and outlet/account panel configuration.
2. Run a small, non-billable or tightly capped GDELT dry run.
3. Produce UK topic counts, article records, and a compatible whole-captured-news
   denominator.
4. Refresh/import the existing UK MODIS NDVI anomaly series.
5. Collect a small Bluesky panel sample and produce a daily topic/share line.
6. Add one existing event layer, initially GDACS/FIRMS wildfire or flood context.
7. Load prepared aggregates into Supabase and export the frontend release assets.
8. Display the three attention/context lines in the timeline with explicit units,
   source labels, freshness, completeness, panel/denominator definitions and release
   ID.

The GDELT numerator must be a share of the same captured article universe as its
denominator. State that it is a share of captured GDELT UK news, not all UK
journalism. For Bluesky, use the monitored-panel denominator. Do not put news,
social posts, search indices and NDVI on one undifferentiated scale.

## Frontend requirements from the updated design and mockup

Use the copied `UK_APP_SCREEN_DESIGN.md` and `UK_APP_SCREEN_MOCKUP.html` as the visual
and interaction starting point.

### Shared application shell

- T&E / UK Attention Atlas identity.
- Primary navigation: Timeline, UK map, Saved views, Data and Methods.
- Dataset freshness, access status, active release ID, date range and configuration
  version visible throughout.
- Save view, share link and export actions.
- URL state must preserve topics, channels, dates, geography, measures, smoothing and
  event overlays.

### Attention timeline

The main screen must support multiple compatible series, including:

- GDELT news share and raw article counts;
- Bluesky monitored-panel post counts/share;
- Google Trends when available;
- MODIS NDVI anomaly;
- fuel/oil prices, weather, disruption and validated event measures as they arrive.

Support left/right axes only for compatible units, warn about misleading dual axes,
offer aligned panels, expose raw units and transformations, and show event markers.
Include date aggregation, smoothing, source/outlet/geography filters, an event filter,
custom reviewed event markers, article drill-down and exportable chart/data metadata.

### UK map

Build the UK map as a second principal workspace. It must support all four nations,
counties and local-authority equivalents as data permits, with selectable attention,
physical and event layers. Keep outlet location, article-mentioned geography, event
location and inferred audience geography distinct. Show unavailable or partial
coverage rather than interpolating it.

### Evidence and methods

Every chart or map selection must expose the formula, source, denominator, dates,
coverage, missingness, release/configuration version and relevant article/event
evidence. The interface must clearly state that associations and timing are
exploratory and do not establish causality.

## Refresh and release operation

Create documented commands for:

- environment setup and secrets;
- configuration and geography validation;
- capped/non-billable dry runs;
- local fixture collection;
- source collection and backfill;
- aggregation and article analysis;
- data-quality/completeness checks;
- Supabase synchronisation;
- frontend export and development;
- production build;
- release verification and rollback.

The repository does not need a production scheduler in the first build. Define clean
command boundaries that a T&E-controlled scheduler can invoke later, with daily,
weekly, monthly and event-driven cadences represented in source metadata. Add alerts
for failed runs, incomplete windows, stale sources, unexpected row counts and schema
changes.

## Testing and validation

Add meaningful tests for:

- configuration and phrase/version loading;
- UK topic and outlet/account panel contracts;
- URL and post deduplication;
- aligned GDELT denominators;
- article availability and conditional article percentages;
- Bluesky cursors, deletes/updates and panel denominators;
- MODIS refresh, anomaly baseline, valid-area metadata and missing months;
- source-specific units and revision status;
- missing dates, genuine zeros, unsupported geographies and outages;
- idempotent/resumable runs and release manifests;
- Supabase payloads and frontend data transformations;
- timeline/map URL state and core mockup interactions.

Validation work must include native-speaker review, topic precision/recall, political
classifier precision/recall, outlet-to-country attribution, denominator audits,
matched-date or untreated-market checks where appropriate, event-source comparison,
multiple-testing decisions and pre-registered primary hypotheses. Do not call a
working chart a validated measurement.

## Initial acceptance criteria

- The new repository contains the two approved planning documents, architecture/data
  notes, updated screen design and web-app mockup.
- A new developer can run the README commands locally.
- A capped UK GDELT run produces article records, daily topic totals and an aligned
  whole-captured-news denominator.
- The configuration contains the four initial topics and explicit test/language
  status.
- The timeline demonstrates GDELT news, monitored-panel Bluesky posts and refreshed
  UK MODIS NDVI, with distinct units and labels.
- Existing GDACS/FIRMS context can be loaded without rebuilding their collectors.
- Prepared aggregates can be loaded into Supabase and exported to the frontend.
- The frontend follows the copied mockup/design sufficiently to support Timeline,
  UK map scaffolding, Data and Methods routes, freshness and release metadata.
- Missing data, denominators, panel coverage, source status and configuration versions
  are visible.
- Tests and production builds pass.
- No credentials, generated research datasets, large caches or unrelated old UI are
  committed.
- The old `Wildfire-Trends` repository remains unchanged.

Do not make official Google Trends access, X, Sentinel-2, every UK flood feed, full
article-text retrieval, predictive modelling or a complete causal design prerequisites
for the first working pilot. Leave documented integration points and a clear source
status for each deferred layer.

When finished, report the files copied/adapted from the MVP, the vertical slice that
works, commands and tests run, dataset/release assumptions, remaining access needs,
and any methodological decisions that require T&E approval.
