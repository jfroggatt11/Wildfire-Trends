# Methodology

## GDELT unit of observation

The canonical observation is one UTC day, conceptual topic, publishing outlet source
country, and optional original source language. `geography` means the country assigned
to the outlet by GDELT. It is not the country mentioned in an article, the location of
an event, or the location of the audience.

GDELT searches English terms across machine-translated coverage in supported
languages. This broadens international recall but does not remove translation errors,
ambiguous terms, changing source coverage, or country-level differences in the number
and kinds of outlets monitored.

## Topic measurement

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

## Denominators

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
zero. The native country share remains the preferred attention-intensity measure
because it asks what fraction of the monitored press from that country discussed the
topic. Raw counts remain useful
for workload, output-volume, and sensitivity analyses, but should not be interpreted
alone as public interest or compared naively across countries.

## Time and completeness

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

## Known limitations

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
classification. It is not needed to produce the canonical daily attention series.

## Independent event measurement

The primary event treatment is external to the attention outcome. NASA FIRMS
science-quality VIIRS S-NPP detections provide the physical daily wildfire series,
while GDACS provides a global catalogue of major wildfires, floods, and tropical
cyclones. GDELT extreme-weather queries may later be used as a secondary event-news
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
GDACS alert scores are oriented toward potential humanitarian consequences rather
than a uniform physical magnitude. Analyses should preserve both event type and
source-specific severity semantics instead of pooling them naively.

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

## GDELT Web NGrams validation source

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
deterministic hash-ordered sample can be joined to GAL for URL, title, description,
language, and author review. Exact daily counts are a census of matched indexed URLs;
the bounded article sample exists only to label and audit classifier error.

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
checking that their configured-language and phrase metadata agree.

All BigQuery jobs use parameterized SQL, a non-billable dry run, an explicit billing
project and a hard per-window `maximum_bytes_billed` cap. Query byte estimates,
batched topic IDs, and completed job statistics are retained in response envelopes
and row metadata. Denominator mode is not the default because scanning GAL can
dominate cost; estimate it independently.

## Source documentation

- [GDELT DOC 2.0 API documentation](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [GDELT raw result counts announcement](https://blog.gdeltproject.org/gdelt-2-0-api-now-supports-raw-result-counts/)
- [GDELT rate limiting and Web NGrams guidance](https://blog.gdeltproject.org/ukraine-api-rate-limiting-web-ngrams-3-0/)
- [GDELT's June 2026 non-consumptive NGrams guidance](https://blog.gdeltproject.org/using-the-new-web-ngrams-dataset-to-find-relevant-coverage/)
- [GDELT Web NGrams 3.0 dataset](https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/)
- [GDELT domain-country segmentation example](https://blog.gdeltproject.org/using-web-ngrams-3-0-custom-media-catalogs-to-segment-by-country-state-ownership-partisanship-or-other-attributes/)
- [Google Trends data normalization](https://support.google.com/trends/answer/4365533?hl=en-GB)
- [Google Trends search terms and topics](https://support.google.com/trends/answer/17309543)
- [Google Trends API alpha](https://developers.google.com/search/apis/trends)

Record the package version, frozen topic and country configs, manifest, and retrieval
date when citing a derived dataset. Cite GDELT separately as the underlying source.
