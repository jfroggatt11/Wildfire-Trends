# UK Attention Atlas data-layer audit

Reviewed: 23 September 2026

This audit records which proposed layers are public, reusable from the MVP, suitable for the UK pilot, and ready to set up. Public access may still involve registration, quotas, attribution, licensing, geography or historical-coverage limits.

## Summary

The most useful low-friction additions are DESNZ weekly fuel prices, ONS inflation, Met Office HadUK-Grid weather, Environment Agency flood data for England, GOV.UK and Parliament policy records, and the GDELT whole-UK denominator.

The next access applications should be made under T&E ownership:

- Google Trends API alpha
- National Rail Darwin and Historic Service Performance
- NASA FIRMS and Earthdata credentials
- Copernicus Data Space Ecosystem access for Sentinel-2

Bluesky is technically accessible without a source-data subscription and should be in the first demo as a **separately labelled social-posting line**. Define a reviewed UK account panel first; do not present its posts as a representative measure of all UK social conversation. X is optional and budget-sensitive.

## Layer audit

| Layer | Access and coverage | MVP reuse | Assessment and first action |
| --- | --- | --- | --- |
| GDELT Web NGrams / GAL | Public dataset and BigQuery access. Web NGrams 3.0 links matched n-grams to article URLs and has a backfile from 2020. | High. Existing source adapter handles phrases, distinct URLs, political signals and scan estimates. | Core media layer. Extend it for UK article metadata, outlet registry and an aligned whole-UK denominator. |
| GDELT DOC API | Public API. | High. Existing alternative provider. | Keep for validation and small queries; do not make it the denominator without proving population compatibility. |
| Google Trends | Official API is an alpha with limited tester access. Google describes five years of rolling data, daily to yearly aggregation, subregions and consistently scaled values. | Medium. Existing unofficial collector is not suitable as the production path. | Apply under T&E. Test quotas, UK subregions, language, query choices and backfill completeness before integration. |
| Bluesky | Public AppView reads and public firehose/Jetstream, with no published source-access fee for these public endpoints; rate limits and self-hosting/compute costs still apply. Jetstream v2 documents historical replay, subject to checking the available hosted service and archive window. | Low. No MVP collector. | Put a daily topic-post count and share of all posts from a reviewed UK account panel in the demo. Preserve account categories, stable DIDs, post URIs, deletes/updates and refresh cursors. Label panel coverage; English text does not establish UK residence. |
| X | Official API supports post search, full archive, filtered stream and user endpoints. Current access is pay-per-use; published rates include $0.005 per post read and a 3 million post-read monthly cap on the standard plan. | Low. No MVP collector. | Optional. Create a T&E account only after defining an account panel, terms review and monthly spending cap. |
| HadUK-Grid | Open Government Licence. Daily rainfall begins in 1891; daily maximum/minimum temperature begins in 1960. Annual releases are revised and provisional monthly data arrive after month-end. | Low to medium. Existing satellite patterns are reusable; no HadUK adapter. | Best historical baseline for local anomalies. Add a NetCDF adapter and clear provisional/revised status. |
| Current weather observations | Needs a separate operational feed. | Low. Not in MVP. | Compare a timely Met Office product with HadUK latency before building. Keep source and revision fields separate. |
| Environment Agency floods | Public, no registration, Open Government Licence. Near-real-time warnings, alerts, levels and flows; readings are often measured every 15 minutes but transferred at varying frequencies. | Low. New UK observation layer. | Build England first. Audit equivalent feeds for Scotland, Wales and Northern Ireland before showing a UK-wide measure. |
| Sentinel-2 | Copernicus products are free. Data Space APIs provide catalogue and processing access; repeat processing needs an account and quota. European Level-2A coverage starts in 2015. | Low to medium. MVP satellite module is mainly MODIS/AppEEARS. | Good local greenness layer, but requires cloud/quality masking and land-cover decisions. Test one UK region first. |
| GDACS | Public event API and catalogue. | High. Existing provider and event model. | Retain for international context, with explicit source and severity vocabulary. Do not equate its severity with local observations. |
| NASA FIRMS | Public API with a free MAP_KEY, rate and transaction limits, and separate near-real-time, standard and historical products. | High. Existing provider. | Ready for UK hotspot context. Move the key to T&E secrets and add availability checks. |
| MODIS burned area / NDVI | Public NASA/Earthdata products; some AppEEARS workflows require credentials. | **High. Existing collector, UK observations, export and timeline overlay.** | Reuse monthly UK NDVI anomaly immediately. The current 0.05-degree country aggregate covers all valid vegetation, not grass specifically; re-aggregate and validate before presenting county-level values. Keep burned area, NDVI and FIRMS detections distinct. |
| DESNZ road-fuel prices | Official weekly UK pump-price statistics with a CSV history currently covering 2018 onward. | Low. No adapter. | Immediate priority for the EV/fuel question. Add a provenance-aware weekly adapter. |
| ONS CPI and household pressure | Open ONS API with no key. CPI/CPIH are monthly UK official statistics; detailed research data have revision and confidentiality constraints. | Low. No adapter. | Select a short, pre-registered set of measures and record release dates and revisions. |
| Brent/oil prices | EIA series are public through an API with key registration; commercial alternatives have separate licences. | Low. No adapter. | Define benchmark, timezone, frequency and level/return/threshold measure. Test a US$100 event only after pre-specifying windows. |
| Stock and index prices | Free UK equity histories are fragmented and often restricted for redistribution. | Low. No adapter. | Defer individual stocks until T&E chooses a licensed feed. Broad indices are easier. |
| Air-conditioner interest and prices | Search interest can use Trends after access. A complete free historical retail-price series has not been identified. | Low. No adapter. | Add search terms to the Trends application. Treat retail prices as a separate partner/procurement task. |
| National Rail Darwin / HSP | Official GB train-running feeds require Rail Data Marketplace registration. HSP provides historic performance for up to one year; feeds are free within stated terms and usage conditions. | Low. No adapter. | Strong England, Scotland and Wales disruption layer. Register under T&E and define route, cancellation and delay measures. |
| GOV.UK policy records | Public Content API, no authentication, structured page metadata, documented 10 requests/second client limit. It covers GOV.UK HTML content, not every search result or attachment. | Low. No adapter. | Add a watched organisation/document registry with canonical path and publication/update timestamps. |
| UK Parliament | Public APIs cover bills, stages, publications, members and votes. | Low. No adapter. | Add bill-stage and sitting event types. Check each record before treating it as an implementation date. |
| Elections | Public results exist, but one stable UK-wide API and comparable geography still need selection. | Low. No adapter. | Start with a sourced event registry and versioned geography. |
| COP and meetings | Official calendars exist, but no single stable feed covers every meeting and announcement. | Low. No adapter. | Use a small curated event table with source, dates, location and relevance. |
| Geopolitical events | UCDP provides free CC BY 4.0 datasets and API access, including georeferenced violence and monthly candidate releases. ACLED provides richer data after registration and under access/licensing terms. | Low. No adapter. | Use UCDP for historical context and a reviewed energy/geopolitical event ledger. Do not use GDELT-derived event labels as independent outcomes. |

