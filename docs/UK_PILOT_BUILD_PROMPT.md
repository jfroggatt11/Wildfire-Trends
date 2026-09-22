# UK Attention Atlas — Initial Build Prompt

Build the initial version of the UK Attention Atlas in the current repository:

`../Climate_Attention_Atlas_UK`

The repository is currently empty. Set it up as a new, clean implementation owned by T&E.

Before making changes, read the following planning documents as project specifications:

- `/Users/jonahfroggatt/Downloads/UK Attention Atlas - One-Pager.md`
- `/Users/jonahfroggatt/Downloads/UK Attention Atlas — Technical Plan (2).md`

Copy these documents into this repository under `docs/` with clear, permanent filenames.

Use the existing prototype at the following path as a read-only reference:

`../Wildfire-Trends`

Review its architecture briefing, methodology, GDELT collectors, data models, storage layer, Supabase migrations, frontend data loading, configuration system and tests. Reuse sound concepts and selected code where appropriate, but do not copy generated data, credentials, cached responses, historical exports or the entire existing interface. Do not modify the old repository.

The new project is a UK-focused research and monitoring tool that connects attention with events and real-world conditions. Its initial topics are:

- Climate change
- Cost of living
- Clean transport
- Electric vehicles as a separately selectable subtopic

The eventual attention sources are:

- UK news and media coverage
- Google Trends
- Bluesky
- X, where access and budget permit
- Defined panels of politicians and other relevant accounts

The eventual comparison and event sources include:

- Temperature and rainfall anomalies
- Vegetation condition
- Wildfires and flooding
- Oil and petrol prices
- Inflation and household pressures
- Selected share and index prices
- Train delays and cancellations
- Policy announcements
- Elections
- COP meetings
- Product launches
- Energy and geopolitical shocks

The interface will eventually have two principal screens:

1. A UK map with appropriate geography across all four nations, including counties and local-authority equivalents. It should support selectable physical, event and attention layers and clearly distinguish outlet location, article-mentioned places, event location and audience geography.
2. A configurable attention timeline that can compare multiple topics, attention channels, outlet groups, geographic selections, events, prices, disruption and physical measures. It should support event markers, smoothing, lag views, article drill-down, saved specifications and exportable figures and data.

## Architecture constraints

- Keep the application deployment non-GCP.
- Use React, TypeScript and Vite for the frontend.
- Keep the frontend deployable through Netlify.
- Use Supabase/Postgres for prepared serving data and geographic queries.
- Use Python for collection, validation, analysis and export workflows.
- Use versioned Parquet files, cached source responses and run manifests as the research archive.
- BigQuery may be used only as the provider for GDELT NGrams queries and query-cost estimation.
- Do not introduce Cloud Run, Cloud Storage, BigQuery GIS or a GCP-hosted application.
- T&E should own the repository, Netlify site, Supabase project, credentials, billing and retention decisions.
- Do not assume that a Netlify deployment refreshes the data.
- Design collection, analysis, Supabase synchronisation and frontend publication as an explicit, observable release process.
- Every release must identify and validate one dataset version before publishing static assets and Supabase tables.

Build the project incrementally. In this first implementation, complete one reliable vertical slice from news collection to a working attention chart. Do not attempt to integrate every planned source immediately.

## Phase 1 requirements

### 1. Repository foundation

Create a maintainable structure containing:

- `docs/`
- `frontend/`
- `src/climate_attention/`
- `src/climate_attention/sources/`
- `config/`
- `scripts/`
- `supabase/migrations/`
- `tests/`
- `pyproject.toml`
- `README.md`
- `.env.example`
- `.gitignore`
- `netlify.toml`

Use the existing prototype’s Python and frontend tooling where it remains appropriate. Avoid adding frameworks or infrastructure that the pilot does not need.

### 2. Versioned configuration

Create configuration files for:

- UK topics and their phrase definitions
- Political and government signals
- UK outlet metadata
- Geographic definitions
- Source and refresh settings

Topic definitions must be configuration-driven and versioned. Do not hard-code climate change and EV logic into collectors or interface components.

The configuration must support synonyms, exclusions, language, validation status and future topic expansion. Begin with English-language coverage while explicitly recording Welsh-language and other language gaps.

### 3. Core data contracts

Define and document schemas for at least:

- `topic_definition`
- `outlet_registry`
- `article_record`
- `daily_attention`
- `daily_news_denominator`
- `event_record`
- `physical_observation`
- `run_manifest`
- `dataset_release`

Article records should support:

- URL
- Canonical or deduplicated URL
- Publication timestamp
- Title where available
- Outlet/domain
- Outlet classification
- Matched topic
- Matched phrase or topic evidence
- Source
- Source geography
- Mentioned geography where available
- Classifier/configuration version
- Collection run
- Retrieval and availability status

