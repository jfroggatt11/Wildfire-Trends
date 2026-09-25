# UK, Germany and France data availability review

**Review date:** 24 September 2026  
**Starting point:** the UK pilot plan and the UK data-layer audit in this repository  
**Decision question:** how much of the UK pilot can be reused in Germany and France, and which country is easiest and cheapest to implement?

## Executive assessment

The three-country version is feasible. The lowest-risk design is a shared international backbone plus country adapters:

- **Shared backbone:** GDELT Web NGrams/GAL, Google Trends (subject to alpha access), Bluesky public reads or Jetstream, NASA FIRMS, NASA MODIS/VIIRS, Copernicus Sentinel-2, GDACS and common storage/export code.
- **Country adapters:** gridded or station weather, flood warnings and gauges, rail disruption, fuel prices, inflation, government/parliament records, and administrative geography.
- **Cross-country caveat:** identical APIs do not produce identical measurements. German and French search terms, outlet lists, media density, administrative levels and event taxonomies need country-specific review.

### Provisional rankings

These rankings measure delivery from the **current UK pilot repository**, including the value of existing UK code and configuration. Scores are directional rather than a procurement quote.

| Rank | Country | Mean ease score* | Core recurring data cost | Transferability | Main reason |
| --- | --- | ---: | --- | --- | --- |
| 1 | United Kingdom | **2.27** | Low | Baseline | Existing adapters, configurations and audit already exist; the remaining hard part is completing four-nation flood coverage and the new UK operational feeds. |
| 2 | France | **2.33** | Low | Medium | Vigicrues, SNCF open GTFS/GTFS-RT/SIRI and French open-data portals are relatively unified; Météo-France still needs account setup and a country adapter. |
| 3 | Germany | **2.40** | Low to medium | Medium | DWD and the national flood portal are strong, but rail coverage and historical performance are more access-dependent, and federal-state responsibilities need more reconciliation. |

France and Germany are close. If the product prioritises weather and flood monitoring over rail, Germany can move ahead of France. If it requires a comparable historical rail-performance series, France is the safer second implementation.

\* Mean of the 15 layer scores in the table below; lower is easier. It is a planning score, not a measured delivery time.

### Cost and transferability rankings

- **Core recurring cost:** joint **1st (low)** for the UK, Germany and France. The public data backbone has no expected country-specific subscription fee. Germany moves to **3rd (medium)** only if the product requires a paid or partner-only DB disruption feed rather than the free timetable feed.
- **Source transferability:** **Germany and France joint 1st** because they can share the EU fuel-price and HICP layers as well as the global backbone; **UK 3rd** for those layers because it needs DESNZ and ONS replacements. All three still need national weather, flood, rail, policy and local-geography adapters.

## Scoring method

- **Ease:** 1 = very easy, 2 = easy, 3 = moderate, 4 = hard, 5 = very hard. This combines access, historical coverage, engineering effort and validation burden.
- **Cost:** **Low** means public/free access with normal compute and operations; **Medium** means registration, rate limits or a likely paid/partner option; **High** means a licence, procurement or a bespoke collection workflow is likely.
- **Transferability:** **A** = same provider and interface; **B** = same international family or standard with a country configuration/adapter; **C** = country-specific replacement or manual harmonisation.

The ease score includes the optional retail-price layer, which is currently hard in all three countries. Excluding that layer lowers each mean by about 0.2 points but does not change the order.

## Layer-by-layer review

