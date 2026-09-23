# UK Attention Atlas — Web App Screen Design

## Product model

The Atlas is a research workbench. Every screen answers three linked questions:

1. What changed? A topic, channel, place or period with a measurable attention signal.
2. What happened at the same time? Weather, prices, disruption, hazards or dated events.
3. What evidence supports the measure? The source definition, denominator, coverage, article records and missingness.

The first screen is the attention timeline because it is the most reusable way to compare topics and inputs. The map is the second main workspace for geographic questions. Event detail, article evidence, saved views and methods open as routes or drawers.

The product should keep its exploratory status visible. Charts can show associations and timing; labels should not imply that an event caused attention to change.

## Global application shell

The shell is shared by every screen:

- Top bar: T&E / UK Attention Atlas wordmark, dataset freshness, primary navigation and access status.
- Primary navigation: Timeline, UK map, Saved views, Data and Methods.
- Global actions: Save view, Share link, Export and help.
- Persistent context: active dataset release, date range, topic configuration version and last successful refresh.
- Mobile behavior: collapse navigation into a menu while keeping Save, Share and the current view title visible.

The URL should encode the view and analytical specification. A colleague should be able to open a link and see the same topics, dates, channels, geography, measures and event overlays.

## Screen 1: Attention timeline

### Purpose

Build a chart by adding any number of compatible series to a left Y axis and, optionally, a right Y axis. A series can represent an attention topic, place, source group, price, share price, physical measure or validated derived metric. Filtered event sets and custom event markers sit on the X axis.

### Layout

~~~text
┌──────────────────────────────────────────────────────────────────────────────┐
│ UK Attention Atlas     Timeline   UK map   Saved views   Data   Methods       │
├──────────────────────────────────────────────────────────────────────────────┤
│ Attention timeline                                      Save  Share  Export   │
│ Compare attention and context across the UK                                  │
│ Chart title [Climate and transport attention vs fuel prices]                 │
│ Dates [2022-01-01] → [Today]     Interval [Week]     Place [UK]               │
├──────────────────────────────────────────────────────────────────────────────┤
│ Left Y: News share (%)                      Right Y: Petrol price (p/litre)   │
│  ● Climate change / UK / news share         ● Petrol / UK / weekly            │
│  ● EVs / UK / news share                     + Add series                      │
│  + Add series                                                                │
│                                                                              │
│  1.2% ┤                 ╭──╮                             ╭─── 165p           │
│  0.8% ┤       ╭──╮     ╭╯  ╰──╮             ╭─────────────╯                   │
│  0.4% ┼───────╯  ╰─────╯       ╰───────╮   ╱                                  │
│       └──────────────────────────────────────────────────────────────         │
│         2022        2023        2024        2025        2026                 │
│ Events [Heatwave · UK] [Policy · transport] [+ Add event filter]             │
│        [+ Add custom event]                                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│ Selected period: 18–24 July 2025          124 articles · 8,410 denominator   │
│ Climate change · 1.47% of captured UK news · 36 matching URLs                │
│ GDELT Web NGrams · complete for 7 of 7 days · release uk-2026-09             │
└──────────────────────────────────────────────────────────────────────────────┘
~~~

### Controls

The chart starts with one left axis and an Add right axis action. Each axis accepts multiple series. An Add series drawer asks for a metric, then its topic or subject, geography, source, outlet group and aggregation where relevant. A configured series appears as a compact row with color, label, axis assignment, visibility, style, duplicate and remove controls. Dragging a row between axes or changing its axis selector preserves the rest of its definition.

Available metrics should include:

- News attention share: topic-matching articles divided by all captured articles in the same UK outlet/date universe.
- Raw attention: distinct matching article count, search index or post count, with source-specific units.
- Conditional article percentage: a configurable numerator set A and a separately defined denominator set B, such as wildfire articles mentioning climate change divided by all wildfire articles. The interface displays the exact formula and matched coverage.
- Price and physical measures: petrol, oil, selected stocks, temperature anomaly, vegetation condition and disruption measures as their feeds arrive.
- Custom metric: a saved, typed expression over approved measures with explicit units, joins, time grain, zero-denominator handling and validation. An expression may combine approved measures, but it cannot silently join unmatched article universes.

Each axis has an editable label, unit, scale mode, tick format and optional range. An axis can show several series only when the displayed units are compatible or the user has explicitly selected an indexed or standardised transform. The app should warn if dual axes could imply a misleading relation and provide aligned panels as an alternative. Raw source units and transformations remain visible in tooltips and export metadata.

Presentation controls include editable chart title, subtitle, axis names, legend labels, series colors, line style and width, marker visibility, annotations, smoothing and date aggregation. Colors must meet contrast checks and remain distinguishable alongside labels or line patterns. A Reset appearance action restores defaults without changing data selections.

