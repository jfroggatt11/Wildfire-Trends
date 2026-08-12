# Methodology

## Unit of observation

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

## Source documentation

- [GDELT DOC 2.0 API documentation](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [GDELT raw result counts announcement](https://blog.gdeltproject.org/gdelt-2-0-api-now-supports-raw-result-counts/)
- [GDELT rate limiting and Web NGrams guidance](https://blog.gdeltproject.org/ukraine-api-rate-limiting-web-ngrams-3-0/)
- [GDELT's June 2026 non-consumptive NGrams guidance](https://blog.gdeltproject.org/using-the-new-web-ngrams-dataset-to-find-relevant-coverage/)

Record the package version, frozen topic and country configs, manifest, and retrieval
date when citing a derived dataset. Cite GDELT separately as the underlying source.