Every collected or derived record should retain sufficient provenance to reproduce it. Preserve missing values as missing rather than turning them into zero.

### 4. UK media collection

Implement a reproducible GDELT Web NGrams/GAL collection path for UK news.

The first pipeline must:

- Collect the configured UK topics.
- Retain matched article URLs and topic evidence.
- Deduplicate URLs within the appropriate topic/day/outlet scope.
- Record the whole identifiable UK article universe for every day.
- Calculate topic counts as a percentage of that same captured universe.
- Ensure numerator and denominator use compatible dates, outlets and coverage.
- Label the result as a share of captured GDELT UK news, not all UK journalism.
- Record query parameters, scan estimates, run times and completeness.
- Support resumable and idempotent runs.
- Detect incomplete dates and failed batches.
- Avoid silently filling missing dates with zero.

Build outlet classification as a reviewed registry rather than inference embedded in the collection query. It should support national, regional and local classifications, coverage areas, ownership, evidence-backed political leaning, effective dates and unknown/mixed values. Political leaning is an outlet attribute and should not be presented as the stance of every article.

### 5. Article analysis foundation

Design the data model so later analysis can calculate measures such as:

- Percentage of all captured UK news that discusses a selected topic.
- Percentage of wildfire articles that mention climate change.
- Percentage of fuel-price articles that mention electric vehicles.
- Breakdowns by national, regional and local outlets.
- Breakdowns by reviewed outlet political classification.

Do not classify an unavailable article as a negative match. Full-text collection must remain a separate permitted-access workflow. Record syndication and duplicates explicitly.

### 6. Supabase serving layer

Create migrations for the initial serving tables and appropriate indexes.

Keep research records and serving aggregates distinct. Supabase should serve validated, prepared data rather than becoming the only research archive.

Add restrictive row-level security and document how public/browser-safe access differs from administrative credentials. Never commit secrets or database connection strings.

### 7. Initial frontend

Create a functional React/TypeScript/Vite frontend with:

- A simple project shell.
- An attention timeline.
- Topic selection.
- Date-range selection.
- Raw article counts.
- Total UK denominator counts.
- Topic share of captured UK news.
- Source/outlet filters supported by the initial data.
- Clear missing-data and freshness indicators.
- Article drill-down for a selected date or point.
- Visible dataset and configuration version information.

Use fixture data initially where it allows frontend work to proceed, but connect the final Phase 1 chart to the prepared serving schema. The interface must not imply causal conclusions.

Prepare routing and component boundaries for the later UK map, Google Trends, social attention, events and physical overlays, but do not build placeholder complexity that Phase 1 does not need.

### 8. Release and operation

Create documented commands for:

- Environment setup.
- Configuration validation.
- A small non-billable or tightly capped collection dry run.
- A local fixture run.
- Collection.
- Aggregation.
- Data validation.
- Supabase synchronisation.
- Frontend development.
- Production build.
- Release verification.

Add run manifests, freshness checks, completeness checks, retry boundaries and scan-budget caps.

The repository does not currently have a production scheduler. Define a clean command boundary that a T&E-controlled managed runner can invoke later without changing the pipeline. Do not select or provision GCP scheduling infrastructure.

### 9. Testing

Add meaningful tests for:

- Topic configuration loading.
- URL deduplication.
- Numerator and denominator alignment.
- Whole-UK denominator calculation.
- Article availability handling.
- Missing dates.
- Outlet classifications with effective dates.
- Dataset and classifier versions.
- Resumable/idempotent runs.
- Supabase payload generation.
- Frontend data transformations.

Do not create tests that merely repeat implementation details.

## Phase 1 acceptance criteria

- A new developer can follow the README and run the project locally.
- The repository contains the two approved planning documents.
- Topics and outlet metadata are configuration-driven.
- A small UK GDELT run can produce article records, daily topic totals and daily whole-UK denominators.
- Topic share is calculated from aligned numerator and denominator populations.
- The run records provenance, completeness and dataset versions.
- Prepared aggregates can be loaded into Supabase.
- The frontend displays a working attention timeline and article drill-down.
- Missing data, freshness and denominator definitions are visible.
- Tests and production builds pass.
- No secrets, generated research datasets or large caches are committed.
- The existing `Wildfire-Trends` repository remains unchanged.

Do not implement Google Trends, Bluesky, X, predictive modelling, causal claims or the complete UK map during this first phase. Document their integration points and leave the architecture ready for them.

Work autonomously through the implementation until the Phase 1 foundation is complete. Start by inspecting the specifications and reference repository, then write a concise implementation plan in the new repository. Make the implementation, run the appropriate tests and builds, and finish by reporting what was built, how it was validated, and which external credentials or access decisions remain.
