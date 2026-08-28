import { useEffect, useMemo, useState } from 'react'
import { Activity, CircleAlert, Info } from 'lucide-react'
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchAttentionWindow, fetchRegionAttention } from './supabase'
import type { AttentionObservation, RegionAttentionObservation } from './supabase'
import { formatAxisDate, monthTicks } from './analysisTime'

type Topic = 'climate_change' | 'electric_vehicles'
type Measure = 'matched' | 'political'
type PlaceScope = 'world' | 'eu27' | 'country' | 'group'
type Hazard = 'all' | 'wildfire' | 'flood'
type AlertScope = 'major' | 'all' | 'green'
type ComparisonMode = 'single' | 'topics' | 'countries'
type RollingWindow = 1 | 7 | 14 | 28
type MarkerMode = 'alert' | 'wildfire_size'
type WildfireSizeBand = 'all' | 'under_5k' | '5k_10k' | '10k_50k' | '50k_plus'

type KeyEvent = {
  id: string
  name: string
  hazardType: 'wildfire' | 'flood'
  alertLevel: 'Green' | 'Orange' | 'Red'
  startAt: string
  geographyIds: string[]
  severity?: number | null
  severityUnit?: string | null
}

type TooltipEvent = Pick<KeyEvent, 'name' | 'alertLevel' | 'hazardType' | 'severity' | 'severityUnit'>

type TimelineTooltipPoint = {
  date: string
  values: Record<string, number | null>
  eventItems: TooltipEvent[]
  eventCount: number
}

type TimelineTooltipEntry = { payload?: TimelineTooltipPoint }
type TimelineSeries = {
  key: string
  label: string
  color: string
  topic: Topic
  locations: string[]
}

const TOPICS: Record<Topic, { label: string; color: string }> = {
  climate_change: { label: 'Climate change', color: '#286e59' },
  electric_vehicles: { label: 'Electric vehicles', color: '#6575b7' },
}

const EU27 = new Set([
  'austria', 'belgium', 'bulgaria', 'croatia', 'cyprus', 'czechrepublic',
  'denmark', 'estonia', 'finland', 'france', 'germany', 'greece', 'hungary',
  'ireland', 'italy', 'latvia', 'lithuania', 'luxembourg', 'malta',
  'netherlands', 'poland', 'portugal', 'romania', 'slovakia', 'slovenia',
  'spain', 'sweden',
])

const GDELT_OUTAGE = { start: '2025-06-14', end: '2025-07-01' }
const MAX_GROUP_COUNTRIES = 8
const COUNTRY_COLORS = ['#286e59', '#6575b7', '#c56f42', '#8a6aa8', '#2f8791', '#a46b3d', '#596f9f', '#80954f']
const ALERT_COLORS: Record<KeyEvent['alertLevel'], string> = {
  Green: '#789342',
  Orange: '#bd8b3b',
  Red: '#b6523b',
}
const SIZE_BANDS: Record<Exclude<WildfireSizeBand, 'all'>, { label: string; color: string; rank: number }> = {
  under_5k: { label: 'Under 5,000 ha', color: '#9b8bc2', rank: 0 },
  '5k_10k': { label: '5,000–9,999 ha', color: '#7b6bb3', rank: 1 },
  '10k_50k': { label: '10,000–49,999 ha', color: '#5c4695', rank: 2 },
  '50k_plus': { label: '50,000+ ha', color: '#372466', rank: 3 },
}

export function wildfireSizeBand(event: Pick<KeyEvent, 'hazardType' | 'severity' | 'severityUnit'>): Exclude<WildfireSizeBand, 'all'> | null {
  if (event.hazardType !== 'wildfire' || event.severity == null || event.severityUnit !== 'ha') return null
  if (event.severity < 5_000) return 'under_5k'
  if (event.severity < 10_000) return '5k_10k'
  if (event.severity < 50_000) return '10k_50k'
  return '50k_plus'
}

const shiftDate = (value: string, days: number) => {
  const result = new Date(`${value}T00:00:00Z`)
  result.setUTCDate(result.getUTCDate() + days)
  return result.toISOString().slice(0, 10)
}

const dateRange = (start: string, end: string) => {
  const values: string[] = []
  for (let day = start; day <= end; day = shiftDate(day, 1)) values.push(day)
  return values
}

const compactCount = (value: number) => new Intl.NumberFormat('en-GB', {
  notation: value >= 10_000 ? 'compact' : 'standard',
  maximumFractionDigits: 1,
}).format(value)