| Pilot layer | UK | Germany | France | Ease (UK / DE / FR) | Cost | Transferability |
| --- | --- | --- | --- | --- | --- | --- |
| **News attention and article denominator** | GDELT Web NGrams 3.0/GAL via BigQuery; existing UK topic seeds and cost dry-run. | Same GDELT tables; add German phrases, German-language validation and a German outlet registry. | Same GDELT tables; add French phrases, French-language validation and a French outlet registry. | **1 / 2 / 2** | Low | **A** |
| **Search interest** | Google Trends API alpha is the intended production path; UK geo is `GB`. | Same API and `DE` geo; German terms and regional naming need review. | Same API and `FR` geo; French terms, accents and regional naming need review. | **2 / 2 / 2** | Low, but access is gated | **A/B** |
| **Social posting** | Bluesky public AppView/Jetstream can support a reviewed UK account/topic panel. X remains optional and budget-sensitive. | Same global Bluesky/X endpoints, but a German account panel and language rules are needed. | Same global endpoints, but a French account panel and language rules are needed. | **3 / 3 / 3** | Low for Bluesky; medium/high for X | **A** for provider, **B** for country measurement |
| **Weather and climate baseline** | HadUK-Grid: open licence, daily rainfall from 1891 and daily max/min temperature from 1960; revisions and provisional releases need status fields. | DWD open-data daily station observations have historical and recent directories; aggregation to a comparable grid is additional work. | Météo-France climatological data are open/free, but the API uses an account and has a documented 50 requests/minute limit. | **2 / 2 / 3** | Low | **C** with national observations; **A/B** if all three use ERA5-Land |
| **Vegetation / satellite** | Existing NASA MODIS country aggregate; add quality/land-cover decisions before local interpretation. Sentinel-2 is an optional higher-resolution layer. | Same MODIS/VIIRS and Copernicus coverage. | Same MODIS/VIIRS and Copernicus coverage. | **2 / 2 / 2** | Low; Copernicus processing has quotas | **A** |
| **Active-fire detections** | NASA FIRMS free MAP_KEY; existing provider and country polygon workflow. | Same FIRMS API and polygon workflow. | Same FIRMS API and polygon workflow. | **1 / 1 / 1** | Low | **A** |
| **Major hazard events** | GDACS public API; existing event model. | Same GDACS API and event model. | Same GDACS API and event model. | **1 / 1 / 1** | Low | **A** |
| **Flood warnings and gauges** | Environment Agency is easy for England; Scotland, Wales and Northern Ireland require separate feeds before claiming UK-wide coverage. | Länderübergreifendes Hochwasserportal (LHP) provides a free national API for warnings and about 1,200 gauges, with CC BY 4.0 attribution; raw water-level data can still be operator-specific. | Vigicrues provides public observations and warning endpoints; historical data beyond the short live window needs HydroPortail or archived downloads. | **4 / 3 / 2** | Low | **C** |
| **Rail disruption** | National Rail Darwin/HSP is free after Rail Data Marketplace registration; HSP covers up to one year. | DB Timetables has a free plan and current deviations, but richer RIS disruption feeds require approval and may be paid; full all-operator historical coverage is not established. | SNCF publishes open GTFS, GTFS-RT and SIRI Lite feeds; these are strong for current service status, but a UK-style historical performance series still needs a derived archive. | **2 / 4 / 3** | Low for basic feeds; medium/high for richer Germany coverage | **C** |
| **Fuel prices** | DESNZ weekly pump-price CSV (2018 onward). | European Commission Weekly Oil Bulletin (EU country series) is the closest common source. | Same Weekly Oil Bulletin source as Germany. | **2 / 2 / 2** | Low | **B**: same source for DE/FR, national UK replacement |
| **Inflation / household pressure** | ONS CPI/CPIH monthly data. | Eurostat HICP provides harmonised monthly data. | Eurostat HICP provides harmonised monthly data. | **2 / 1 / 1** | Low | **B**: same source for DE/FR, UK replacement; an OECD series could be a common fallback |
| **Government and parliamentary records** | GOV.UK Content API plus UK Parliament APIs; structured and public, but each covers only its own institution. | Bundestag publishes plenary records and documents as XML/JSON; government announcements still need a separate registry. | Assemblée nationale open data covers legislative files, debates and votes; Légifrance API is free after registration for legal records. | **2 / 3 / 3** | Low | **C** |
| **Administrative geography** | ONS geography and versioned local-authority boundaries. | Destatis/BKG boundaries and regional statistics; NUTS is available through Eurostat GISCO. | INSEE COG provides annual commune, department and region codes and history; NUTS is also available through GISCO. | **2 / 2 / 2** | Low | **B**: use GISCO NUTS for a common regional layer; national units remain different |
| **Elections, policy launches and other dated events** | Curated event ledger plus GOV.UK/Parliament identifiers. | Curated ledger plus Bundestag/federal-government identifiers. | Curated ledger plus Assemblée nationale/Légifrance identifiers. | **3 / 3 / 3** | Low | **C** |
| **Retail prices (for example air conditioners)** | No complete free historical retailer series identified in the UK audit. | No comparable free historical series identified; likely retailer/partner work. | No comparable free historical series identified; likely retailer/partner work. | **5 / 5 / 5** | High/unknown | **C** |

## Cost interpretation

### Core pipeline

The largest common variable is the GDELT scan. The UK dry-run scanned 100.472 GB for a seven-day, four-topic batch. At BigQuery's published on-demand price of **US$6.25/TiB**, that is about **US$0.57 per weekly run before the first 1 TiB/month free tier**. Adding Germany and France should be dry-run separately: country filtering does not guarantee a proportional reduction in bytes scanned, and a single batched query may be cheaper than three independent scans.

For the core public sources, the expected country-level recurring vendor cost is therefore **low**. The real cost is engineering and operations: language review, source monitoring, retries, storage, scheduler/hosting, and maintaining country-specific schemas.

### Cost escalators

