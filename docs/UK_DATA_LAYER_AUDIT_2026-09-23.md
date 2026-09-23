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

Bluesky is technically accessible now, but the project needs a defined UK account or topic panel. X is optional and budget-sensitive.

## Layer audit

| Layer | Access and coverage | MVP reuse | Assessment and first action |
| --- | --- | --- | --- |
| GDELT Web NGrams / GAL | Public dataset and BigQuery access. Web NGrams 3.0 links matched n-grams to article URLs and has a backfile from 2020. | High. Existing source adapter handles phrases, distinct URLs, political signals and scan estimates. | Core media layer. Extend it for UK article metadata, outlet registry and an aligned whole-UK denominator. |
| GDELT DOC API | Public API. | High. Existing alternative provider. | Keep for validation and small queries; do not make it the denominator without proving population compatibility. |
| Google Trends | Official API is an alpha with limited tester access. Google describes five years of rolling data, daily to yearly aggregation, subregions and consistently scaled values. | Medium. Existing unofficial collector is not suitable as the production path. | Apply under T&E. Test quotas, UK subregions, language, query choices and backfill completeness before integration. |
| Bluesky | Public AppView reads and public firehose/Jetstream. Full firehose is large; Jetstream provides filtered JSON and replay. | Low. No MVP collector. | Start with a reviewed account/topic panel. English text does not establish UK residence. Add durable cursors and post/engagement records. |
| X | Official API supports post search, full archive, filtered stream and user endpoints. Current access is pay-per-use; published rates include $0.005 per post read and a 3 million post-read monthly cap on the standard plan. | Low. No MVP collector. | Optional. Create a T&E account only after defining an account panel, terms review and monthly spending cap. |
| HadUK-Grid | Open Government Licence. Daily rainfall begins in 1891; daily maximum/minimum temperature begins in 1960. Annual releases are revised and provisional monthly data arrive after month-end. | Low to medium. Existing satellite patterns are reusable; no HadUK adapter. | Best historical baseline for local anomalies. Add a NetCDF adapter and clear provisional/revised status. |
| Current weather observations | Needs a separate operational feed. | Low. Not in MVP. | Compare a timely Met Office product with HadUK latency before building. Keep source and revision fields separate. |
| Environment Agency floods | Public, no registration, Open Government Licence. Near-real-time warnings, alerts, levels and flows; readings are often measured every 15 minutes but transferred at varying frequencies. | Low. New UK observation layer. | Build England first. Audit equivalent feeds for Scotland, Wales and Northern Ireland before showing a UK-wide measure. |
| Sentinel-2 | Copernicus products are free. Data Space APIs provide catalogue and processing access; repeat processing needs an account and quota. European Level-2A coverage starts in 2015. | Low to medium. MVP satellite module is mainly MODIS/AppEEARS. | Good local greenness layer, but requires cloud/quality masking and land-cover decisions. Test one UK region first. |
| GDACS | Public event API and catalogue. | High. Existing provider and event model. | Retain for international context, with explicit source and severity vocabulary. Do not equate its severity with local observations. |
| NASA FIRMS | Public API with a free MAP_KEY, rate and transaction limits, and separate near-real-time, standard and historical products. | High. Existing provider. | Ready for UK hotspot context. Move the key to T&E secrets and add availability checks. |
| MODIS burned area / NDVI | Public NASA/Earthdata products; some AppEEARS workflows require credentials. | High. Existing satellite workflow. | Reuse for broad physical context. Keep burned area, NDVI and FIRMS detections distinct. |
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
5. Define a Bluesky account/topic panel and test Jetstream cursors.

## Defer

- X until a monthly budget, account panel and terms review exist.
- Retail air-conditioner prices without a named historical provider.
- Individual UK stock prices without a licence and instrument list.
- A single UK flood or train-disruption number before four-nation coverage is measured.
- Predictive modelling before history, classifiers and denominators are validated.

## MVP reuse

Reuse the MVP’s provider interfaces, explicit provider errors, resumable run state, request manifests, GDELT phrase catalogues, URL deduplication, GDACS/FIRMS event models, Parquet provenance, Supabase batch sync, frontend freshness states and tests for outages and incomplete windows.

Add new adapters and schemas for article URL/title/outlet retention, whole-UK denominators, outlet classification, physical/economic observations, UK geography, dated policy/election/product/geopolitical events, social posts and search-interest series.

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
- [Bluesky Jetstream](https://github.com/bluesky-social/jetstream-legacy)
- [X API introduction](https://docs.x.com/x-api/introduction) and [pricing](https://docs.x.com/x-api/getting-started/pricing)
- [HadUK-Grid overview](https://www.metoffice.gov.uk/research/climate/maps-and-data/data/haduk-grid/overview) and [datasets](https://www.metoffice.gov.uk/research/climate/maps-and-data/data/haduk-grid/datasets)
- [Copernicus Sentinel-2](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-2) and [APIs](https://documentation.dataspace.copernicus.eu/APIs.html)
- [Environment Agency flood-monitoring API](https://environment.data.gov.uk/flood-monitoring/doc/reference)
- [NASA FIRMS API](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html)
- [DESNZ weekly road-fuel prices](https://www.gov.uk/government/statistics/weekly-road-fuel-prices)
- [ONS developer API](https://developer.ons.gov.uk/)
- [National Rail Darwin feeds](https://www.nationalrail.co.uk/developers/darwin-data-feeds/)
- [GOV.UK Content API](https://content-api.publishing.service.gov.uk/)
- [UK Parliament developer hub](https://developer.parliament.uk/)
- [UCDP download centre](https://ucdp.uu.se/downloads/)
- [ACLED API access](https://acleddata.com/api-documentation/getting-started)
