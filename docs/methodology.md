# Methodology

> **Current MVP methodology (10 September 2026):** the public analysis uses
> GDELT Web NGrams distinct-URL counts. DOC API shares described below are an
> alternative collection/validation path. Explicitly unsupported country mappings
> are unavailable, and affected-market estimates require every affected country.
> Windows can cross calendar years. Overlap exclusion checks Orange/Red floods and
> wildfires across all years, independently of the displayed cohort. Single-event
> cards now report descriptive changes without statistical significance verdicts.
> See [the first improvement batch](IMPROVEMENTS_PHASE1.md) for corrected results,
> regression coverage and coordinated serving-data refresh instructions.


## Current measurement and serving paths

The MVP outcome is Web NGrams distinct matched URLs per topic, publishing-outlet
country and UTC day. Country news denominators are optional and not validated for
routine use. DOC API shares below describe an alternative collector, not the
current analysis outcome. Google Trends remains experimental.

Python computes the event-study exports from local Parquet. The browser combines
static major-event studies with Supabase daily attention and all-alert aggregates.
Supabase is required for the full current interface. Before/after changes and
lead/lag correlations are descriptive; the interface does not report permutation
p-values or statistical significance verdicts. See the
[architecture briefing](ARCHITECTURE_BRIEFING_2026-09-15.md) for operational limits.

## Test topics, translation, and verification

Climate change and electric vehicles are the prototype's two test topics. Their
phrases demonstrate the collection and comparison workflow; they are not final,
validated definitions of T&E's research interests. New topics require an agreed
conceptual definition, relevant markets, and reviewed language-specific expressions.

The current Web NGrams pipeline matches original-language article text against
preconfigured phrases in `config/topics.multilingual.example.yaml`. It does not
translate articles or generate new translations during collection. The seed covers
English, Spanish, Portuguese, French, German, Italian, Russian, Arabic, Chinese, and
Japanese. For example, the climate topic includes English “climate change”, French
“changement climatique”, and German “Klimawandel”. The alternative DOC API searches
English expressions over GDELT's machine-translated coverage; this is a different
measurement path, not a translation step applied to NGrams.

Phrase records specify language, segmentation, and `draft`/`validated` status.
Non-English seed entries are drafts; the collector can use draft phrases, so this
status is an audit label rather than an enforced quality gate. English entries are
marked validated in the configuration, but this does not establish measured
precision or recall. Literal matching does not automatically recover unlisted
synonyms, inflections, abbreviations, or local usage. Chinese and Japanese use
character-based context matching. Ambiguity, mixed-language articles, and uneven
outlet coverage can also affect comparisons between languages and countries.

The following verification protocol is proposed, not a completed validation result:

1. **Review the definition and phrase lists.** T&E and native speakers agree what
   counts as relevant, inspect local terminology and exclusions, and document
   ambiguous cases. Record the reviewer, date, and rationale for each revision.
2. **Measure precision.** Draw reproducible samples of matched articles across
   topics, priority languages, markets, ordinary dates, and attention spikes.
   Reviewers inspect retained phrase context and the article where available, and
   label topic relevance and political signals separately. Precision is the
   proportion of classified positives that reviewers judge relevant.
3. **Measure recall independently.** Review a separate sample of indexed coverage
   drawn without requiring a topic match, including unmatched articles. Recall is
   the proportion of all reviewer-identified relevant articles in that sample that
   the classifier finds. A matched-only sample cannot estimate recall; report sample
   sizes and uncertainty, and do not infer reliable recall from too few relevant
   examples. Any enriched sampling needs documented selection and weighting.
4. **Resolve disagreements and retest.** Have two reviewers independently label a
   shared subset, record agreement, and adjudicate differences. Revise the lists
   using a development sample and assess accuracy on a separate held-out sample.
   Report results by topic and language/market, with explicit gaps where no suitable
   reviewer or enough evidence is available. Unreviewable articles remain unknown.
5. **Check attribution and stability.** Audit outlet-country mappings, duplicate
   handling, per-language coverage, and false positives/negatives for political
   signals. Agree acceptance criteria before confirmatory analysis, freeze the
   approved taxonomy, and recollect affected periods consistently after changes.
   Periodic spot checks should detect terminology and source-coverage drift.

## GDELT DOC API alternative: unit of observation

The DOC API observation is one UTC day, conceptual topic, publishing outlet source
country, and optional original source language. `geography` means the country assigned
to the outlet by GDELT. It is not the country mentioned in an article, the location of
an event, or the location of the audience.

The GDELT DOC API searches English terms across machine-translated coverage in supported
languages. This broadens international recall but does not remove translation errors,
ambiguous terms, changing source coverage, or country-level differences in the number
and kinds of outlets monitored.