## Start now

1. Freeze UK topics, phrase lists, language status and validation plan.
2. Extend GDELT NGrams/GAL for article records and an aligned whole-UK denominator.
3. Add DESNZ weekly fuel prices.
4. Add ONS monthly CPI and household-pressure measures.
5. Add HadUK-Grid daily rainfall and temperature anomalies.
6. Add the England Environment Agency adapter with explicit England-only coverage.
7. Add GOV.UK and Parliament event tables.
8. Build the reviewed outlet registry, including national/regional/local scope and unknown/mixed political classification.

## Access and account work

1. Apply for Google Trends under T&E.
2. Register for National Rail HSP and Darwin.
3. Move FIRMS and Earthdata credentials to T&E-owned secrets.
4. Create a Copernicus Data Space account and test one Sentinel-2 request.
5. Define a Bluesky UK account/topic panel; test public AppView reads for a quick demonstration and Jetstream v2 replay/cursors for reliable refresh.

## Defer

- X until a monthly budget, account panel and terms review exist.
- Retail air-conditioner prices without a named historical provider.
- Individual UK stock prices without a licence and instrument list.
- A single UK flood or train-disruption number before four-nation coverage is measured.
- Predictive modelling before history, classifiers and denominators are validated.

## MVP reuse

Reuse the MVP’s provider interfaces, explicit provider errors, resumable run state, request manifests, GDELT phrase catalogues, URL deduplication, GDACS/FIRMS event models, **monthly MODIS NDVI collector and UK anomaly export**, Parquet provenance, Supabase batch sync, frontend freshness states and tests for outages and incomplete windows. The exported UK NDVI series currently has 19 monthly observations from January 2025 through July 2026; refresh it before a live demo. The existing frontend already plots NDVI anomalies against attention.

