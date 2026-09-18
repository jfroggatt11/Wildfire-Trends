# UK pilot BigQuery dry-run estimate

**Date:** 18 September 2026  
**Billing project:** `wildfire-trends-505214`  
**Query mode:** BigQuery dry run (`dry_run=true`); no data processed and no query charge  
**Test period:** 7–13 September 2026 inclusive

## Workload tested

- United Kingdom only in the requested output.
- Four English-language topic seeds: climate change, cost of living, clean
  transport and electric vehicles.
- 39 configured phrases across those topics.
- UK political-signal seed configuration.
- Retention of all matched article URLs and available GAL metadata.
- One batched query for all four topics.

The phrase definitions are in
[`config/topics.uk-pilot.yaml`](../config/topics.uk-pilot.yaml). They are initial
cost-estimation seeds and require T&E review and precision/recall validation.

## Results

| Seven-day workload | Estimated bytes scanned |
| --- | ---: |
| Matched topics + political signals + retained article URLs | 100.472 GB |
| Same workload + all-UK GAL denominator | 100.474 GB |
| Increment from denominator in this dry run | approximately 0.002 GB |

The denominator result means the current combined SQL can calculate the number of
GDELT GAL articles attributable to the configured UK outlet-country mapping at
negligible additional scan volume for this tested week. It does not validate the
completeness of that universe or the underlying outlet-country mapping.

## Cost translation

Using BigQuery’s published on-demand starting price of
[US$6.25 per TiB scanned](https://cloud.google.com/bigquery/pricing):

| Frequency | Approximate scan | Nominal query price before free tier |
| --- | ---: | ---: |
| One weekly refresh | 0.091 TiB | US$0.57 |
| Average month of weekly refreshes | 0.40 TiB | US$2.48 |
| 52 weekly refreshes | 4.75 TiB | US$29.70 |

The first 1 TiB of on-demand queries per month is currently free. If this were the
billing account’s only BigQuery analysis workload, the regular weekly refresh would
fit within that allowance. Other queries on the account consume the same allowance.

These figures cover query analysis only. They exclude scheduled reruns or overlap
windows, historical backfills, BigQuery or object storage, Cloud Run, networking,
database serving, Google Trends/social access and licensed market data. Exact bytes
can change with dates, GDELT table volume, phrase anchors, political definitions,
article output, denominator logic and query implementation. Every production query
should be dry-run first and protected by `maximum_bytes_billed`.