## GDELT DOC API alternative: topic measurement

Enabled expressions within a topic are joined into one GDELT Boolean OR query. This
means an article matching two expressions in the same topic is counted once by GDELT.
Topics are independent: an article can count in both `clean_energy` and
`climate_change`, so topic counts must not be summed as mutually exclusive categories.

The default collector uses GDELT `TimelineSourceCountry`. One global topic request
returns separate series for source countries with matching coverage; the collector
selects the configured countries and fills an omitted country series with zero. Each
value is the percentage of all monitored media originating in that country that
matched the topic. The stored fraction is:

```text
country_attention_share = reported_percentage / 100
```

The native country mode does not expose raw matched or denominator counts, so those
fields remain null. If a global response omits an entire configured country series,
the collector records zero for that country and marks `series_omitted_as_zero` in
metadata. GDELT's unlabeled source-country series is ignored. If GDELT returns a
country series but omits an expected day, the window fails rather than inventing a
value. `--country-batch-size 7` retains explicit country-filtered requests as a
validation and recovery path.

## GDELT DOC API alternative: denominators

GDELT's `TimelineVolRaw.norm` is the total number of articles monitored by GDELT
globally in the interval, even when the query contains `sourcecountry:`. It is stored
as `global_monitored_count`; it is not a country denominator.

Optional `--trend-mode raw-counts` collection makes one topic and one baseline query
per country, language, and date window. The country-only baseline raw `value` is
stored as `country_monitored_count`. Raw rows use:

```text
global_attention_share  = matched_count / global_monitored_count
country_attention_share = matched_count / country_monitored_count
```

A zero or unavailable raw denominator produces a null calculated share rather than
zero. The native country share describes the fraction of monitored press from that
country discussing the topic in the DOC API path. It is not the primary MVP outcome.
Both shares and counts require source-coverage validation; counts alone should not
be interpreted as public interest or compared naively across countries.

## GDELT DOC API alternative: time and completeness

Requested dates are inclusive UTC dates. Windows longer than one week are required so
GDELT returns daily rather than hourly or 15-minute resolution. The parser requires
exactly one point for every expected UTC date. A missing or duplicate date fails the
window; no synthetic zero or interpolation is inserted.

A successful native-share zero is different from a missing day within a returned
series. Raw mode represents a successful zero with `matched_count = 0`; a missing day
leaves the window failed and resumable.

Each successful window is written immediately to shared Parquet. Completeness is a
property of a run, not merely the presence of files. Before analysis, confirm that
the run state or manifest is `complete` and that all planned windows succeeded.

## GDELT DOC API alternative: known limitations

- GDELT's source catalog and monitoring coverage change over time.
- Small or less-digitized media systems may be underrepresented.
- Keyword taxonomies have false positives and false negatives and require validation.
- Machine translation can change query recall and precision across languages.
- The bundled 197-country catalog is syntactically validated, but every entry has not
  yet been proven against a live GDELT query.
- A missing series in the global country breakdown is interpreted as zero matching
  coverage. Researchers needing to distinguish zero matches from no monitored media
  should collect raw country baselines for the affected panel.
- A five-year range is planned as bounded annual requests, but live API acceptance of
  every country and historical window is not guaranteed.
- The public DOC API has variable shared capacity. Failed and interrupted windows must
  be resumed; large world-scale backfills may need GDELT bulk datasets.

Article-list collection is optional and intended for auditing spikes or later content
classification. It is not needed to produce the DOC API daily attention series.

## Independent event measurement

The primary event treatment is external to the attention outcome. NASA FIRMS
science-quality VIIRS S-NPP detections provide the physical daily wildfire series,
while GDACS provides a catalogue that can include wildfires, floods, and tropical
cyclones. The current frontend and event-study analysis use only wildfires and floods. GDELT extreme-weather queries may later be used as a secondary event-news
salience measure, but not as the sole treatment definition: selecting events from the
same news stream being explained would mechanically favour well-covered events.

FIRMS requests use the documented `world` area in non-overlapping windows of no more
than five days. Points classified as presumed vegetation fire (`type=0`) are retained
unless confidence is low. Each point is assigned to a configured sovereign country
using revision-pinned Natural Earth 1:50m polygons, then count and fire radiative
power are aggregated by UTC acquisition date. Complete country polygons receive zero
when no retained point exists; a country without boundary support receives null.
Neither a hotspot nor summed FRP is equivalent to burned area, fire impact, or a
named wildfire event. Agricultural and prescribed burning may remain.