export function rollingAverageValues(values: (number | null)[], windowDays: RollingWindow) {
  return values.map((_, index) => {
    const window = values.slice(Math.max(0, index - windowDays + 1), index + 1)
    if (window.length !== windowDays || window.some((value) => value == null)) return null
    return window.reduce<number>((total, value) => total + Number(value), 0) / windowDays
  })
}

function TimelineTooltip({
  active,
  payload,
  label,
  measure,
  series,
  rollingWindow,
  markerMode,
}: {
  active?: boolean
  payload?: TimelineTooltipEntry[]
  label?: string | number
  measure: Measure
  series: TimelineSeries[]
  rollingWindow: RollingWindow
  markerMode: MarkerMode
}) {
  const point = payload?.find((entry) => entry.payload)?.payload
  if (!active || !point) return null
  const visibleEvents = point.eventItems.slice(0, 5)
  return (
    <div className="timeline-tooltip">
      <strong>{new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(String(label)))}</strong>
      <div className="timeline-tooltip-series">
        {series.map((item) => {
          const value = point.values[item.key]
          if (value == null) return null
          return <span key={item.key}><i style={{ background: item.color }} /><span>{item.label}<small>{rollingWindow === 1 ? (measure === 'matched' ? 'Matching articles' : 'Political articles') : `${rollingWindow}-day average`}</small></span><b>{value.toLocaleString('en-GB', { maximumFractionDigits: rollingWindow === 1 ? 0 : 1 })}</b></span>
        })}
      </div>
      {visibleEvents.length > 0 && <div className="timeline-tooltip-events">
        <small>{point.eventCount} event{point.eventCount === 1 ? '' : 's'} started</small>
        {visibleEvents.map((event, index) => {
          const sizeBand = wildfireSizeBand(event)
          const markerColor = markerMode === 'wildfire_size' && sizeBand ? SIZE_BANDS[sizeBand].color : ALERT_COLORS[event.alertLevel]
          const sizeLabel = event.severity != null && event.severityUnit === 'ha' ? ` · ${event.severity.toLocaleString('en-GB')} ha` : ''
          return <span key={`${event.name}-${index}`}><i style={{ background: markerColor }} /><span>{event.name}<small>{event.alertLevel} · {event.hazardType === 'wildfire' ? 'Wildfire' : 'Flood'}{sizeLabel}</small></span></span>
        })}
        {point.eventCount > visibleEvents.length && <em>+{point.eventCount - visibleEvents.length} more events</em>}
      </div>}
    </div>
  )
}