Add new adapters and schemas for article URL/title/outlet retention, whole-UK denominators, outlet classification, physical/economic observations, UK geography, dated policy/election/product/geopolitical events, social posts and search-interest series.

## Existing MVP data sources that can seed the UK pilot

| Existing source | What is already usable for the UK | What still needs doing |
| --- | --- | --- |
| GDELT Web NGrams through BigQuery | UK topic counts, original-language phrase matching, distinct URLs, optional article metadata/URLs, whole-news coverage queries, political co-occurrence flags and deterministic article samples. `config/topics.uk-pilot.yaml` already contains seed phrases for climate change, cost of living, clean transport and EVs. | T&E phrase review, article-level denominator design, source/outlet registry, UK local attribution and precision/recall validation. The phrases remain test definitions. |
| GDELT DOC/timeline API | A secondary attention series and source-comparison path already exists. | Keep it as validation until its population, scaling and coverage are shown comparable to Web NGrams; do not silently merge the two measures. |
| GDACS | Existing named wildfire and flood event catalogue, alert levels, dates, affected-country fields and event geometry. | Extend beyond those hazards and do not treat GDACS as a complete UK incident register or an independent measure of all local events. |
| NASA FIRMS | Existing active-fire detections and UK country-day aggregation. | Keep the T&E-owned MAP_KEY, validate UK detection completeness, and distinguish hotspots from named events and burned area. |
| NASA MODIS MCD64/MOD13 | Existing burned-area processing and monthly MODIS NDVI anomaly series, including UK observations and frontend export. | Refresh the UK series; add quality masking, local geography and clear surface-greenness wording. |
| Unofficial Google Trends collector | A tested experimental collector and request pacing/retry behaviour. | It is not a production source. Use only for a smoke test until official T&E API access is granted. |
| Phrase-based political signals | Existing UK seed signals and official-domain list can be applied to retained GDELT article records. | This is derived classification, not an independent data source. Build and review a UK outlet taxonomy and measure classifier accuracy. |

The MVP therefore already covers the first UK media line, a physical greenness line, wildfire context, flood/wildfire event context and a provisional article-review path. DESNZ prices, ONS, HadUK-Grid, Environment Agency, rail, oil, Bluesky and official Google Trends would be genuinely new source integrations rather than ports of existing collectors.

## Additional MVP assets to reuse

The new pilot should fork or extract these working pieces before writing parallel infrastructure:

- **Collection runtime:** the Python CLI, provider interface, explicit provider errors, HTTP retry/backoff handling, rate-limit recovery, bounded request windows, saturated-window splitting, resumable checkpoints and `runs inspect/retry` commands. These are useful for GDELT, Bluesky, official APIs and physical feeds alike.
- **Provenance and reproducibility:** frozen YAML snapshots, configuration hashes, request logs, run manifests, software/version metadata, cached API responses and deterministic record IDs. Extend the manifest with source release/version and schema version for every new adapter.
- **Storage pattern:** typed Pydantic models, partitioned local Parquet, atomic replacement, source-specific observation tables, raw response retention and metadata columns. This is a good research archive pattern; it is not a substitute for managed backups or concurrent-job locking.
- **Coverage and missingness rules:** explicit distinction between a measured zero, an absent day, an unsupported geography and a confirmed provider outage; contiguous observed-date ranges; completeness checks; and source-quality metadata. These rules should become a shared UK data-quality contract.
- **Geography utilities:** country and region boundary indexes, point-in-polygon assignment, ISO mappings and Natural Earth reference assets. Reuse the spatial pattern, but add official UK counties/local authorities and keep outlet location, article-mentioned location, event location and audience geography as separate fields.
- **Analysis functions:** event-window construction, cross-year windows, overlap detection, rolling summaries, complete-panel checks, political-share aggregation and lead/lag scaffolding. Reuse the mechanics, but carry the MVP's known corrections forward: use descriptive language, retain sample sizes, pre-specify lags, and do not present exploratory correlations or percentage changes as causal estimates.
- **Serving path:** the staged Supabase upserts, derived warehouse tables, read-only browser access, static JSON/GeoJSON exports and release manifest. This lets the pilot keep the current non-GCP deployment while adding UK tables. A single release ID should eventually link the Parquet snapshot, Supabase rows and frontend assets.
- **Frontend patterns:** the attention timeline, event markers, map layer controls, date-range state, URL-shareable selections, freshness/source-status display, compact browser exports and unit/e2e test structure. The NDVI overlay and its explanatory text are already directly reusable.
- **Validation and operations:** the existing Python/frontend test fixtures for retries, missing dates, unsupported markets, genuine zeros, duplicates, outage handling, cross-year windows and export contents; the operations guide; and the architecture/data dictionary. Extend these tests for each new source instead of testing only successful responses.

