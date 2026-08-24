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
  const [location, setLocation] = useState('__global__')
  const [hazard, setHazard] = useState<Hazard>('all')
  const [cohort, setCohort] = useState<Cohort>('all')
  const [measure, setMeasure] = useState<Measure>('matched')
  const [rollingDays, setRollingDays] = useState(28)
  const [activityRows, setActivityRows] = useState<EventActivityObservation[]>([])
  const [attentionRows, setAttentionRows] = useState<(AttentionObservation | RegionAttentionObservation)[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const start = `${studyYear}-01-01`
  const end = `${studyYear}-12-31`

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    const attentionRequest = location === '__global__' || location === '__eu27__'
      ? fetchRegionAttention(location === '__global__' ? 'global' : 'eu27', start, end)
      : fetchAttentionWindow({ start, end, geographies: [location], topics: Object.keys(TOPICS) })
    Promise.all([
      fetchEventActivity({
        geography: location,
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
  }, [cohort, end, hazard, location, start])

  const points = useMemo(() => {
    const dates = dateRange(studyYear)
    const activityByDate = new Map<string, { started: number; active: number }>()
    for (const row of activityRows) {
      const value = activityByDate.get(row.date) ?? { started: 0, active: 0 }
      value.started += row.eventsStarted
      value.active += row.eventsActive
      activityByDate.set(row.date, value)
    }
    const attentionByDate = new Map<string, Partial<Record<Topic, AttentionObservation | RegionAttentionObservation>>>()
    for (const row of attentionRows) {
      if (!(row.topicId in TOPICS)) continue
      const value = attentionByDate.get(row.date) ?? {}
      value[row.topicId as Topic] = row
      attentionByDate.set(row.date, value)
    }
    const rawByTopic: Record<Topic, (number | null)[]> = {
      climate_change: dates.map((date) => {
        const row = attentionByDate.get(date)?.climate_change
        return row ? attentionValue(row, measure) : null
      }),
      electric_vehicles: dates.map((date) => {
        const row = attentionByDate.get(date)?.electric_vehicles
        return row ? attentionValue(row, measure) : null
      }),
    }
    return dates.map((date, index) => {
      const rollingStarts = dates.slice(Math.max(0, index - rollingDays + 1), index + 1)
        .reduce((total, day) => total + (activityByDate.get(day)?.started ?? 0), 0)
      const point: Record<string, string | number | null> = {
        date,
        rollingStarts,
        activeEvents: activityByDate.get(date)?.active ?? 0,
      }
      for (const topic of Object.keys(TOPICS) as Topic[]) {
        const value = rawByTopic[topic][index]
        const baseline = rawByTopic[topic]
          .slice(Math.max(0, index - 28), index)
          .filter((item): item is number => item != null)
        if (value == null || baseline.length < 14) point[topic] = null
        else {
          const baselineMean = mean(baseline)
          point[topic] = measure === 'political_share'
            ? value - baselineMean
            : baselineMean ? ((value - baselineMean) / baselineMean) * 100 : null
        }
      }
      return point
    })
  }, [activityRows, attentionRows, measure, rollingDays, studyYear])

  const lagPoints = useMemo(() => Array.from({ length: 57 }, (_, index) => index - 28).map((lag) => {
    const result: Record<string, number | null> = { lag }
    for (const topic of Object.keys(TOPICS) as Topic[]) {
      const events: number[] = []
      const attention: number[] = []
      for (let index = 0; index < points.length; index += 1) {
        const attentionIndex = index + lag
        const eventValue = Number(points[index].rollingStarts)
        const attentionValueAtLag = points[attentionIndex]?.[topic]
        if (attentionIndex >= 0 && attentionIndex < points.length && typeof attentionValueAtLag === 'number') {
          events.push(eventValue)
          attention.push(attentionValueAtLag)
        }
      }
      result[topic] = pearson(events, attention)
    }
    return result
  }), [points])

  const totalStarts = activityRows.reduce((total, row) => total + row.eventsStarted, 0)
  const peakRolling = Math.max(0, ...points.map((point) => Number(point.rollingStarts)))
  const bestLag = (Object.keys(TOPICS) as Topic[]).map((topic) => {
    const available = lagPoints.filter((point) => typeof point[topic] === 'number')
    return {
      topic,
      point: available.sort((left, right) => Math.abs(Number(right[topic])) - Math.abs(Number(left[topic])))[0],
    }
  })

  const countryOptions = [...new Set(eventGeographies)].sort((left, right) =>
    (geographyLabels[left] || left).localeCompare(geographyLabels[right] || right),
  )

  return (
    <section className="activity-workspace">
      <aside className="activity-controls">
        <div className="lab-section-heading"><span>1</span><div><small>Country-year panel</small><h2>Configure activity</h2></div></div>
        <div className="lab-form">
          <label><span>Place</span><select value={location} onChange={(event) => setLocation(event.target.value)}><option value="__global__">Global</option><option value="__eu27__">EU27</option>{countryOptions.map((country) => <option key={country} value={country}>{geographyLabels[country] || country}</option>)}</select></label>
          <label><span>Event alerts</span><select value={cohort} onChange={(event) => setCohort(event.target.value as Cohort)}><option value="all">All alerts</option><option value="green">Green only</option><option value="major">Orange and Red</option></select></label>
          <label><span>Event type</span><select value={hazard} onChange={(event) => setHazard(event.target.value as Hazard)}><option value="all">Floods and wildfires</option><option value="flood">Floods</option><option value="wildfire">Wildfires</option></select></label>
          <label><span>Attention measure</span><select value={measure} onChange={(event) => setMeasure(event.target.value as Measure)}><option value="matched">All matching articles</option><option value="political">Political articles</option><option value="political_share">Political share</option></select></label>
          <label><span>Rolling event window</span><select value={rollingDays} onChange={(event) => setRollingDays(Number(event.target.value))}><option value={7}>7 days</option><option value={28}>28 days</option></select></label>
        </div>
        <div className="analysis-definition"><Info size={15} /><p><strong>Country exposure.</strong> Multi-country events count once in every affected country. Global and EU totals count each unique event once.</p></div>
      </aside>

      <div className="activity-results">
        {loading ? <div className="activity-state"><Activity size={20} /> Loading country-day panel…</div> : error ? <div className="activity-state error"><CircleAlert size={20} /><strong>Activity panel unavailable</strong><p>{error}</p></div> : <>
          <div className="activity-kpis">
            <article><small>Events started</small><strong>{totalStarts.toLocaleString()}</strong><span>{cohort === 'major' ? 'Orange and Red' : cohort === 'green' ? 'Green alerts' : 'All alert levels'}</span></article>
            <article><small>Peak rolling load</small><strong>{peakRolling.toLocaleString()}</strong><span>Starts within {rollingDays} days</span></article>
            {bestLag.map(({ topic, point }) => <article key={topic}><small>{TOPICS[topic].label} strongest lag</small><strong>{point ? `${Number(point.lag) > 0 ? '+' : ''}${point.lag}d` : '—'}</strong><span>{point ? `r = ${Number(point[topic]).toFixed(2)}` : 'Insufficient variation'}</span></article>)}
          </div>

          <section className="activity-chart-card">
            <div className="result-heading"><div><span className="eyebrow">Event activity and attention</span><h2>Do attention anomalies move with event load?</h2></div><small>{rollingDays}-day starts · preceding 28-day attention baseline</small></div>
            <div className="activity-chart">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={points} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={(value) => new Intl.DateTimeFormat('en-GB', { month: 'short', timeZone: 'UTC' }).format(new Date(value))} minTickGap={45} tick={{ fontSize: 8, fill: '#738179' }} />
                  <YAxis yAxisId="attention" width={45} tickFormatter={(value) => `${value > 0 ? '+' : ''}${Math.round(value)}${measure === 'political_share' ? '' : '%'}`} tick={{ fontSize: 8, fill: '#738179' }} />
                  <YAxis yAxisId="events" orientation="right" width={35} allowDecimals={false} tick={{ fontSize: 8, fill: '#a17b42' }} />
                  <Tooltip labelFormatter={(value) => new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(String(value)))} formatter={(value, name) => name === 'Rolling event starts' ? [Number(value).toFixed(0), name] : [formatAnomaly(value, measure), name]} />
                  <Legend wrapperStyle={{ fontSize: 9 }} />
                  <ReferenceLine yAxisId="attention" y={0} stroke="#9eaaa4" />
                  <Bar yAxisId="events" dataKey="rollingStarts" name="Rolling event starts" fill="#d7b878" opacity={0.38} barSize={4} />
                  {studyYear === 2025 && <ReferenceArea yAxisId="attention" x1={GDELT_OUTAGE.start} x2={GDELT_OUTAGE.end} fill="#bd8b3b" fillOpacity={0.12} stroke="#bd8b3b" strokeOpacity={0.45} label={{ value: 'GDELT outage · excluded', position: 'insideTop', fill: '#806127', fontSize: 8 }} />}
                  <Line yAxisId="attention" type="monotone" dataKey="climate_change" name="Climate change" stroke={TOPICS.climate_change.color} strokeWidth={2} dot={false} connectNulls={false} />
                  <Line yAxisId="attention" type="monotone" dataKey="electric_vehicles" name="Electric vehicles" stroke={TOPICS.electric_vehicles.color} strokeWidth={2} dot={false} connectNulls={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            {studyYear === 2025 && <div className="analysis-definition outage-note"><CircleAlert size={15} /><p><strong>Provider gap.</strong> GDELT infrastructure was unavailable from 14 June through 1 July 2025. Those dates are excluded—not treated as zero—and lines deliberately break across the gap.</p></div>}
          </section>

          <section className="lag-chart-card">
            <div className="result-heading"><div><span className="eyebrow">Lead / lag exploration</span><h3>When is event activity most associated with attention?</h3></div><small>Positive lag means attention follows events</small></div>
            <div className="lag-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={lagPoints} margin={{ top: 10, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" vertical={false} />
                  <XAxis dataKey="lag" tickFormatter={(value) => `${value > 0 ? '+' : ''}${value}d`} tick={{ fontSize: 8, fill: '#738179' }} />
                  <YAxis domain={[-1, 1]} width={36} tick={{ fontSize: 8, fill: '#738179' }} />
                  <Tooltip formatter={(value) => Number(value).toFixed(3)} labelFormatter={(value) => `${Number(value) > 0 ? '+' : ''}${value} day lag`} />
                  <ReferenceLine x={0} stroke="#bd8b3b" strokeDasharray="4 4" />
                  <ReferenceLine y={0} stroke="#9eaaa4" />
                  <Line type="monotone" dataKey="climate_change" name="Climate change" stroke={TOPICS.climate_change.color} strokeWidth={2} dot={false} connectNulls />
                  <Line type="monotone" dataKey="electric_vehicles" name="Electric vehicles" stroke={TOPICS.electric_vehicles.color} strokeWidth={2} dot={false} connectNulls />
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