export default function AttentionTimeline({
  coverageStart,
  coverageEnd,
  geographyLabels,
  keyEvents,
}: {
  coverageStart: string
  coverageEnd: string
  geographyLabels: Record<string, string>
  keyEvents: KeyEvent[]
}) {
  const countryOptions = useMemo(() => Object.keys(geographyLabels).sort((left, right) =>
    (geographyLabels[left] || left).localeCompare(geographyLabels[right] || right),
  ), [geographyLabels])
  const preferred = ['unitedkingdom', 'france', 'germany'].filter((country) => countryOptions.includes(country))
  const [placeScope, setPlaceScope] = useState<PlaceScope>('world')
  const [country, setCountry] = useState(preferred[0] || countryOptions[0] || '')
  const [groupCountries, setGroupCountries] = useState<string[]>(() =>
    [...preferred, ...countryOptions.filter((item) => !preferred.includes(item))].slice(0, 3),
  )
  const [comparisonMode, setComparisonMode] = useState<ComparisonMode>('single')
  const [topic, setTopic] = useState<Topic>('climate_change')
  const [measure, setMeasure] = useState<Measure>('matched')
  const [rollingWindow, setRollingWindow] = useState<RollingWindow>(1)
  const [hazard, setHazard] = useState<Hazard>('all')
  const [alerts, setAlerts] = useState<AlertScope>('major')
  const [markerMode, setMarkerMode] = useState<MarkerMode>('alert')
  const [sizeBand, setSizeBand] = useState<WildfireSizeBand>('all')
  const [attentionRows, setAttentionRows] = useState<(AttentionObservation | RegionAttentionObservation)[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const activeLocations = useMemo(() => {
    if (comparisonMode === 'countries') return groupCountries
    if (placeScope === 'world') return ['__global__']
    if (placeScope === 'eu27') return ['__eu27__']
    if (placeScope === 'country') return country ? [country] : []
    return groupCountries
  }, [comparisonMode, country, groupCountries, placeScope])

  const requestedTopics = useMemo<Topic[]>(
    () => comparisonMode === 'topics' ? ['climate_change', 'electric_vehicles'] : [topic],
    [comparisonMode, topic],
  )

  const series = useMemo<TimelineSeries[]>(() => {
    if (comparisonMode === 'topics') return requestedTopics.map((item) => ({
      key: `topic_${item}`,
      label: TOPICS[item].label,
      color: TOPICS[item].color,
      topic: item,
      locations: activeLocations,
    }))
    if (comparisonMode === 'countries') return activeLocations.map((location, index) => ({
      key: `country_${location}`,
      label: geographyLabels[location] || location,
      color: COUNTRY_COLORS[index % COUNTRY_COLORS.length],
      topic,
      locations: [location],
    }))
    return [{ key: 'attention', label: TOPICS[topic].label, color: TOPICS[topic].color, topic, locations: activeLocations }]
  }, [activeLocations, comparisonMode, geographyLabels, requestedTopics, topic])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    const usesRegion = comparisonMode !== 'countries' && (placeScope === 'world' || placeScope === 'eu27')
    const request = usesRegion
      ? fetchRegionAttention(placeScope === 'world' ? 'global' : 'eu27', coverageStart, coverageEnd)
      : fetchAttentionWindow({ start: coverageStart, end: coverageEnd, geographies: activeLocations, topics: requestedTopics })
    request
      .then((rows) => {
        if (active) setAttentionRows(rows)
      })
      .catch(() => {
        if (!active) return
        setAttentionRows([])
        setError('Daily attention data is not available from Supabase yet.')
      })
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [activeLocations, comparisonMode, coverageEnd, coverageStart, placeScope, requestedTopics])

  const relevantEvents = useMemo(() => keyEvents.filter((event) => {
    const eventDate = event.startAt.slice(0, 10)
    if (eventDate < coverageStart || eventDate > coverageEnd) return false
    if (alerts === 'major' && event.alertLevel === 'Green') return false
    if (alerts === 'green' && event.alertLevel !== 'Green') return false
    if (hazard !== 'all' && event.hazardType !== hazard) return false
    if (markerMode === 'wildfire_size') {
      const eventSizeBand = wildfireSizeBand(event)
      if (!eventSizeBand || (sizeBand !== 'all' && eventSizeBand !== sizeBand)) return false
    }
    if (comparisonMode !== 'countries' && placeScope === 'world') return true
    if (comparisonMode !== 'countries' && placeScope === 'eu27') return event.geographyIds.some((item) => EU27.has(item))
    return event.geographyIds.some((item) => activeLocations.includes(item))
  }), [activeLocations, alerts, comparisonMode, coverageEnd, coverageStart, hazard, keyEvents, markerMode, placeScope, sizeBand])

  const eventDates = useMemo(() => {
    const grouped = new Map<string, KeyEvent[]>()
    for (const event of relevantEvents) {
      const day = event.startAt.slice(0, 10)
      grouped.set(day, [...(grouped.get(day) ?? []), event])
    }
    return grouped
  }, [relevantEvents])

  const plottedPoints = useMemo(() => {
    const bySeriesSource = new Map<string, Map<string, AttentionObservation | RegionAttentionObservation>>()
    for (const row of attentionRows) {
      const rowLocation = 'geography' in row
        ? row.geography
        : row.regionId === 'global' ? '__global__' : '__eu27__'
      const sourceKey = `${rowLocation}:${row.topicId}`
      const byDate = bySeriesSource.get(sourceKey) ?? new Map<string, AttentionObservation | RegionAttentionObservation>()
      byDate.set(row.date, row)
      bySeriesSource.set(sourceKey, byDate)
    }
    const rawPoints = dateRange(coverageStart, coverageEnd).map((date) => {
      const values: Record<string, number | null> = {}
      for (const item of series) {
        const rows = item.locations.map((location) => bySeriesSource.get(`${location}:${item.topic}`)?.get(date))
        values[item.key] = !item.locations.length || rows.some((row) => !row)
          ? null
          : rows.reduce((total, row) => total + Number(measure === 'matched' ? row?.matchedCount ?? 0 : row?.politicalCount ?? 0), 0)
      }
      return { date, values }
    })
    const smoothedValues = new Map(series.map((item) => [
      item.key,
      rollingAverageValues(rawPoints.map((point) => point.values[item.key]), rollingWindow),
    ]))
    return rawPoints.map((point, index) => {
      const values: Record<string, number | null> = {}
      for (const item of series) {
        values[item.key] = smoothedValues.get(item.key)?.[index] ?? null
      }
      return { ...point, values, ...values }
    })
  }, [attentionRows, coverageEnd, coverageStart, measure, rollingWindow, series])

  const observedValues = plottedPoints.flatMap((point) => series.flatMap((item) => point.values[item.key] == null ? [] : [point.values[item.key] as number]))
  const plottedPeak = observedValues.length ? Math.max(...observedValues) : 0
  const plottedAverage = observedValues.length
    ? observedValues.reduce((total, value) => total + value, 0) / observedValues.length
    : 0
  const missingDays = plottedPoints.filter((point) => series.some((item) => point.values[item.key] == null)).length
  const markerHeight = plottedPeak > 0 ? plottedPeak * 0.975 : 0
  const chartPoints = plottedPoints.map((point) => {
    const events = eventDates.get(point.date)
    const isRed = events?.some((event) => event.alertLevel === 'Red') ?? false
    const isOrange = events?.some((event) => event.alertLevel === 'Orange') ?? false
    const largestSizeBand = events
      ?.map(wildfireSizeBand)
      .filter((value): value is Exclude<WildfireSizeBand, 'all'> => value != null)
      .sort((left, right) => SIZE_BANDS[right].rank - SIZE_BANDS[left].rank)[0]
    return {
      ...point,
      greenEvent: markerMode === 'alert' && events && !isRed && !isOrange ? markerHeight : null,
      orangeEvent: markerMode === 'alert' && events && !isRed && isOrange ? markerHeight : null,
      redEvent: markerMode === 'alert' && events && isRed ? markerHeight : null,
      sizeUnder5k: markerMode === 'wildfire_size' && largestSizeBand === 'under_5k' ? markerHeight : null,
      size5k10k: markerMode === 'wildfire_size' && largestSizeBand === '5k_10k' ? markerHeight : null,
      size10k50k: markerMode === 'wildfire_size' && largestSizeBand === '10k_50k' ? markerHeight : null,
      size50kPlus: markerMode === 'wildfire_size' && largestSizeBand === '50k_plus' ? markerHeight : null,
      eventItems: events?.map(({ name, alertLevel, hazardType, severity, severityUnit }) => ({ name, alertLevel, hazardType, severity, severityUnit })) ?? [],
      eventCount: events?.length ?? 0,
    }
  })
  const placeLabel = placeScope === 'world'
    ? 'World'
    : placeScope === 'eu27'
      ? 'EU27'
      : placeScope === 'country'
        ? geographyLabels[country] || country
        : `${groupCountries.length}-country group`
  const chartTitle = comparisonMode === 'topics'
    ? `Topic comparison in ${placeLabel}`
    : comparisonMode === 'countries'
      ? `${TOPICS[topic].label} across ${groupCountries.length} countries`
      : `${TOPICS[topic].label} in ${placeLabel}`
  const frequencyLabel = rollingWindow === 1 ? 'Daily attention' : `${rollingWindow}-day rolling average`
  const axisTicks = useMemo(() => monthTicks(coverageStart, coverageEnd), [coverageEnd, coverageStart])
  const multiYearAxis = coverageStart.slice(0, 4) !== coverageEnd.slice(0, 4)

  const addGroupCountry = (selected: string) => {
    if (!selected || groupCountries.includes(selected) || groupCountries.length >= MAX_GROUP_COUNTRIES) return
    setGroupCountries((current) => [...current, selected])
  }

  const updateMarkerMode = (mode: MarkerMode) => {
    setMarkerMode(mode)
    if (mode === 'wildfire_size') {
      setHazard('wildfire')
      setAlerts('all')
    }
  }

  const eventMarkerColor = (events: KeyEvent[]) => {
    if (markerMode === 'alert') {
      if (events.some((event) => event.alertLevel === 'Red')) return ALERT_COLORS.Red
      if (events.some((event) => event.alertLevel === 'Orange')) return ALERT_COLORS.Orange
      return ALERT_COLORS.Green
    }
    const largest = events.map(wildfireSizeBand)
      .filter((value): value is Exclude<WildfireSizeBand, 'all'> => value != null)
      .sort((left, right) => SIZE_BANDS[right].rank - SIZE_BANDS[left].rank)[0]
    return largest ? SIZE_BANDS[largest].color : SIZE_BANDS.under_5k.color
  }

  return (
    <section className="timeline-workspace">
      <aside className="timeline-controls">
        <div className="lab-section-heading"><span>1</span><div><small>Observed publishing</small><h2>Configure timeline</h2></div></div>
        <div className="lab-form">
          <label><span>Lines</span><select aria-label="Timeline lines" value={comparisonMode} onChange={(event) => setComparisonMode(event.target.value as ComparisonMode)}><option value="single">One topic</option><option value="topics">Compare climate and EVs</option><option value="countries">Compare countries</option></select></label>
          {comparisonMode !== 'countries' && <label><span>Geography</span><select value={placeScope} onChange={(event) => setPlaceScope(event.target.value as PlaceScope)}><option value="world">World</option><option value="eu27">EU27</option><option value="country">Single country</option><option value="group">Combined country group</option></select></label>}
          {comparisonMode !== 'countries' && placeScope === 'country' && <label><span>Country</span><select value={country} onChange={(event) => setCountry(event.target.value)}>{countryOptions.map((item) => <option key={item} value={item}>{geographyLabels[item] || item}</option>)}</select></label>}
          {(comparisonMode === 'countries' || placeScope === 'group') && <>
            <label><span>Add country</span><select aria-label="Add timeline country" value="" disabled={groupCountries.length >= MAX_GROUP_COUNTRIES} onChange={(event) => addGroupCountry(event.target.value)}><option value="">{groupCountries.length >= MAX_GROUP_COUNTRIES ? 'Eight-country maximum' : 'Choose a country…'}</option>{countryOptions.filter((item) => !groupCountries.includes(item)).map((item) => <option key={item} value={item}>{geographyLabels[item] || item}</option>)}</select></label>
            <div className="comparison-country-list" aria-label="Timeline country group">{groupCountries.map((item) => <span key={item}>{geographyLabels[item] || item}<button type="button" aria-label={`Remove ${geographyLabels[item] || item}`} disabled={groupCountries.length <= 2} onClick={() => setGroupCountries((current) => current.filter((value) => value !== item))}>×</button></span>)}</div>
          </>}
          {comparisonMode !== 'topics' && <label><span>Attention topic</span><select value={topic} onChange={(event) => setTopic(event.target.value as Topic)}>{Object.entries(TOPICS).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select></label>}
          <label><span>Attention measure</span><select value={measure} onChange={(event) => setMeasure(event.target.value as Measure)}><option value="matched">All matching articles</option><option value="political">Political articles</option></select></label>
          <label><span>Time aggregation</span><select value={rollingWindow} onChange={(event) => setRollingWindow(Number(event.target.value) as RollingWindow)}><option value="1">Daily count</option><option value="7">7-day rolling average</option><option value="14">14-day rolling average</option><option value="28">28-day rolling average</option></select><small>Rolling averages remain daily lines and require a complete trailing window.</small></label>
          <label><span>Event marker category</span><select value={markerMode} onChange={(event) => updateMarkerMode(event.target.value as MarkerMode)}><option value="alert">GDACS alert tier</option><option value="wildfire_size">Wildfire burned area</option></select><small>Burned-area categories use the provider’s hectares field. Comparable flood size is not available in the current export.</small></label>
          <label><span>Event alert tier</span><select value={alerts} onChange={(event) => setAlerts(event.target.value as AlertScope)}><option value="all">All tiers · Green, Orange, Red</option><option value="major">Major tiers · Orange and Red</option><option value="green">Green tier only</option></select><small>Green is a lower humanitarian-impact tier, not an absence of an event.</small></label>
          <label><span>Event type</span><select value={markerMode === 'wildfire_size' ? 'wildfire' : hazard} disabled={markerMode === 'wildfire_size'} onChange={(event) => setHazard(event.target.value as Hazard)}><option value="all">Floods and wildfires</option><option value="flood">Floods</option><option value="wildfire">Wildfires</option></select></label>
          {markerMode === 'wildfire_size' && <label><span>Wildfire size</span><select value={sizeBand} onChange={(event) => setSizeBand(event.target.value as WildfireSizeBand)}><option value="all">All burned areas</option>{Object.entries(SIZE_BANDS).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select></label>}
        </div>
        <div className="analysis-definition"><Info size={15} /><p><strong>Comparable observed attention.</strong> Choose separate lines for topics or publishing markets. Rolling averages smooth weekday volatility but never bridge missing provider dates. {markerMode === 'alert' ? 'Event colours show GDACS impact tiers, whose rules differ by hazard.' : 'Event colours show wildfire burned-area bands; flood size is not inferred.'}</p></div>
      </aside>

      <div className="timeline-results">
        {loading ? <div className="activity-state"><Activity size={20} /> Loading daily attention…</div> : error ? <div className="activity-state error"><CircleAlert size={20} /><strong>Attention timeline unavailable</strong><p>{error}</p></div> : <section className="timeline-chart-card">
          <div className="result-heading"><div><span className="eyebrow">{frequencyLabel}</span><h2>{chartTitle}</h2></div><div className="timeline-total"><strong>{series.length === 1 ? compactCount(Math.round(plottedAverage)) : `${series.length} lines`}</strong><small>{series.length === 1 ? `average ${measure === 'matched' ? 'matching' : 'political'} articles/day · peak ${compactCount(plottedPeak)}` : `${frequencyLabel.toLowerCase()} · ${measure === 'matched' ? 'matching' : 'political'} articles`} · {relevantEvents.length} events</small></div></div>
          <div className="timeline-chart" role="img" aria-label={`${frequencyLabel} for ${chartTitle.toLowerCase()} with event markers`}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartPoints} margin={{ top: 20, right: 18, bottom: 2, left: 4 }}>
                <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="date" ticks={axisTicks} tickFormatter={(value) => formatAxisDate(String(value), multiYearAxis)} minTickGap={38} tick={{ fontSize: 9, fill: '#738179' }} />
                <YAxis domain={[0, 'auto']} width={56} tickFormatter={(value) => compactCount(Number(value))} tick={{ fontSize: 9, fill: '#738179' }} />
                <Tooltip content={<TimelineTooltip measure={measure} series={series} rollingWindow={rollingWindow} markerMode={markerMode} />} />
                {coverageStart <= GDELT_OUTAGE.end && coverageEnd >= GDELT_OUTAGE.start && <ReferenceArea x1={GDELT_OUTAGE.start} x2={GDELT_OUTAGE.end} fill="#70879a" fillOpacity={0.13} stroke="#60798d" strokeOpacity={0.55} label={{ value: 'Provider gap', position: 'insideTop', fill: '#506879', fontSize: 8 }} />}
                {[...eventDates.entries()].map(([date, events]) => <ReferenceLine key={date} x={date} stroke={eventMarkerColor(events)} strokeWidth={1} strokeDasharray="3 4" strokeOpacity={0.62} />)}
                {series.map((item) => <Line key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={2.3} dot={false} connectNulls={false} />)}
                <Scatter dataKey="greenEvent" name="Events" legendType="none" fill="#789342" shape="diamond" />
                <Scatter dataKey="orangeEvent" name="Events" legendType="none" fill="#bd8b3b" shape="diamond" />
                <Scatter dataKey="redEvent" name="Events" legendType="none" fill="#b6523b" shape="diamond" />
                <Scatter dataKey="sizeUnder5k" name="Events" legendType="none" fill={SIZE_BANDS.under_5k.color} shape="diamond" />
                <Scatter dataKey="size5k10k" name="Events" legendType="none" fill={SIZE_BANDS['5k_10k'].color} shape="diamond" />
                <Scatter dataKey="size10k50k" name="Events" legendType="none" fill={SIZE_BANDS['10k_50k'].color} shape="diamond" />
                <Scatter dataKey="size50kPlus" name="Events" legendType="none" fill={SIZE_BANDS['50k_plus'].color} shape="diamond" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="timeline-series-key">{series.map((item) => <span key={item.key}><i style={{ borderColor: item.color }} />{item.label}</span>)}</div>
          <div className="timeline-key">
            {markerMode === 'alert' ? <><span><i style={{ borderColor: ALERT_COLORS.Green }} />Green tier</span><span><i style={{ borderColor: ALERT_COLORS.Orange }} />Orange tier</span><span><i style={{ borderColor: ALERT_COLORS.Red }} />Red tier</span></> : Object.values(SIZE_BANDS).map((item) => <span key={item.label}><i style={{ borderColor: item.color }} />{item.label}</span>)}
            {coverageStart <= GDELT_OUTAGE.end && coverageEnd >= GDELT_OUTAGE.start && <span className="provider-gap-key"><i />Provider gap</span>}
            <small>Hover a diamond for event names · {missingDays} unavailable day{missingDays === 1 ? '' : 's'} excluded</small>
          </div>
        </section>}
      </div>
    </section>
  )
}
