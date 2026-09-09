# Climate Attention Atlas — Project One-Pager

## What the project sets out to do

Climate Attention Atlas investigates how major wildfires and floods relate to changes in news attention to climate change and the transition to electric vehicles. Its central design choice is to measure the physical event independently from the media response: disasters come from external hazard catalogues, while attention is measured from news publishing data. The result is a reproducible data pipeline and interactive research interface for exploring when attention rises, where it rises, whether it persists after an event, and how much of the coverage includes political actors or government action.

The project is intended as an exploratory research platform, not yet as proof that extreme-weather events cause changes in news coverage or public opinion.

## Data sources

- **GDELT Web NGrams 3.0** is the current MVP's primary attention source. It provides distinct matched news URLs by UTC day, topic, and publishing-outlet country. The pipeline also supports the GDELT DOC API as a comparison and validation source.
- **GDACS (Global Disaster Alert and Coordination System)** supplies named wildfire and flood events, dates, affected countries, alert levels, locations, and provider-reported severity. Orange and Red alerts form the main analytical cohort.
- **NASA MODIS** supplies country-level burned-area observations and seasonal NDVI anomalies, allowing media attention to be viewed alongside physical burning and surface greenness or browning.
- **NASA FIRMS** provides an additional physical wildfire layer based on science-quality VIIRS detections and fire radiative power. It is kept distinct from named GDACS events and from burned area.
- **Natural Earth** boundary data supports reproducible country assignment and map labels. An unofficial Google Trends collector is available as a search-interest fallback, but its independently scaled and unstable data are not used as the main outcome.

## Methodology in brief

The current study tracks two multilingual topics: **climate change** and **electric vehicles**. Within each topic, matching phrases are alternatives and every URL is counted at most once per topic and day. Media geography means the country of the publishing outlet—not the event location, article subject, or audience. Political coverage is a deduplicated union of political-actor, government-action, party-politics, and known official-domain signals.

For each GDACS event, the system compares mean daily URL counts during an event-onset window, or during a post-event persistence window, with the event's own immediately preceding baseline. Users can select 7-, 14-, or 28-day windows and compare affected countries, other EU countries, the rest of the world, or the global total. Pooled results use the median event response and show the interquartile range. Every required date must be present; missing days are never filled with zero, the confirmed 14 June–1 July 2025 GDELT outage is excluded, and overlapping major events in the same country are excluded by default.

These before-and-after estimates and lead/lag correlations are descriptive associations. They do not yet control for seasonality, concurrent news, autocorrelation, or an untreated comparison group.

## What the interface tabs do

- **Explore** maps individual floods and wildfires. Selecting an event opens an **Attention** tab with daily climate-change and EV coverage plus a before/after test, and a **Coverage breakdown** tab showing timing, political signals, and the largest publishing markets.
- **Analysis Lab — Event study** pools comparable events and tests different hazards, media groups, time windows, and definitions of attention. It reports the median response, variation across events, country patterns, and the events with the largest increases.
- **Wildfire attention** ranks which fires generated the strongest response and compares attention with GDACS-reported area. Its severity residual is a descriptive benchmark, not a forecast.
- **Event activity** compares rolling event starts with attention over time and offers exploratory lead/lag correlations and country comparisons.
- **Attention timeline** provides the broad time-series view across topics and publishing markets, with event markers and optional GDACS burned area, MODIS burned area, and NDVI overlays.
- **Data** documents current coverage, gaps, and source provenance; **Methods** records the definitions, design choices, limitations, and validation protocol.

## How successful is it?

The project is successful as an end-to-end MVP. As of the 5 September 2026 export, it contains **230,884 daily topic-market rows** covering **586 observed news days and 197 publishing markets**, **531,101 retained article records**, **9,024 GDACS wildfire and flood events**, and **112,410 MODIS observations** across 199 geographies. The major-event exports include 40 events for 2025 and 23 for 2026, with 2,296 complete event/specification rows available across the two studies. The map explorer, attention timeline, event drill-downs, multi-event Analysis Lab, satellite comparisons, resumable collection, provenance records, and optional Supabase serving layer are all implemented. The current automated suites pass **112 Python tests and 35 frontend tests**.

The early substantive results are promising but not uniform. Under the 14-day, non-overlapping specification, median affected-market climate-change coverage increased around event onset by 9.5% across 16 eligible 2025 events and 27.6% across nine eligible 2026 events. The corresponding global medians were smaller and mixed (+4.2% and −1.7%), while electric-vehicle attention showed no consistent increase.

A check of every available major-event affected-country series using the interface's 7-day post-event, one-sided permutation test found nominal increases at **p < 0.05** for events affecting **Spain, France, Pakistan, Sri Lanka, the United States, and Nigeria**. Spain has the clearest repeated pattern: five of nine testable Spanish events showed increases of 35%–72%, and its median 14-day onset response was +27% across nine events. However, the five significant Spanish records overlap other Spanish fires, especially the August 2025 cluster, so they are not independent replications. The other country signals each come from one event, and Nigeria is borderline (p = 0.048). None of these tests has been corrected for multiple comparisons. They are promising leads for confirmatory analysis, not country-level causal findings.

## Future plans

The next phase is to expand both the evidence base and the questions the platform can answer. Priorities are to:

1. **Extend the data backwards** to build a longer historical record, cover more events, and improve the power and robustness of comparisons.
2. **Automate collection and refreshes** so news, search, event, and physical data update on an appropriate daily, weekly, or monthly schedule with completeness checks and alerts for failed runs.
3. **Add Google Trends as a core comparison source** to measure what people search for, complementing GDELT's measure of what news outlets publish.
4. **Add public social-posting data from Bluesky and, where access permits, X.** This would measure what people post about and could follow defined groups such as MEPs and other politicians, linking the Atlas to existing T&E political and communications work.
5. **Broaden the event layer.** Add ordinary weather anomalies such as temperature departures from local historical norms; more extreme-weather types; and non-weather events such as COP meetings, EV launches, elections, policy announcements, and other political events.
6. **Test a wider set of hypotheses** about timing, spillovers, geography, event severity, political attention, and differences between published, searched, and posted attention.
7. **Build toward a predictive model of attention from event data.** Once the historical panel and validation are strong enough, use out-of-sample evaluation and interpretable feature-importance methods to identify which event characteristics best predict attention.
8. **Continue validating the approach throughout:** conduct native-speaker and precision/recall reviews of topic and political classifiers; audit domain-to-country attribution; add validated news denominators; compare event sources without treating unlike severity measures as equivalent; pre-register confirmatory hypotheses; add matched dates or untreated markets; and correct for multiple testing.