GDACS records are used at event level. The canonical identity combines provider,
hazard code, and event id; affected-country arrays support multi-country events.
Start/end dates and severity can be revised, so `source_updated_at` controls upserts.
For wildfires, GDACS severity in hectares is treated as the event's cumulative burned
area. The Attention Timeline assigns that value to the event start date and supports
daily, 7-day, 14-day and 28-day trailing sums. A multi-country event contributes its
full value to each affected-country view, but only once to combined-country, EU27 and
global totals; the result is therefore not unique land area if country series are
manually summed.
For display, the GDACS point is independently intersected with pinned Natural Earth
Admin-0 and Admin-1 polygons to derive a map country and first-order region label.
These point labels do not overwrite GDACS's affected-country array, and offshore or
unmatched points remain explicitly unlabeled.
GDACS alert scores are oriented toward potential humanitarian consequences rather
than a uniform physical magnitude. Analyses should preserve both event type and
source-specific severity semantics instead of pooling them naively.

## Satellite vegetation and burned area

The scalable vegetation series uses NASA MOD13C2 version 6.1 NDVI: a monthly global
0.05-degree (about 5.6 km) Climate Modeling Grid product. The collector requests only
the NDVI variable through Earthdata Cloud OPeNDAP, computes country statistics, and
deletes each temporary NetCDF subset. Country means are weighted by latitude-derived
cell area; World and EU27 means use the same retained area weights.

Raw NDVI is strongly seasonal. For comparisons with attention, each country or
region is therefore expressed as the difference from its own mean for the matching
calendar month. The default climatology is 2001–2020 and requires at least five
baseline observations. A composite value is drawn only across its calendar month; it
is not presented as a new daily satellite measurement. The first MVP uses all valid
CMG cells and does not yet claim to isolate grassland or cropland. The coarser grid is
intended for country-scale comparison, not local vegetation mapping.

MCD64A1 version 6.1 `Burn_Date` is processed differently. For native-projection
GeoTIFFs, pixels with an ordinal burn day are counted by day and multiplied by the
affine pixel area in hectares. Country pixels are then summed for EU27 and World
totals. Successfully processed composites also produce explicit zero-hectare days,
preserving the difference between no detected burning and missing coverage. This
provides observed burned area through time and remains separately selectable from
GDACS' whole-event severity estimate; the timeline can overlay both for contrast.
Boundary-edge pixels and product detection limits remain sources of measurement
uncertainty. NDVI is labelled as surface greenness/browning and is never treated as
a burned-area classification.

## Unofficial Google Trends fallback

The Google mode measures search interest rather than media output. Each configured
query is sent as a literal search term for one search-origin country and one requested
date range. Query alternatives are intentionally not OR-combined: Google Trends does
not provide GDELT-style Boolean deduplication, so every query remains a distinct
series.

Google samples eligible searches, divides each point by the highest point in the
request's time and geography scope, and scales the result to `0..100`. The collector
therefore stores `attention_index` and never converts it to an apparent share or
count. Each response receives a deterministic `scaling_group_id`. Levels from
separate countries, queries, or requested ranges are independently scaled and are not
directly comparable.

The provider decides the returned time resolution. The collector preserves the
observed dates and labels the inferred resolution as daily, weekly, monthly, or
irregular; it does not interpolate coarse series into daily data. Getting five years
of genuinely daily data would require a separately implemented and validated
overlapping-window stitching method. Repeated collection is also needed to quantify
sampling variability before the series is used in an event study.

The fallback uses only pytrends-modern's ordinary HTTP path. Browser automation,
saved login sessions, proxy rotation, and user-agent rotation are disabled or absent.
Because this is an undocumented web interface, endpoint changes and rate limits can
break collection. Frozen configs, run state, package version, scaling metadata, and
response envelopes must be retained, and an official API should replace this source
when access is available.

## GDELT Web NGrams primary attention source

Web NGrams 3.0 is a URL-level index over original-language article text from January
2020 onward. The collector reconstructs each configured native-language literal from
the `pre`, `ngram`, and `post` context fields and deduplicates matches across phrases
and languages to one URL per topic and day. It does not count phrase occurrences as
articles. Phrase records carry the GDELT ISO language code, segmentation mode, and a
translation-validation status. Character-mode context is concatenated without spaces
for languages such as Chinese and Japanese.

All selected topics are evaluated in one table scan per date window. A matched URL
is expanded to every applicable topic and then deduplicated on
`(topic_id, day, url)`. Thus synonyms and translations within a topic cannot inflate
its count, while an article legitimately matching two conceptual topics contributes
once to each. The batch window is the operational retry unit; canonical record
identity remains topic-specific and is backward-compatible with earlier per-topic
runs.

