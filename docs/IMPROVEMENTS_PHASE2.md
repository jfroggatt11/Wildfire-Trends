# Phase 2: comparison continuity and visible evidence

Implemented locally on 10 September 2026. These changes use the existing exports and refreshed Supabase tables; no database migration or data refresh is required.

## Changes

- Opening an event from either Lab event ranking carries its topic, media group, measure, window and timing into Explore. Event URLs include those settings and restore them on reload. Invalid URL options fall back to a 14-day climate-count onset comparison. Closing the event clears the event-specific URL parameters.
- Explore supports the Lab's Other EU27 and Rest of world groups using complete panels of supported publishing markets. These groups exclude affected countries and retain their original definitions.
- The drawer supports onset and post-end comparisons and political share. Onset includes day zero; persistence starts the day after event end. Both retain the pre-onset baseline, including across year boundaries. Political share uses period totals, not the mean of daily percentages. Its daily chart uses percentage units.
- Country rows now explicitly group event responses by affected country. They display the selected media group and explain that multi-country events appear in multiple rows. This corrects the interpretation; it does not introduce country-specific domestic response estimates.
- Event and wildfire ranking rows show mean counts before and after, absolute daily changes and baseline URL totals. The drawer shows totals for both periods. Baselines below 20 URLs receive an explicit display flag, not an inferential cutoff. Political-share rows identify the matched-URL denominator.
- The Lab's event ranking identifies itself as the upper tail of responses rather than a representative sample.
- Info and the Lab compare 7-, 14- and 28-day medians for both all eligible events and the intersection of events eligible in every window. Intersection eligibility includes measure availability and the selected overlap exclusion rule. All-alert results fetch all three window specifications to support this comparison.
- Pooled curves expose the contributing event count in the tooltip and its range in the caption. Days with no usable values stay null; the numeric date axis and straight segments do not bridge missing days. Topic summary statistics report their own usable sample sizes.

## What the fixed-cohort comparison shows

Affected-market climate counts, major events, onset, excluding Orange/Red overlaps:

| Event year | Common events | 7 days | 14 days | 28 days |
| --- | ---: | ---: | ---: | ---: |
| 2025 | 12 | -2.38% | +9.51% | +9.73% |
| 2026 | 7 | +3.03% | +27.45% | 0.00% |

The 2026 sample is partial-year. Fixing membership removes changing event composition from this window comparison; it does not address confounding, selection bias or dependence between events.

## Verification

- 49 frontend tests pass, including URL round trips, cross-year onset/persistence dates, distinct geography panels, missing days and denominators, low-volume evidence, and fixed-cohort eligibility.
- Regression checks compare drawer calculations with all 2,416 complete exported event specifications across 2025 and 2026, for matched counts, political counts and political share.
- TypeScript and the production build pass.
- Browser regression expectations were updated and a Lab-to-drawer/reload test was added. These browser tests and visual verification were not run: the computer-use tool reported no connected browsers.

Remaining research work includes classifier validation, country news denominators and temporal placebo/matched-comparison designs. Country-specific domestic effects would require a new analytical output rather than relabelling the pooled event effects.
