import { useEffect, useMemo, useState } from 'react'
import { Activity, BarChart3, CircleAlert, Info } from 'lucide-react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  fetchAttentionWindow,
  fetchEventActivity,
  fetchRegionAttention,
} from './supabase'
import type {
  AttentionObservation,
  EventActivityObservation,
  RegionAttentionObservation,
} from './supabase'
import { formatAxisDate, monthTicks } from './analysisTime'

type Hazard = 'all' | 'wildfire' | 'flood'
type Cohort = 'major' | 'green' | 'all'
type Measure = 'matched' | 'political' | 'political_share'
type Topic = 'climate_change' | 'electric_vehicles'
type PlaceMode = 'single' | 'compare'
type ScaleMode = 'focus' | 'full'
type AttentionDetail = 'average' | 'daily'

const TOPICS: Record<Topic, { label: string; color: string }> = {
  climate_change: { label: 'Climate change', color: '#286e59' },
  electric_vehicles: { label: 'Electric vehicles', color: '#6575b7' },
}

const COHORT_ALERTS: Record<Cohort, EventActivityObservation['alertLevel'][]> = {
  major: ['Orange', 'Red'],
  green: ['Green'],
  all: ['Green', 'Orange', 'Red'],
}

const GDELT_OUTAGE = { start: '2025-06-14', end: '2025-07-01' }
const COUNTRY_COLORS = ['#286e59', '#6575b7', '#c56f42', '#8a6aa8', '#2f8791']
const MAX_COMPARISON_COUNTRIES = 5
const ATTENTION_AVERAGE_DAYS = 7
const NEGLIGIBLE_CORRELATION = 0.1

const eventKey = (location: string) => `events_${location}`
const attentionKey = (location: string, topic: Topic) => `attention_${location}_${topic}`

const shiftDate = (value: string, days: number) => {
  const result = new Date(`${value}T00:00:00Z`)
  result.setUTCDate(result.getUTCDate() + days)
  return result.toISOString().slice(0, 10)
}

const dateRange = (start: string, end: string) => {
  const dates: string[] = []
  for (let day = start; day <= end; day = shiftDate(day, 1)) dates.push(day)
  return dates
}

const mean = (values: number[]) => values.reduce((total, value) => total + value, 0) / values.length

function niceAxisBound(value: number, minimum: number) {
  const target = Math.max(Math.abs(value), minimum)
  const roughStep = target / 4
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const normalized = roughStep / magnitude
  const niceStep = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10) * magnitude
  return Math.ceil(target / niceStep) * niceStep
}

function symmetricBound(values: number[], quantile: number, minimum: number) {
  const magnitudes = values.filter(Number.isFinite).map((value) => Math.abs(value)).sort((left, right) => left - right)
  if (!magnitudes.length) return minimum
  const index = Math.min(magnitudes.length - 1, Math.ceil((magnitudes.length - 1) * quantile))
  return niceAxisBound(magnitudes[index], minimum)
}

function pearson(left: number[], right: number[]) {
  if (left.length < 10 || left.length !== right.length) return null
  const leftMean = mean(left)
  const rightMean = mean(right)
  const numerator = left.reduce((total, value, index) => total + (value - leftMean) * (right[index] - rightMean), 0)
  const denominator = Math.sqrt(
    left.reduce((total, value) => total + (value - leftMean) ** 2, 0) *
    right.reduce((total, value) => total + (value - rightMean) ** 2, 0),
  )
  return denominator ? numerator / denominator : null
}

function attentionValue(
  row: AttentionObservation | RegionAttentionObservation,
  measure: Measure,
) {
  if (measure === 'matched') return row.matchedCount
  if (measure === 'political') return row.politicalCount
  if ('politicalShare' in row) return row.politicalShare
  return row.matchedCount ? (Number(row.politicalCount ?? 0) / row.matchedCount) * 100 : null
}

