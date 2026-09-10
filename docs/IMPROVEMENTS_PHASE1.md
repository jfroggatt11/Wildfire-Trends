# First improvement batch — 10 September 2026

This implements the first correctness batch from [the repository review](REVIEW_2026-09-10.md). Changes are local; the live Supabase tables and hosted frontend have not been changed.

## Changes

- **Unsupported mapping is unavailable.** The event-study loader retains the mapping-support flag from canonical metadata. Explicitly unsupported country-days cannot enter affected-market estimates as zeros. Every affected country must be observed, including countries absent from the loaded panel. Global/EU groups explicitly describe supported markets. The daily-attention sync writes null counts and a minimal mapping-support flag into the existing serving `metadata` column. The browser honors both null counts and explicit unsupported flags. Unknown legacy metadata remains unknown and retains existing behavior; mapping support is not a claim of validated source coverage.
- **Continuous observation windows.** Study year selects events; attention observations are retained across year boundaries, including post-event periods for long-running events. The date selector still describes the selected event year. Year-specific effect filenames and all-alert warehouse directories avoid overwriting another year's analysis.
- **Fixed overlap policy.** Every displayed cohort uses Orange/Red wildfire and flood overlaps, across all available years. Green events remain available as candidates but are not part of the overlap-exclusion catalogue. This preserves the original major-event policy while making it consistent across static and served analyses. It is not an all-hazard/all-alert contamination model.
- **Complete daily charts.** Event charts include every UTC calendar date and explicit nulls, with a numeric time axis and linear lines. A partially missing affected-market aggregate is unavailable; duplicate market rows cannot inflate it. Provider clock times no longer remove the first pre-event day. Regional aggregates also reject partial days and deduplicate identical inputs.
- **Descriptive presentation.** The drawer reports observed increase/decrease and complete-period means without permutation significance verdicts. The overview replaces the selected-country significance leaderboard with 7/14/28-day sensitivity results. Its headline describes news changes around events, and the snapshot distinguishes supported from configured markets. “Excess attention” is labelled “Residual from area-only fit.” Methods copy and overlap controls reflect the new rules.

## Effect on the saved results

Compared with the 5 September snapshot, 104 specifications changed in 2025 and 64 in 2026. Across both years, 128 previously incomplete specifications became complete; eight became incomplete because affected-market coverage was unsupported. Overlap flags changed in 72 specifications. These categories overlap and must not be added as independent counts. Specifications are event×topic×scope×timing×window combinations, not independent events.

| Affected-market climate onset | Before | After |
|---|---:|---:|
| 2025, 7 days | 0.0%, n=20 | 0.0%, n=20 |
| 2025, 14 days | +9.5%, n=16 | +9.5%, n=16 |
| 2025, 28 days | +1.9%, n=13 | +1.9%, n=13 |
| 2026, 7 days | +3.0%, n=13 | +1.7%, n=12 |
| 2026, 14 days | +27.6%, n=9 | +29.8%, n=8 |
| 2026, 28 days | −5.0%, n=6 | 0.0%, n=7 |

The corrected 14-day global climate medians are +3.0% (20 events) in 2025 and −4.6% (10 events) in 2026. The affected-market EV medians are +3.4% (16) and −2.9% (8). The major-event files now contain 2,416 complete specifications. The manifest identifies 182 markets with mapping support among 197 configured markets.

Examples now handled correctly:

- `gdacs:FL:1103404` (Philippines/Vietnam) cannot provide a complete affected-market estimate when Vietnam is unsupported.
- `gdacs:FL:1103735` (19 January 2026) is flagged as overlapping `gdacs:FL:1103694`, which began in December 2025 and continued into January.
- Late-2025 persistence windows can use observations from 2026.
- The June/July outage occupies real space on the event chart and interrupts its lines.

Machine-readable before/after differences are in `data/analysis/review-changes-2025.json`, `review-changes-2026.json`, and `review-summary.json`. The original review documents the pre-fix snapshot and is intentionally retained as an audit record.

## Validation and release

Regression tests cover unsupported and absent markets, genuine zero counts, missing dates, non-midnight event timestamps, year-crossing windows and overlaps, cohort-invariant overlap policy, duplicate rows, regional completeness, support metadata in serving records, and isolation of yearly warehouse outputs. Python tests, frontend unit tests and the production build pass. Browser rendering and browser regression tests remain unverified because no connected browser was available.

The all-alert warehouse now writes to `data/analysis/year=2025/` and `year=2026/`. `sync-analysis-supabase --year YEAR` reads the matching directory; `--skip-build` requires these newly generated files. Major-cohort flat effects are `data/analysis/event_effects_2025.parquet` and `event_effects_2026.parquet`.

Before publishing this frontend, sync the daily table and both derived years together so older remote zero scaffolds and overlap flags are not mixed with the corrected static files. No schema migration is required for mapping support: the existing JSONB metadata column is used. The normal authorized release commands are:

```bash
.venv/bin/climate-attention sync-supabase --data-dir data
.venv/bin/climate-attention sync-analysis-supabase --data-dir data --year 2025 --skip-build
.venv/bin/climate-attention sync-analysis-supabase --data-dir data --year 2026 --skip-build
```

These commands are documented here and have not been executed against the remote database.

## Remaining work

The next batch should preserve the exact Lab specification through event drill-downs, expose day-specific sample sizes and fixed-cohort sensitivity, fix country-response attribution, and improve raw-count/low-baseline context. Denominator validation, multilingual classifier audits, time-aware inference, satellite QA, the lag-correlation redesign and navigation consolidation remain on the original review list. This batch does not establish causal effects or validate the classifiers.