Date controls set start, end, aggregation and a date-range shortcut. Geography can be global to the chart or overridden per series to compare areas. An unavailable channel remains marked Access required or Planned.

The X-axis event builder has two paths:

- Add from event data: select event type, source, geography, date range, severity or other source-specific filters; preview the match count and sample dates; then add the resulting set as a named event track. Reopening the track shows its filter definition and current matches.
- Add custom event: supply title, start date, optional end date, category, place, description, source URL and display color. Custom events belong to the saved view until deliberately shared or promoted into the reviewed event catalogue.

If event markers collide, group them by date and open a list on selection. A filtered event set does not alter the attention query; it adds context to the same X axis.

### Chart behavior

- Attention measures use stable series colors and direct labels.
- Left and right axes can each contain multiple compatible lines. The chart never adds a third Y axis.
- Event tracks sit directly under the X axis. Selecting a marker opens its type, date, source, affected geography and saved filter or custom-event origin.
- If many series make the chart unreadable, the user can temporarily hide lines or switch to aligned panels without losing the configured view.
- Missing days are shown as gaps with an explanation and are never plotted as zero.
- Hover or keyboard focus shows all visible series at the selected date, with units, source and coverage.
- A selected date or range drives the evidence panel below the chart.
- Any percentage states its denominator: share of captured GDELT UK news.
- A How to read this link explains associations, source coverage and standardisation.

### Evidence panel

The evidence panel shows selected dates and values, numerator and whole-UK denominator, source and outlet breakdown, completeness, freshness, matched article URLs, topic evidence and article-content analysis status. It links to the relevant event, place or saved view.

On wide screens it sits below the chart. On small screens it becomes a full-height drawer.

### First-build scope

Implement first: multiple news-topic and geography series on the left axis, a configured right axis for a fixture or available price series, the whole-UK daily denominator, raw counts and topic shares, title/axis/legend/color editing, date controls, article drill-down, event tracks using fixture records, source coverage, completeness and dataset version. Persist the complete chart specification in the URL or saved-view schema from the beginning.

Add later: Google Trends, Bluesky and X, validated conditional and custom-metric builders, more physical and economic inputs, lag and spillover views and publication templates. The event filter and custom-event flow should be in the design from the start, with the first implementation limited to available event data.

## Screen 2: UK map

### Purpose

Explore how attention, conditions and events change across UK places and through time. The map has a date picker, a scrubber and Play/Pause controls. It preserves the difference between a publisher’s location, a place mentioned in an article and the location of an event.

### Layout

~~~text
┌──────────────────────────────────────────────────────────────────────────────┐
│ UK map                                                     Save  Share  Export│
│ Place, event and attention patterns                                          │
├──────────────────────┬──────────────────────────────────────────┬────────────┤
│ Layers & filters     │              UK map                      │ Detail     │
│ Attention            │      counties / local authorities         │ London     │
│  ● Climate change    │       ● article mention                  │ 12–18 Jul  │
│  ○ Clean transport   │           ▲ event                        │ 1.24% topic │
│  ○ Cost of living    │                                          │ 8,410 total │
│ Physical             │  ─────────────────────────────────────   │ Sources     │
│  □ Temperature       │      Date: 18 Jul 2025                    │ GDELT      │
│  □ NDVI / grass      │                                          │ ONS geo     │
│  □ Flood footprint   │                                          │ Open timeline│
│ Events               │                                          │ Open articles│
│  □ Wildfire          │                                          │             │
│  □ Policy            │                                          │             │
│  □ Transport         │      [Filter layers and events]          │             │
├──────────────────────┴──────────────────────────────────────────┴────────────┤
│ [◀] [▶ Play] [▶]  2022 ──────────────●────────────── Today  [18 Jul 2025]  │
│ Step [day/week/month]  Speed [1×/2×/4×]  Window [date/7-day/30-day]        │
│ Map meaning: outlet location · article-mentioned place · event location      │
└──────────────────────────────────────────────────────────────────────────────┘
~~~

### Map modes

The map offers three explicit modes:

1. Attention by place: topic share, article count or channel measure associated with the selected geography.
2. Physical conditions: temperature anomaly, vegetation condition, flood or burned footprint.
3. Events and disruption: hazard, policy, election, transport, launch or geopolitical event.

The left panel supports selecting a base metric and optional overlays, then filtering each layer by topic, source, geography, event type and source-specific fields. Event filters can use date, severity, status, affected area and category where those fields exist. Show a live count of matching areas or events. Keep filter chips visible after the panel closes. Reset one layer without clearing the whole map.

Each layer shows its source, unit, spatial and time resolution, aggregation window, available date range and last update. A layer is selectable only when its geography and time resolution are compatible with the current view; otherwise explain what is unavailable. The legend updates to the selected layer, metric, scale and date.

### Time controls and playback