1. **Google Trends:** access is still an alpha tester programme, so the gating risk is approval and quota rather than a published per-query price.
2. **X:** keep outside the base budget until an account panel, terms review and monthly spending cap are agreed.
3. **Rail:** Germany may become medium/high cost if comparable historical or all-operator disruption data require a commercial DB product; the free DB Timetables feed is narrower.
4. **Retail prices and individual stocks:** treat as procurement/partner work rather than assuming that a free historical series exists.
5. **Satellite processing:** source data are open/free, but repeated Sentinel-2 processing may consume account quotas and cloud/compute budget.

## Transferability summary

### Reuse directly (A)

GDELT, Bluesky, NASA FIRMS, NASA MODIS/VIIRS, Copernicus Sentinel-2 and GDACS use the same provider family across all three countries. The code can usually be reused with country IDs, polygons, language/query configuration and validation samples.

### Reuse through a common standard (B)

Google Trends uses the same API but country-language configurations differ. Fuel prices can use one EU source for Germany and France, while the UK needs DESNZ. Inflation can use one Eurostat HICP source for Germany and France, while the UK needs ONS or a genuinely common international series. GISCO NUTS provides a shared regional layer, but it does not replace national local-authority geography.

### Replace or harmonise nationally (C)

Weather observations, flood monitoring, rail disruption, policy/parliament records, elections/events and administrative local units are not one transferable source. Store a common canonical schema, retain the provider-specific fields, and publish coverage and comparability notes per country.

### Translation and verification

Translating the UK phrase list word for word will miss common local wording and can create false matches. German compounds and inflections, and French synonyms and accented forms, need separate query sets for news, search and social data. A native speaker or subject specialist should review each set, then label samples of matched **and missed** articles in each language to estimate precision and recall. Version the query lists and repeat the check when they change. The UK also needs a Welsh-language coverage check before calling its news measure fully UK-wide. This is a **moderate validation effort** for Germany and France, even though the underlying GDELT and Trends providers are shared.

## Recommended delivery sequence

1. **Build the shared backbone once:** GDELT, Trends access, Bluesky panel format, FIRMS, MODIS/VIIRS, GDACS, provenance and common country polygons.
2. **Add Germany next or France next depending on the product emphasis:** choose France for a faster rail/flood demonstration; choose Germany for weather/flood-first monitoring.
3. **Use one common regional display level first:** NUTS 2 or NUTS 3 across all three countries. Add ONS local authorities, German Kreise and French communes/departments only after the common layer is stable.
4. **Use national weather data only when observation provenance matters:** otherwise ERA5-Land gives one comparable Europe-wide source and removes three separate weather adapters.
5. **Make rail a separate capability:** standardise current service alerts first; do not promise comparable historical delay rates until each country has a verified archive.
6. **Defer retail prices, X and individual stocks:** they drive cost and licensing risk without being necessary to validate the core attention atlas.

## Sources checked

- [GDELT Web NGrams 3.0](https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/)
- [Google Trends API alpha](https://developers.google.com/search/apis/trends)
- [Bluesky API directory and firehose documentation](https://github.com/bluesky-social/bsky-docs/blob/main/docs/advanced-guides/api-directory.mdx)
- [Met Office HadUK-Grid](https://www.metoffice.gov.uk/research/climate/maps-and-data/data/haduk-grid/datasets)
- [DWD daily station observations](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/)
- [Météo-France climatological API listing](https://www.data.gouv.fr/dataservices/api-donnees-climatologiques)
- [Copernicus Sentinel-2 L2A API](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html)
- [NASA FIRMS MAP_KEY and limits](https://firms.modaps.eosdis.nasa.gov/api/map_key/)
- [GDACS API](https://www.gdacs.org/gdacsapi/swagger/index.html)
- [Germany LHP flood API](https://www.hochwasserzentralen.de/developers/api-docs-stable-elements)
- [France Vigicrues API](https://www.vigicrues.gouv.fr/services/v1.1)
- [National Rail Darwin and HSP](https://www.nationalrail.co.uk/developers/darwin-data-feeds/)
- [DB Timetables API](https://developers.deutschebahn.com/db-api-marketplace/apis/product/timetables)
- [SNCF open rail feeds](https://transport.data.gouv.fr/datasets/horaires-sncf)
- [European Commission Weekly Oil Bulletin](https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en)
- [Eurostat HICP](https://ec.europa.eu/eurostat/en/web/hicp)
- [GOV.UK Content API](https://content-api.publishing.service.gov.uk/)
- [German Bundestag open data](https://www.bundestag.de/services/opendata)
- [Assemblée nationale open data](https://data.assemblee-nationale.fr/)
- [INSEE Code officiel géographique](https://www.insee.fr/fr/information/2560452)
- [Eurostat GISCO NUTS](https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics)
- [BigQuery pricing](https://cloud.google.com/bigquery/pricing)