The interval from 14 June through 1 July 2025 is excluded from GDELT NGrams
analysis. GDELT confirmed multiple infrastructure outages during the observed
coverage collapse; direct GAL checks show 14 June was partial, coverage remained
unusable through 1 July, and normal article volumes returned on 2 July. Stored zero
scaffolds in this interval are provider missingness, not observed zero attention.
Event windows crossing the interval therefore fail completeness, and collection
planning skips it on future runs.

When a political configuration is supplied, the same NGram scan also accumulates
URL-level co-occurrence flags for `political_actor`, `government_action`, and
`party_politics`. The daily political measure is the distinct-URL union of those
flags and an `official_source` flag derived from the versioned country-domain
registry:

```text
political_count = distinct topic URLs where actor OR action OR party OR official
political_share_of_matched = political_count / matched_count
```

The component counts overlap by design and therefore must not be summed. Political
phrases may occur anywhere in the indexed article text; this is a discourse-relevance
screen, not a claim that a politician caused or endorsed the underlying event. A
deterministic hash-ordered sample can be joined to GAL for review, or `--save-articles`
can retain the complete matched panel. Available GAL fields are publication time,
URL/domain, outlet name/logo/Twitter handle, title, image, description, language and
author. The panel also retains one deterministic representative `pre`/`ngram`/`post`
context for each distinct configured phrase that matched the article, covering both
topic membership and political-signal classification. Evidence is capped at 100
phrases per article-topic row with the uncapped total and truncation status retained.
No GKG/Knowledge Graph table is queried. Exact daily counts are a census of
matched indexed URLs; a bounded sample must only be used to audit classifier error.

Country attribution uses GDELT's multilingual April 2015 domain-country table.
Ambiguous domains are discarded, the longest matching domain suffix wins for
subdomains, and URLs without a mapping are excluded. This catalogue is both old and
incomplete; metadata therefore records the share of all matching URLs that received
any unambiguous country assignment. Selected-country coverage cannot by itself
recover the country distribution of unmapped URLs.
In political mode, configured official domains are also eligible attribution domains
and take precedence over an equally specific historical mapping. This retains known
government, parliamentary, and party pages that are missing or stale in the 2015
catalogue, while keeping the override transparent in the frozen configuration.
Each country-day row also records whether the requested country label has any mapped
domains. A zero for an unsupported mapping must be treated as missing, not as a
measured zero. `audit-ngram-countries` produces the full mapping review and suggested
historical labels.

The default NGram measure is a country-day article count:

```text
matched_count = distinct matching NGram URLs attributed to the country
```

The affordable pilot filters the table's clustered `ngram` column using exact,
unpunctuated lower- and title-case anchor forms, then verifies the full configured
phrase against its context. This misses uppercase and some punctuation-adjacent
forms and therefore requires a later sensitivity analysis.

An optional `--include-denominator` mode also finds the distinct set of GAL URLs
assigned to the same country and day:

```text
country_attention_share = distinct matching NGram URLs / distinct mapped GAL URLs
```

The resulting optional share resembles but does not reproduce
`TimelineSourceCountry`. The API uses GDELT's
current internal source-country assignments and searches English machine-translated
coverage. NGrams search the original text and use a historical externalized country
map. English-only phrases undercount non-English coverage. The bundled multilingual
taxonomy is a draft research seed; translated terms must be reviewed for local usage,
inflection and conceptual equivalence before inferential analysis. Initial validation
must compare paired daily shapes, missingness, per-language composition and zero
rates—not demand identical levels.