- The date picker jumps to a specific valid date. The scrubber spans the selected layer’s available range, with missing or unavailable intervals visibly marked.
- Previous/Next steps by the chosen day, week or month interval. A single-date, rolling 7-day or rolling 30-day window is selectable where meaningful.
- Play advances one interval at a time. Speed options are 1×, 2× and 4×. Pause stops on the current frame; changing the layer, filters or date pauses playback.
- The date label, map colors, legend, event markers, detail drawer and linked mini-timeline update together. The selected area remains selected while playing.
- Playback pauses on missing data and shows the gap by default. A skip-gaps option may be added later if the behavior is explicit.
- The URL and saved view store the current date and playback configuration; playback itself does not change a saved view until the user saves.
- Respect reduced-motion settings and make Play/Pause, scrubber and date selection keyboard accessible.

Avoid implying daily precision when a layer is weekly, monthly or irregular. The displayed frame names its actual observation period and age.

### Geography rules

- Use versioned ONS boundaries across England, Scotland, Wales and Northern Ireland.
- Provide nation, county and local-authority selectors.
- Distinguish local publisher location, article-mentioned place and event location in the legend and detail drawer.
- Do not describe national media counts as county audience attention.
- Show the geographic coverage denominator beside any local percentage.
- State whether a place came from article extraction or an associated event.

### Map detail drawer

Selecting a county, local authority or event opens a drawer with the selected geography and current frame/window, attention measures and denominator, source and outlet mix, physical conditions, events, a small linked timeline, article examples and an Open in timeline action that preserves the current date, filters and layers. During playback, the drawer updates its value and source period without jumping to a different place.

The drawer keeps the map visible while the user inspects the selection.

### First-build scope

Start with UK geography, a news attention layer, date picker, scrubber, Play/Pause, interval stepping, topic/geography/source filtering, a selected geography summary and links into the timeline. Add physical layers once their spatial resolution, update cadence and missingness rules are agreed. The first build can use fixture dates to establish playback behavior.

## Event and article detail

Event detail is shared by the map and timeline. It contains:

- event name, type, source and dates;
- affected geography;
- severity measure with its original unit;
- attention before, during and after the event;
- channel comparison;
- related physical observations;
- complete and missing days;
- article evidence.

Article detail shows the URL, title, publisher, publication date, topic matches, political signal matches and geographic evidence. If full text is unavailable, show “not available” rather than “does not mention”.

## Saved views and publication workflow

Saved views are analytical specifications, not screenshots. A timeline view stores its title, subtitle, both axis definitions, each series and its color/style, geography, date range, aggregation, metric formulas, event-set filters, custom events, annotations and dataset release. A map view stores selected date, time step, playback speed, time window, base metric, overlay layers, filters, geography level, selected place and dataset release. Both store notes, owner and timestamps.

The saved view page offers reopen, duplicate and edit, copy link, export chart, export data and a short methods note describing the denominator and sources. This is central to publication work because a chart must remain reproducible after a data refresh.

## Data and methods screens

### Data

The Data screen is an operational catalogue showing source and provider, date range, last successful refresh, expected and observed days, record count, geography coverage, freshness, known gaps, current release identifier and download or API status.

Use clear statuses such as Complete, Partial, Delayed, Access required and Not yet integrated.

### Methods

The Methods screen explains topic definitions and test-phrase status, original-language matching and translation limitations, precision and recall review plans, outlet-to-country attribution, denominator definition, article deduplication, missingness, event timing and severity, standardisation and lag calculations, and causal and predictive limits.

Every chart’s method label should link to the relevant definition.

## Shared states

Every screen needs four explicit states:

- Loading: show the requested date range, source and release being loaded.
- Partial: show the chart with a visible completeness message and gaps.
- Unavailable: explain missing access, unsupported geography or unavailable history.
- Error: provide the failed run, source and retry action.

The empty state should tell the user what decision is needed, such as selecting a topic, requesting Trends access or choosing a geography with available data.

## First build route map

The first useful release can expose:

- /timeline
- /map
- /data
- /methods
- /views/:id once saved views exist

The timeline is the default route. A future event route can open from either main screen while preserving the current analytical specification.

## Visual and interaction principles

- Keep the chart or map as the dominant surface.
- Put controls close to the analysis they change.
- Use a small number of persistent controls and open detailed configuration on demand.
- Pair color with labels, line style or shape.
- Make source, unit, denominator, time grain and freshness visible near the value.
- Offer a simple default view while allowing Power BI-like control in focused builders for series, axes, events, layers and appearance.
- Preserve filters when moving between map, timeline, event and article evidence.
- Design for a 320px mobile width by stacking controls and turning drawers into full-screen panels.
- Ensure every important action works by keyboard and every visual has an accessible description.
- Keep research caveats near the relevant output rather than hiding them in a help page.