function formatAnomaly(value: unknown, measure: Measure) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${number > 0 ? '+' : ''}${number.toFixed(1)}${measure === 'political_share' ? ' pp' : '%'}`
}

export default function EventActivityView({
  coverageStart,
  coverageEnd,
  geographyLabels,
  eventGeographies,
}: {
  coverageStart: string
  coverageEnd: string
  geographyLabels: Record<string, string>
  eventGeographies: string[]
}) {
  const countryOptions = useMemo(() => [...new Set(eventGeographies)].sort((left, right) =>
    (geographyLabels[left] || left).localeCompare(geographyLabels[right] || right),
  ), [eventGeographies, geographyLabels])
  const [location, setLocation] = useState('__global__')
  const [placeMode, setPlaceMode] = useState<PlaceMode>('single')
  const [comparisonTopic, setComparisonTopic] = useState<Topic>('climate_change')
  const [comparisonLocations, setComparisonLocations] = useState<string[]>(() => {
    const preferred = ['unitedkingdom', 'france', 'germany'].filter((country) => eventGeographies.includes(country))
    return [...preferred, ...eventGeographies.filter((country) => !preferred.includes(country))].slice(0, 3)
  })
  const [hazard, setHazard] = useState<Hazard>('all')
  const [cohort, setCohort] = useState<Cohort>('all')
  const [measure, setMeasure] = useState<Measure>('matched')
  const [scaleMode, setScaleMode] = useState<ScaleMode>('focus')
  const [attentionDetail, setAttentionDetail] = useState<AttentionDetail>('average')
  const [rollingDays, setRollingDays] = useState(28)
  const [activityRows, setActivityRows] = useState<EventActivityObservation[]>([])
  const [attentionRows, setAttentionRows] = useState<(AttentionObservation | RegionAttentionObservation)[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const start = coverageStart
  const end = coverageEnd
  const axisTicks = useMemo(() => monthTicks(start, end), [end, start])
  const multiYearAxis = start.slice(0, 4) !== end.slice(0, 4)
  const activeLocations = useMemo(
    () => placeMode === 'compare' ? comparisonLocations : [location],
    [comparisonLocations, location, placeMode],
  )

  useEffect(() => {
    if (comparisonLocations.length || !countryOptions.length) return
    setComparisonLocations(countryOptions.slice(0, Math.min(3, countryOptions.length)))
  }, [comparisonLocations.length, countryOptions])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    const regionalLocation = activeLocations.length === 1 && (activeLocations[0] === '__global__' || activeLocations[0] === '__eu27__')
      ? activeLocations[0]
      : null
    const attentionRequest = regionalLocation
      ? fetchRegionAttention(regionalLocation === '__global__' ? 'global' : 'eu27', start, end)
      : fetchAttentionWindow({ start, end, geographies: activeLocations, topics: Object.keys(TOPICS) })
    Promise.all([
      fetchEventActivity({
        geographies: activeLocations,
        start,
        end,
        alerts: COHORT_ALERTS[cohort],
        hazard: hazard === 'all' ? undefined : hazard,
      }),
      attentionRequest,
    ])
      .then(([events, attention]) => {
        if (!active) return
        setActivityRows(events)
        setAttentionRows(attention)
      })
      .catch(() => {
        if (!active) return
        setActivityRows([])
        setAttentionRows([])
        setError('The all-alert activity tables are not available from Supabase yet.')
      })
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [activeLocations, cohort, end, hazard, start])

  const points = useMemo(() => {
    const dates = dateRange(start, end)
    const activityByLocation = new Map<string, Map<string, { started: number; active: number }>>()
    for (const row of activityRows) {
      const activityByDate = activityByLocation.get(row.geography) ?? new Map<string, { started: number; active: number }>()
      const value = activityByDate.get(row.date) ?? { started: 0, active: 0 }
      value.started += row.eventsStarted
      value.active += row.eventsActive
      activityByDate.set(row.date, value)
      activityByLocation.set(row.geography, activityByDate)
    }
    const attentionByLocation = new Map<string, Map<string, Partial<Record<Topic, AttentionObservation | RegionAttentionObservation>>>>()
    for (const row of attentionRows) {
      if (!(row.topicId in TOPICS)) continue
      const rowLocation = 'geography' in row
        ? row.geography
        : row.regionId === 'global' ? '__global__' : '__eu27__'
      const attentionByDate = attentionByLocation.get(rowLocation) ?? new Map<string, Partial<Record<Topic, AttentionObservation | RegionAttentionObservation>>>()
      const value = attentionByDate.get(row.date) ?? {}
      value[row.topicId as Topic] = row
      attentionByDate.set(row.date, value)
      attentionByLocation.set(rowLocation, attentionByDate)
    }
    const rawByLocation = new Map<string, Record<Topic, (number | null)[]>>()
    for (const selectedLocation of activeLocations) {
      const attentionByDate = attentionByLocation.get(selectedLocation)
      rawByLocation.set(selectedLocation, {
        climate_change: dates.map((date) => {
          const row = attentionByDate?.get(date)?.climate_change
          return row ? attentionValue(row, measure) : null
        }),
        electric_vehicles: dates.map((date) => {
          const row = attentionByDate?.get(date)?.electric_vehicles
          return row ? attentionValue(row, measure) : null
        }),
      })
    }
    return dates.map((date, index) => {
      const point: Record<string, string | number | null> = {
        date,
      }
      for (const selectedLocation of activeLocations) {
        const activityByDate = activityByLocation.get(selectedLocation)
        point[eventKey(selectedLocation)] = dates.slice(Math.max(0, index - rollingDays + 1), index + 1)
          .reduce((total, day) => total + (activityByDate?.get(day)?.started ?? 0), 0)
        const rawByTopic = rawByLocation.get(selectedLocation)
        if (!rawByTopic) continue
        for (const topic of Object.keys(TOPICS) as Topic[]) {
          const value = rawByTopic[topic][index]
          const baseline = rawByTopic[topic]
            .slice(Math.max(0, index - 28), index)
            .filter((item): item is number => item != null)
          const key = attentionKey(selectedLocation, topic)
          if (value == null || baseline.length < 14) point[key] = null
          else {
            const baselineMean = mean(baseline)
            point[key] = measure === 'political_share'
              ? value - baselineMean
              : baselineMean ? ((value - baselineMean) / baselineMean) * 100 : null
          }
        }
      }
      return point
    })
  }, [activeLocations, activityRows, attentionRows, end, measure, rollingDays, start])

  const chartSeries = useMemo(() => placeMode === 'compare'
    ? activeLocations.map((selectedLocation, index) => ({
        key: attentionKey(selectedLocation, comparisonTopic),
        eventKey: eventKey(selectedLocation),
        location: selectedLocation,
        topic: comparisonTopic,
        label: geographyLabels[selectedLocation] || selectedLocation,
        color: COUNTRY_COLORS[index % COUNTRY_COLORS.length],
      }))
    : (Object.keys(TOPICS) as Topic[]).map((topic) => ({
        key: attentionKey(location, topic),
        eventKey: eventKey(location),
        location,
        topic,
        label: TOPICS[topic].label,
        color: TOPICS[topic].color,
      })),
  [activeLocations, comparisonTopic, geographyLabels, location, placeMode])

  const attentionPlotPoints = useMemo(() => {
    if (attentionDetail === 'daily') return points
    return points.map((point, index) => {
      const plottedPoint = { ...point }
      for (const series of chartSeries) {
        const window = points.slice(index - ATTENTION_AVERAGE_DAYS + 1, index + 1)
          .map((item) => item[series.key])
        plottedPoint[series.key] = window.length === ATTENTION_AVERAGE_DAYS && window.every((value) => typeof value === 'number' && Number.isFinite(value))
          ? mean(window as number[])
          : null
      }
      return plottedPoint
    })
  }, [attentionDetail, chartSeries, points])

  const attentionValues = useMemo(() => attentionPlotPoints.flatMap((point) => chartSeries
    .map((series) => point[series.key])
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))), [attentionPlotPoints, chartSeries])
  const attentionBound = useMemo(
    () => symmetricBound(attentionValues, scaleMode === 'focus' ? 0.98 : 1, measure === 'political_share' ? 2 : 25),
    [attentionValues, measure, scaleMode],
  )
  const attentionDomain: [number, number] = [-attentionBound, attentionBound]
  const clippedAttentionValues = scaleMode === 'focus'
    ? attentionValues.filter((value) => Math.abs(value) > attentionBound).length
    : 0

  const lagPoints = useMemo(() => Array.from({ length: 57 }, (_, index) => index - 28).map((lag) => {
    const result: Record<string, number | null> = { lag }
    for (const series of chartSeries) {
      const events: number[] = []
      const attention: number[] = []
      for (let index = 0; index < points.length; index += 1) {
        const attentionIndex = index + lag
        const eventValue = Number(points[index][series.eventKey])
        const attentionValueAtLag = points[attentionIndex]?.[series.key]
        if (attentionIndex >= 0 && attentionIndex < points.length && typeof attentionValueAtLag === 'number') {
          events.push(eventValue)
          attention.push(attentionValueAtLag)
        }
      }
      result[series.key] = pearson(events, attention)
    }
    return result
  }), [chartSeries, points])

  const totalStarts = activityRows.reduce((total, row) => total + row.eventsStarted, 0)
  const peakRolling = Math.max(0, ...points.flatMap((point) => activeLocations.map((selectedLocation) => Number(point[eventKey(selectedLocation)]))))
  const eventDomain: [number, number] = [0, Math.max(1, niceAxisBound(peakRolling, 1))]
  const lagValues = lagPoints.flatMap((point) => chartSeries
    .map((series) => point[series.key])
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value)))
  const lagBound = Math.min(1, symmetricBound(lagValues, 1, NEGLIGIBLE_CORRELATION))
  const lagDomain: [number, number] = [-lagBound, lagBound]
  const bestLag = chartSeries.map((series) => {
    const available = lagPoints.filter((point) => typeof point[series.key] === 'number')
    return {
      series,
      point: available.sort((left, right) => Math.abs(Number(right[series.key])) - Math.abs(Number(left[series.key])))[0],
    }
  })
  const strongestAssociation = bestLag.reduce<(typeof bestLag)[number] | null>((strongest, candidate) => {
    if (!candidate.point) return strongest
    if (!strongest?.point) return candidate
    return Math.abs(Number(candidate.point[candidate.series.key])) > Math.abs(Number(strongest.point[strongest.series.key]))
      ? candidate
      : strongest
  }, null)
  const strongestCorrelation = strongestAssociation?.point
    ? Math.abs(Number(strongestAssociation.point[strongestAssociation.series.key]))
    : null
  const associationLabel = strongestCorrelation == null
    ? 'Insufficient variation'
    : strongestCorrelation < NEGLIGIBLE_CORRELATION
      ? 'No clear association'
      : strongestCorrelation < 0.3
        ? 'Weak association'
        : strongestCorrelation < 0.5
          ? 'Moderate association'
          : 'Strong association'

  const addComparisonCountry = (country: string) => {
    if (!country || comparisonLocations.includes(country) || comparisonLocations.length >= MAX_COMPARISON_COUNTRIES) return
    setComparisonLocations((current) => [...current, country])
  }

  return (
    <section className="activity-workspace">
      <aside className="activity-controls">
        <div className="lab-section-heading"><span>1</span><div><small>Country-year panel</small><h2>Configure activity</h2></div></div>
        <div className="lab-form">
          <label><span>Place view</span><select value={placeMode} onChange={(event) => setPlaceMode(event.target.value as PlaceMode)}><option value="single">Single place</option><option value="compare">Compare countries</option></select></label>
          {placeMode === 'single' ? <label><span>Place</span><select value={location} onChange={(event) => setLocation(event.target.value)}><option value="__global__">Global</option><option value="__eu27__">EU27</option>{countryOptions.map((country) => <option key={country} value={country}>{geographyLabels[country] || country}</option>)}</select></label> : <>
            <label><span>Attention topic</span><select value={comparisonTopic} onChange={(event) => setComparisonTopic(event.target.value as Topic)}>{Object.entries(TOPICS).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select></label>
            <label><span>Add country</span><select aria-label="Add country" value="" disabled={comparisonLocations.length >= MAX_COMPARISON_COUNTRIES} onChange={(event) => addComparisonCountry(event.target.value)}><option value="">{comparisonLocations.length >= MAX_COMPARISON_COUNTRIES ? 'Five-country maximum' : 'Choose a country…'}</option>{countryOptions.filter((country) => !comparisonLocations.includes(country)).map((country) => <option key={country} value={country}>{geographyLabels[country] || country}</option>)}</select></label>
            <div className="comparison-country-list" aria-label="Countries being compared">{comparisonLocations.map((country, index) => <span key={country}><i style={{ background: COUNTRY_COLORS[index % COUNTRY_COLORS.length] }} />{geographyLabels[country] || country}<button type="button" aria-label={`Remove ${geographyLabels[country] || country}`} disabled={comparisonLocations.length <= 2} onClick={() => setComparisonLocations((current) => current.filter((item) => item !== country))}>×</button></span>)}</div>
          </>}
          <label><span>Event alert tier</span><select value={cohort} onChange={(event) => setCohort(event.target.value as Cohort)}><option value="all">All tiers · Green, Orange, Red</option><option value="major">Major tiers · Orange and Red</option><option value="green">Green tier only</option></select></label>
          <label><span>Event type</span><select value={hazard} onChange={(event) => setHazard(event.target.value as Hazard)}><option value="all">Floods and wildfires</option><option value="flood">Floods</option><option value="wildfire">Wildfires</option></select></label>
          <label><span>Attention measure</span><select value={measure} onChange={(event) => setMeasure(event.target.value as Measure)}><option value="matched">All matching articles</option><option value="political">Political articles</option><option value="political_share">Political share</option></select></label>
          <label><span>Attention view</span><select value={attentionDetail} onChange={(event) => setAttentionDetail(event.target.value as AttentionDetail)}><option value="average">7-day trailing average</option><option value="daily">Daily values</option></select><small>The average reduces day-to-day noise without filling provider gaps</small></label>
          <label><span>Attention scale</span><select value={scaleMode} onChange={(event) => setScaleMode(event.target.value as ScaleMode)}><option value="focus">Focus on typical range</option><option value="full">Show every extreme</option></select><small>{scaleMode === 'focus' ? 'Symmetric 98% range; extremes are flagged below the chart' : 'Symmetric range including every daily value'}</small></label>
          <label><span>Rolling event window</span><select value={rollingDays} onChange={(event) => setRollingDays(Number(event.target.value))}><option value={7}>7 days</option><option value={28}>28 days</option></select></label>
        </div>
        <div className="analysis-definition"><Info size={15} /><p><strong>Country exposure.</strong> Multi-country events count once in every affected country. Comparison mode separates rolling event load and attention into aligned panels for up to five countries.</p></div>
      </aside>

      <div className="activity-results">
        {loading ? <div className="activity-state"><Activity size={20} /> Loading country-day panel…</div> : error ? <div className="activity-state error"><CircleAlert size={20} /><strong>Activity panel unavailable</strong><p>{error}</p></div> : <>
          <div className="activity-kpis">
            <article><small>{placeMode === 'compare' ? 'Event-country starts' : 'Events started'}</small><strong>{totalStarts.toLocaleString()}</strong><span>{placeMode === 'compare' ? 'Country exposures; a multi-country event may repeat' : cohort === 'major' ? 'Major tiers · Orange and Red' : cohort === 'green' ? 'Green tier only' : 'All tiers · Green, Orange, Red'}</span></article>
            <article><small>Peak rolling load</small><strong>{peakRolling.toLocaleString()}</strong><span>{placeMode === 'compare' ? `Highest selected country within ${rollingDays} days` : `Starts within ${rollingDays} days`}</span></article>
            <article className="association-kpi"><small>Association across −28 to +28 days</small><strong>{associationLabel}</strong><span>{strongestCorrelation == null ? 'No usable lag correlations' : `Largest |r| = ${strongestCorrelation.toFixed(2)} across ${chartSeries.length} plotted series`}</span></article>
          </div>

          <section className="activity-chart-card">
            <div className="result-heading"><div><span className="eyebrow">Event activity and attention</span><h2>Event load and attention over time</h2></div><small>Aligned panels · no dual axis</small></div>
            <div className="activity-series-legend" aria-label={placeMode === 'compare' ? 'Country series' : 'Attention topics'}>
              {chartSeries.map((series) => <span key={series.key}><i style={{ background: series.color }} />{series.label}</span>)}
            </div>
            <div className="activity-chart-stack">
              <div className="activity-chart-panel event-load-panel">
                <div className="activity-panel-heading"><strong>{rollingDays}-day rolling event starts</strong><small>{placeMode === 'compare' ? 'One line per selected country' : 'Event load'}</small></div>
                <div className="event-load-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={points} margin={{ top: 6, right: 2, bottom: 0, left: 2 }}>
                      <CartesianGrid stroke="#e1e7e3" strokeDasharray="3 5" vertical={false} />
                      <XAxis dataKey="date" ticks={axisTicks} hide />
                      <YAxis yAxisId="spacer" width={45} tick={false} axisLine={false} />
                      <YAxis yAxisId="events" domain={eventDomain} orientation="right" width={45} allowDecimals={false} tick={{ fontSize: 8, fill: '#947542' }} />
                      <Tooltip labelFormatter={(value) => new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(String(value)))} formatter={(value, name) => [Number(value).toFixed(0), name]} />
                      {placeMode === 'single'
                        ? <Area yAxisId="events" type="linear" dataKey={eventKey(location)} name={`${rollingDays}-day event starts`} stroke="#b78f4b" strokeWidth={1.5} fill="#d7b878" fillOpacity={0.34} dot={false} />
                        : chartSeries.map((series) => <Line key={`events-${series.location}`} yAxisId="events" type="linear" dataKey={series.eventKey} name={series.label} stroke={series.color} strokeWidth={1.6} dot={false} connectNulls={false} />)}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="activity-chart-panel attention-panel">
                <div className="activity-panel-heading"><strong>Attention anomaly</strong><small>{attentionDetail === 'average' ? '7-day trailing average' : 'Daily values'} · compared with each day’s preceding 28-day baseline</small></div>
                <div className="attention-anomaly-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={attentionPlotPoints} margin={{ top: 6, right: 2, bottom: 0, left: 2 }}>
                      <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" vertical={false} />
                      <XAxis dataKey="date" ticks={axisTicks} tickFormatter={(value) => formatAxisDate(String(value), multiYearAxis)} minTickGap={38} tick={{ fontSize: 8, fill: '#738179' }} />
                      <YAxis domain={attentionDomain} allowDataOverflow width={45} tickFormatter={(value) => `${value > 0 ? '+' : ''}${Math.round(value)}${measure === 'political_share' ? ' pp' : '%'}`} tick={{ fontSize: 8, fill: '#738179' }} />
                      <YAxis yAxisId="spacer" orientation="right" width={45} tick={false} axisLine={false} />
                      <Tooltip labelFormatter={(value) => new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(String(value)))} formatter={(value, name) => [formatAnomaly(value, measure), name]} />
                      <ReferenceLine y={0} stroke="#9eaaa4" />
                      {start <= GDELT_OUTAGE.end && end >= GDELT_OUTAGE.start && <ReferenceArea x1={GDELT_OUTAGE.start} x2={GDELT_OUTAGE.end} fill="#70879a" fillOpacity={0.13} stroke="#60798d" strokeOpacity={0.55} label={{ value: 'Provider gap · excluded', position: 'insideTop', fill: '#506879', fontSize: 8 }} />}
                      {chartSeries.map((series) => <Line key={series.key} type="linear" dataKey={series.key} name={series.label} stroke={series.color} strokeWidth={2.2} dot={false} connectNulls={false} />)}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
            {scaleMode === 'focus' && <div className="chart-scale-note"><Info size={14} /><p><strong>Focused scale.</strong> The axis shows the symmetric 98% range of the plotted {attentionDetail === 'average' ? '7-day averages' : 'daily values'} ({formatAnomaly(-attentionBound, measure)} to {formatAnomaly(attentionBound, measure)}). {clippedAttentionValues ? `${clippedAttentionValues} extreme value${clippedAttentionValues === 1 ? ' is' : 's are'} outside the plot; choose “Show every extreme” to inspect ${clippedAttentionValues === 1 ? 'it' : 'them'}.` : 'No plotted values are clipped.'}</p></div>}
            {start <= GDELT_OUTAGE.end && end >= GDELT_OUTAGE.start && <div className="analysis-definition outage-note"><CircleAlert size={15} /><p><strong>Provider gap.</strong> GDELT infrastructure was unavailable from 14 June through 1 July 2025. Those dates are excluded—not treated as zero—and lines deliberately break across the gap.</p></div>}
          </section>

          <section className="lag-chart-card">
            <div className="result-heading"><div><span className="eyebrow">Lead / lag exploration</span><h3>Is the timing relationship consistent?</h3></div><small>Separate panels use the same Pearson r scale</small></div>
            <div className="lag-band-key"><i />Shaded region: negligible descriptive association (|r| &lt; 0.10)</div>
            <div className="lag-facet-grid">
              {bestLag.map(({ series, point }) => {
                const correlation = point ? Number(point[series.key]) : null
                const lag = point ? Number(point.lag) : null
                const negligible = correlation != null && Math.abs(correlation) < NEGLIGIBLE_CORRELATION
                return <section className="lag-facet" key={series.key}>
                  <div className="lag-facet-heading"><div><i style={{ background: series.color }} /><strong>{series.label}</strong></div><small>{correlation == null || lag == null ? 'Insufficient variation' : negligible ? `All lags negligible · max |r| ${Math.abs(correlation).toFixed(2)}` : `Strongest observed: ${lag > 0 ? '+' : ''}${lag}d · r ${correlation.toFixed(2)}`}</small></div>
                  <div className="lag-facet-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={lagPoints} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
                        <CartesianGrid stroke="#e0e6e2" strokeDasharray="3 5" vertical={false} />
                        <XAxis dataKey="lag" ticks={[-28, -14, 0, 14, 28]} tickFormatter={(value) => value === 0 ? '0' : `${value > 0 ? '+' : ''}${value}d`} tick={{ fontSize: 8, fill: '#738179' }} />
                        <YAxis domain={lagDomain} ticks={[-lagBound, 0, lagBound]} allowDataOverflow width={40} tickFormatter={(value) => Number(value).toFixed(lagBound <= 0.2 ? 2 : 1)} tick={{ fontSize: 8, fill: '#738179' }} />
                        <Tooltip formatter={(value) => [Number(value).toFixed(3), 'Pearson r']} labelFormatter={(value) => `${Number(value) > 0 ? '+' : ''}${value} day lag`} />
                        <ReferenceArea y1={-NEGLIGIBLE_CORRELATION} y2={NEGLIGIBLE_CORRELATION} fill="#dce4df" fillOpacity={0.5} />
                        <ReferenceLine x={0} stroke="#bd8b3b" strokeDasharray="4 4" />
                        <ReferenceLine y={0} stroke="#8f9d96" />
                        <Line type="linear" dataKey={series.key} name={series.label} stroke={series.color} strokeWidth={2.2} dot={false} connectNulls />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="lag-direction-labels"><span>← Attention leads events</span><span>Attention follows events →</span></div>
                </section>
              })}
            </div>
            <div className="analysis-definition"><BarChart3 size={15} /><p><strong>Exploratory correlation.</strong> Pearson r compares rolling event starts with attention anomalies at each lag. Autocorrelation, seasonality and shared news cycles mean this is not a causal estimate.</p></div>
          </section>
        </>}
      </div>
    </section>
  )
}
