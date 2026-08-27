import { useEffect, useMemo, useState } from 'react'
import { Activity, BarChart3, CircleAlert, Info } from 'lucide-react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
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

type Hazard = 'all' | 'wildfire' | 'flood'
type Cohort = 'major' | 'green' | 'all'
type Measure = 'matched' | 'political' | 'political_share'
type Topic = 'climate_change' | 'electric_vehicles'
type PlaceMode = 'single' | 'compare'
type ScaleMode = 'focus' | 'full'

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

const eventKey = (location: string) => `events_${location}`
const attentionKey = (location: string, topic: Topic) => `attention_${location}_${topic}`

const shiftDate = (value: string, days: number) => {
  const result = new Date(`${value}T00:00:00Z`)
  result.setUTCDate(result.getUTCDate() + days)
  return result.toISOString().slice(0, 10)
}

const dateRange = (year: number) => {
  const dates: string[] = []
  for (let day = `${year}-01-01`; day <= `${year}-12-31`; day = shiftDate(day, 1)) dates.push(day)
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
  studyYear,
  geographyLabels,
  eventGeographies,
}: {
  studyYear: number
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
  const [rollingDays, setRollingDays] = useState(28)
  const [activityRows, setActivityRows] = useState<EventActivityObservation[]>([])
  const [attentionRows, setAttentionRows] = useState<(AttentionObservation | RegionAttentionObservation)[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const start = `${studyYear}-01-01`
  const end = `${studyYear}-12-31`
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
    const dates = dateRange(studyYear)
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
  }, [activeLocations, activityRows, attentionRows, measure, rollingDays, studyYear])

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

  const attentionValues = useMemo(() => points.flatMap((point) => chartSeries
    .map((series) => point[series.key])
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))), [chartSeries, points])
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
  const lagBound = Math.min(1, symmetricBound(lagValues, 1, 0.05))
  const lagDomain: [number, number] = [-lagBound, lagBound]
  const bestLag = chartSeries.map((series) => {
    const available = lagPoints.filter((point) => typeof point[series.key] === 'number')
    return {
      series,
      point: available.sort((left, right) => Math.abs(Number(right[series.key])) - Math.abs(Number(left[series.key])))[0],
    }
  })

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
          <label><span>Event alerts</span><select value={cohort} onChange={(event) => setCohort(event.target.value as Cohort)}><option value="all">All alerts</option><option value="green">Green only</option><option value="major">Orange and Red</option></select></label>
          <label><span>Event type</span><select value={hazard} onChange={(event) => setHazard(event.target.value as Hazard)}><option value="all">Floods and wildfires</option><option value="flood">Floods</option><option value="wildfire">Wildfires</option></select></label>
          <label><span>Attention measure</span><select value={measure} onChange={(event) => setMeasure(event.target.value as Measure)}><option value="matched">All matching articles</option><option value="political">Political articles</option><option value="political_share">Political share</option></select></label>
          <label><span>Attention scale</span><select value={scaleMode} onChange={(event) => setScaleMode(event.target.value as ScaleMode)}><option value="focus">Focus on typical range</option><option value="full">Show every extreme</option></select><small>{scaleMode === 'focus' ? 'Symmetric 98% range; extremes are flagged below the chart' : 'Symmetric range including every daily value'}</small></label>
          <label><span>Rolling event window</span><select value={rollingDays} onChange={(event) => setRollingDays(Number(event.target.value))}><option value={7}>7 days</option><option value={28}>28 days</option></select></label>
        </div>
        <div className="analysis-definition"><Info size={15} /><p><strong>Country exposure.</strong> Multi-country events count once in every affected country. Comparison mode uses solid attention lines and dashed rolling-event lines, with a maximum of five countries.</p></div>
      </aside>

      <div className="activity-results">
        {loading ? <div className="activity-state"><Activity size={20} /> Loading country-day panel…</div> : error ? <div className="activity-state error"><CircleAlert size={20} /><strong>Activity panel unavailable</strong><p>{error}</p></div> : <>
          <div className="activity-kpis">
            <article><small>{placeMode === 'compare' ? 'Event-country starts' : 'Events started'}</small><strong>{totalStarts.toLocaleString()}</strong><span>{placeMode === 'compare' ? 'Country exposures; a multi-country event may repeat' : cohort === 'major' ? 'Orange and Red' : cohort === 'green' ? 'Green alerts' : 'All alert levels'}</span></article>
            <article><small>Peak rolling load</small><strong>{peakRolling.toLocaleString()}</strong><span>{placeMode === 'compare' ? `Highest selected country within ${rollingDays} days` : `Starts within ${rollingDays} days`}</span></article>
            {bestLag.map(({ series, point }) => <article key={series.key}><small>{series.label} strongest lag</small><strong>{point ? `${Number(point.lag) > 0 ? '+' : ''}${point.lag}d` : '—'}</strong><span>{point ? `r = ${Number(point[series.key]).toFixed(2)}` : 'Insufficient variation'}</span></article>)}
          </div>

          <section className="activity-chart-card">
            <div className="result-heading"><div><span className="eyebrow">Event activity and attention</span><h2>Do attention anomalies move with event load?</h2></div><small>{rollingDays}-day starts · preceding 28-day attention baseline</small></div>
            <div className="activity-chart">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={points} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={(value) => new Intl.DateTimeFormat('en-GB', { month: 'short', timeZone: 'UTC' }).format(new Date(value))} minTickGap={45} tick={{ fontSize: 8, fill: '#738179' }} />
                  <YAxis yAxisId="attention" domain={attentionDomain} allowDataOverflow width={45} tickFormatter={(value) => `${value > 0 ? '+' : ''}${Math.round(value)}${measure === 'political_share' ? ' pp' : '%'}`} tick={{ fontSize: 8, fill: '#738179' }} />
                  <YAxis yAxisId="events" domain={eventDomain} orientation="right" width={35} allowDecimals={false} tick={{ fontSize: 8, fill: '#a17b42' }} />
                  <Tooltip labelFormatter={(value) => new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(String(value)))} formatter={(value, name) => String(name).includes('event starts') ? [Number(value).toFixed(0), name] : [formatAnomaly(value, measure), name]} />
                  <Legend wrapperStyle={{ fontSize: 9 }} />
                  <ReferenceLine yAxisId="attention" y={0} stroke="#9eaaa4" />
                  {placeMode === 'single' && <Bar yAxisId="events" dataKey={eventKey(location)} name="Rolling event starts" fill="#d7b878" opacity={0.38} barSize={4} />}
                  {studyYear === 2025 && <ReferenceArea yAxisId="attention" x1={GDELT_OUTAGE.start} x2={GDELT_OUTAGE.end} fill="#bd8b3b" fillOpacity={0.12} stroke="#bd8b3b" strokeOpacity={0.45} label={{ value: 'GDELT outage · excluded', position: 'insideTop', fill: '#806127', fontSize: 8 }} />}
                  {placeMode === 'compare' && chartSeries.map((series) => <Line key={`events-${series.location}`} yAxisId="events" type="monotone" dataKey={series.eventKey} name={`${series.label} · event starts`} legendType="none" stroke={series.color} strokeWidth={1} strokeDasharray="3 5" strokeOpacity={0.3} dot={false} connectNulls={false} />)}
                  {chartSeries.map((series) => <Line key={series.key} yAxisId="attention" type="monotone" dataKey={series.key} name={series.label} stroke={series.color} strokeWidth={2.4} dot={false} connectNulls={false} />)}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            {placeMode === 'compare' && <div className="chart-line-key"><span><i className="solid" />Attention anomaly</span><span><i className="dashed" />Rolling event starts</span></div>}
            {scaleMode === 'focus' && <div className="chart-scale-note"><Info size={14} /><p><strong>Focused scale.</strong> The axis shows the symmetric 98% range ({formatAnomaly(-attentionBound, measure)} to {formatAnomaly(attentionBound, measure)}). {clippedAttentionValues ? `${clippedAttentionValues} extreme daily value${clippedAttentionValues === 1 ? ' is' : 's are'} outside the plot; choose “Show every extreme” to inspect ${clippedAttentionValues === 1 ? 'it' : 'them'}.` : 'No plotted values are clipped.'}</p></div>}
            {studyYear === 2025 && <div className="analysis-definition outage-note"><CircleAlert size={15} /><p><strong>Provider gap.</strong> GDELT infrastructure was unavailable from 14 June through 1 July 2025. Those dates are excluded—not treated as zero—and lines deliberately break across the gap.</p></div>}
          </section>

          <section className="lag-chart-card">
            <div className="result-heading"><div><span className="eyebrow">Lead / lag exploration</span><h3>When is event activity most associated with attention?</h3></div><small>Positive lag means attention follows events</small></div>
            <div className="lag-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={lagPoints} margin={{ top: 10, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" vertical={false} />
                  <XAxis dataKey="lag" tickFormatter={(value) => `${value > 0 ? '+' : ''}${value}d`} tick={{ fontSize: 8, fill: '#738179' }} />
                  <YAxis domain={lagDomain} allowDataOverflow width={40} tickFormatter={(value) => Number(value).toFixed(lagBound <= 0.2 ? 2 : 1)} tick={{ fontSize: 8, fill: '#738179' }} />
                  <Tooltip formatter={(value) => Number(value).toFixed(3)} labelFormatter={(value) => `${Number(value) > 0 ? '+' : ''}${value} day lag`} />
                  <ReferenceLine x={0} stroke="#bd8b3b" strokeDasharray="4 4" />
                  <ReferenceLine y={0} stroke="#9eaaa4" />
                  {chartSeries.map((series) => <Line key={series.key} type="monotone" dataKey={series.key} name={series.label} stroke={series.color} strokeWidth={2} dot={false} connectNulls />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="analysis-definition"><BarChart3 size={15} /><p><strong>Exploratory correlation.</strong> Pearson r compares rolling event starts with attention anomalies at each lag. Autocorrelation, seasonality and shared news cycles mean this is not a causal estimate.</p></div>
          </section>
        </>}
      </div>
    </section>
  )
}