Do not copy the MVP's assumptions unchanged. The following are currently hard-coded or scope-specific and must be generalised: the two-topic union (`climate_change` and `electric_vehicles`), 2025/2026 study files, wildfire/flood hazard labels, the Supabase topic check constraints, the global map's country-only geography, `MVP_TOPICS` in the sync code, and the exporter’s GDELT-only attention source. The large `App.tsx` and exporter also contain useful logic but should be split around reusable domain modules before adding many UK layers. The architecture briefing records additional open issues around atomic dataset releases, backup/recovery, article rights, classifier validation and prediction leakage.

## Design decisions

- GDELT measures published media attention, Google Trends measures search interest and social sources measure posting activity. Keep these constructs separate.
- Use source-specific observation tables with frequency and release metadata. Do not force daily resolution onto monthly CPI or provisional weather.
- Keep event location, article-mentioned geography, outlet location and inferred audience geography separate.
- Show source availability, completeness and revision status in the data model and interface.
- Make T&E-owned access and credentials prerequisites for production refreshes.
- Start with sources that have clear public terms and useful history; add account-gated or licensed sources after the core release path is reliable.

## Official references

- [GDELT Web NGrams 3.0](https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/)
- [Google Trends API alpha](https://developers.google.com/search/apis/trends)
- [Bluesky relay and firehose](https://bsky.network/docs/relay/)
- [Bluesky Jetstream v2](https://github.com/bluesky-social/jetstream/blob/main/docs/README.md) and [public AppView API](https://docs.bsky.app/docs/api/app-bsky-feed-get-feed)
- [X API introduction](https://docs.x.com/x-api/introduction) and [pricing](https://docs.x.com/x-api/getting-started/pricing)
- [HadUK-Grid overview](https://www.metoffice.gov.uk/research/climate/maps-and-data/data/haduk-grid/overview) and [datasets](https://www.metoffice.gov.uk/research/climate/maps-and-data/data/haduk-grid/datasets)
- [Copernicus Sentinel-2](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-2) and [APIs](https://documentation.dataspace.copernicus.eu/APIs.html)
- [Environment Agency flood-monitoring API](https://environment.data.gov.uk/flood-monitoring/doc/reference)
- [NASA FIRMS API](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html)
- [DESNZ weekly road-fuel prices](https://www.gov.uk/government/statistics/weekly-road-fuel-prices)
- [ONS developer API](https://developer.ons.gov.uk/)
- [EIA free API key and documentation](https://www.eia.gov/opendata/documentation.php)
- [National Rail Darwin feeds](https://www.nationalrail.co.uk/developers/darwin-data-feeds/)
- [GOV.UK Content API](https://content-api.publishing.service.gov.uk/)
- [UK Parliament developer hub](https://developer.parliament.uk/)
- [UCDP download centre](https://ucdp.uu.se/downloads/)
- [ACLED API access](https://acleddata.com/api-documentation/getting-started)

## GDELT as the only paid data source: Codex-assisted build estimate

The earlier 50–93-day estimate assumed a conventional one-developer implementation and understated reuse of the existing greenness work. The revised ranges below are **focused working days for one person using Codex** to inspect the MVP, implement adapters and tests, and review outputs. They are planning ranges, not a claim that AI reduces every task by a fixed factor. Each includes an initial usable backfill, idempotent refresh, basic failures/completeness checks and a prepared output. Human source access, topic/outlet judgements, independent measurement validation, substantive UI/map work and ongoing operations are separate. Codex can accelerate code and test creation; it cannot establish whether an outlet is politically left/right, whether a UK account panel is representative, or whether two sources measure comparable populations.

“Free” means no planned source-data subscription within published terms. Netlify, Supabase, a job runner, storage, network traffic and staff time may still cost money. GDELT itself is open; BigQuery scans and related cloud usage are the paid component. The [September dry run](UK_PILOT_QUERY_COST_ESTIMATE.md) estimated about US$0.57 per seven-day query before the shared BigQuery free tier for one tested query shape. Backfills and revised query shapes need new dry runs.

| Pipeline or shared work | Codex-assisted effort | Refresh and main constraint |
| --- | ---: | --- |
| Shared run framework: schedule, manifests, retries, freshness, completeness alerts, secrets and releases | **3–6 days** | Check daily; build once across sources. |
| GDELT UK topic URLs, metadata and aligned whole-UK denominator | **4–8 days** | Daily/weekly; denominator and URL deduplication require measurement review. |
| UK outlet registry and versioned national/local/leaning attributes | **2–4 days coding**, plus T&E editorial review | Monthly; labels need a transparent, reviewed rubric. |
| DESNZ national fuel prices | **1–2 days** | Weekly after publication; UK only. |
| ONS CPI/CPIH and selected household measures | **1–2 days** | Monthly; retain release/revision metadata. |
| EIA Brent benchmark | **1–2 days** | Daily/weekly; specify series, units and threshold timing. |
| HadUK-Grid temperature/rainfall and local anomalies | **3–6 days** | Monthly provisional and annual revised; geography/baseline QA. |
| Environment Agency flood warnings/levels | **2–4 days** | Daily or faster; England-only coverage. |
| GDACS/FIRMS UK events and detections, adapted from MVP | **1–2 days** | Daily; keep events and hotspots distinct. |
| **Existing MODIS UK NDVI anomaly reuse** | **1–3 days** for new-pilot import and scheduled refresh | Monthly; UK series and chart already exist in MVP. County aggregation/validation is additional work. |
| GOV.UK/Parliament watched events | **2–4 days** | Daily/weekly; publication and effective dates differ. |
| Curated elections, COP, launches and geopolitical ledger | **1–2 days coding**, then editorial work | Update as needed with provenance. |
| **Bluesky reviewed UK account panel and daily topic/share line** | **2–5 days** for a demo-to-refresh pipeline | Daily AppView collection can start quickly; robust history, account/deletion handling and Jetstream replay need validation. No source subscription planned. |
| UCDP historical conflict events | **2–3 days** | Monthly/annual; add only for a defined hypothesis. |
| Google Trends official API | **2–5 days after access** | Daily/weekly; T&E application and comparability checks are gating. |
| National Rail Darwin/HSP selected routes | **4–8 days after registration** | Daily; incident causation is not in the delay data alone. |
| Sentinel-2 local greenness, one region | **6–12 days** | Cloud and land-cover masking dominate; optional, as UK NDVI already exists. |
| Scotland/Wales/Northern Ireland flood harmonisation | **4–8 additional days**, provisional | Definitions and backfill vary by nation. |

**Recommended demo slice:** GDELT topic and whole-news lines, an explicitly defined Bluesky panel topic/share line, the existing UK monthly MODIS NDVI anomaly, DESNZ fuel prices and a small event ledger, all on the attention chart. Allow roughly **13–28 focused Codex-assisted days**, including 2–4 days of chart integration, before T&E editorial and research review. A quick static Bluesky prototype may be faster; it should not be represented as a complete, automatically refreshed historical series. Label the social line as “posts from monitored Bluesky accounts,” with a panel denominator, not as “UK social attention.”

**Broader initial release:** Add the outlet registry, ONS, Brent, HadUK-Grid, England floods, GDACS/FIRMS and GOV.UK/Parliament. The underlying pipelines and shared framework are roughly **23–50 focused days** in total including the demo sources, before significant map/UI work and independent validation. Work can overlap, but source publication delays and manual review may control elapsed time. Google Trends, rail and local Sentinel-2 remain access- or research-dependent extensions rather than prerequisites for showing social and greenness lines.

These ranges assume that the new repository ports the reusable MVP runtime, models, storage, tests and frontend patterns. Starting from the empty UK repository adds roughly **4–8 focused days** for extraction, dependency cleanup, contract changes and regression repair; rebuilding the platform as greenfield work would add materially more. The saving comes from reusing tested machinery, not from treating the MVP's topic, event or database assumptions as ready-made UK answers.

**Outside the free-source plan:** X's pay-per-use API, licensed stock data, retail air-conditioner price histories and any paid operational weather/rail feeds. Public availability does not imply unrestricted republication of article/post text or a complete historical archive.