The canonical NGram topic-country-day row is replaced when the same date is
recollected with a newer phrase taxonomy. Phrase records in row metadata identify the
active definition, while frozen run manifests and raw response envelopes preserve
the earlier definition. Do not combine partially upgraded date ranges without
checking that their configured-language and phrase metadata agree. Canonical rows
are mutable, not immutable versions of each research definition. A known merge edge
case can retain an earlier non-null derived value when a revised NGram collection
omits it; see the [open issue](ARCHITECTURE_BRIEFING_2026-09-15.md#7-provenance-does-not-yet-provide-immutable-dataset-versions).
This was reproduced synthetically, not established as an error in the stored results.

All BigQuery jobs use parameterized SQL, a non-billable dry run, an explicit billing
project and a hard per-window `maximum_bytes_billed` cap. Query byte estimates,
batched topic IDs, and completed job statistics are retained in response envelopes
and row metadata. Denominator mode is not the default because scanning GAL can
dominate cost; estimate it independently.

## Planned official Google Trends integration

Search interest is not yet a core outcome. The existing collector uses an unofficial
interface with request-specific scaling and operational instability. As reported by
the developer in September 2026, an individual official-API application has received
no response after around a month. The proposed next step is an application under
T&E's name describing the research, target markets, and intended refresh schedule;
access and a response date cannot be assumed.

Google's [official API documentation](https://developers.google.com/search/apis/trends),
checked on 14 September 2026, describes an access-limited alpha with a rolling
five-year history, daily through yearly aggregation, and consistently scaled data
across requests. These features make integration appear manageable using the
existing storage and run-management workflow. An official connector still needs to
be implemented and tested with granted credentials, quotas, actual response formats,
and coverage. Its scaling rules must be recorded separately from the unofficial
collector's `0..100` series.

Start with a small pilot of T&E's priority countries and reviewed local search
terms, checking supported query/topic semantics, low-volume or missing observations,
time resolution, comparability, and repeatability. Then backfill the available
history and schedule incremental refreshes with completeness checks. Align search
origin with publishing-outlet geography explicitly: these describe different
populations, and neither directly measures public opinion.

## Planned non-weather, geopolitical, and energy-market events

Extend the independent event catalogue with a dated register sourced from official
calendars, announcements, and documented external records. Start with COP meetings,
EV launches, elections, policy announcements, and policy implementation. Store a
stable event identifier, category, source URL, announcement/start/end dates, relevant
countries, and revisions. Keep announcement and implementation dates distinct, and
record advance notice so anticipated events can have a pre-event attention response.
Do not select the register's events because they produced a visible attention spike.

Maintain separate geopolitical and energy-market trackers for Strait of Hormuz
disruptions, conflicts, sanctions, and supply shocks, alongside independently sourced
oil-price observations. Keep dates of discrete events distinct from continuous
price series; country exposure should follow a documented rule such as geography or
pre-event import dependence. Any manually curated event should retain its evidence
and review status.

For the question “Does oil reaching US$100 per barrel precede more EV discussion?”,
predefine the benchmark (for example, Brent), price source, spot or futures series,
USD/barrel unit, observation frequency, and crossing rule before testing. A possible
rule is the first daily close at or above US$100 after a predefined period below it;
group repeated crossings into episodes so days within one price surge are not
treated as independent events. Preserve non-trading-day gaps and distinguish the
threshold test from a separate analysis of continuous price changes.

Compare EV news, searches, and public posts separately before, during, and after
each eligible episode, using reviewed topic definitions and complete windows.
Include matched dates or markets with different predefined exposure where credible,
and account for seasonality, underlying trends, and concurrent launches, policies,
or geopolitical events. A global oil shock may leave no truly untreated country;
the resulting comparison must be labelled accordingly. Retain source-specific
event attributes rather than imposing a common severity scale across weather,
politics, and energy markets.

To explore a possible country-A-to-country-B sequence, predefine country pairs,
time windows, and candidate lags. Test whether earlier attention in A adds predictive
information about later attention in B beyond B's own history and common event
timing, using held-out periods. Inspect syndicated coverage and shared language as
alternative explanations; correct for testing many pairs and lags. Temporal ordering
alone does not establish that discussion in A caused discussion in B. These
trackers and analyses are proposed extensions, not currently implemented findings.

## Source documentation

- [GDELT DOC 2.0 API documentation](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [GDELT raw result counts announcement](https://blog.gdeltproject.org/gdelt-2-0-api-now-supports-raw-result-counts/)
- [GDELT rate limiting and Web NGrams guidance](https://blog.gdeltproject.org/ukraine-api-rate-limiting-web-ngrams-3-0/)
- [GDELT's June 2026 non-consumptive NGrams guidance](https://blog.gdeltproject.org/using-the-new-web-ngrams-dataset-to-find-relevant-coverage/)
- [GDELT Web NGrams 3.0 dataset](https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/)
- [GDELT domain-country segmentation example](https://blog.gdeltproject.org/using-web-ngrams-3-0-custom-media-catalogs-to-segment-by-country-state-ownership-partisanship-or-other-attributes/)
- [GDELT infrastructure outage notice, June 2025](https://www.linkedin.com/posts/kalevleetaru_we-are-aware-of-multiple-gdelt-infrastructure-activity-7340435180601393154-_SDg)
- [Google Trends data normalization](https://support.google.com/trends/answer/4365533?hl=en-GB)
- [Google Trends search terms and topics](https://support.google.com/trends/answer/17309543)
- [Google Trends API alpha](https://developers.google.com/search/apis/trends)

Record the package version, frozen topic and country configs, manifest, and retrieval
date when citing a derived dataset. Cite GDELT separately as the underlying source.
