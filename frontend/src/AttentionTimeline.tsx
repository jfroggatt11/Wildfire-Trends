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

type Topic = 'climate_change' | 'electric_vehicles'
type Measure = 'matched' | 'political'
type PlaceScope = 'world' | 'eu27' | 'country' | 'group'
type Hazard = 'all' | 'wildfire' | 'flood'
type AlertScope = 'major' | 'all' | 'green'

type KeyEvent = {
  id: string
  name: string
  hazardType: 'wildfire' | 'flood'
  alertLevel: 'Green' | 'Orange' | 'Red'
  startAt: string
  geographyIds: string[]
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
  const [topic, setTopic] = useState<Topic>('climate_change')
  const [measure, setMeasure] = useState<Measure>('matched')
  const [hazard, setHazard] = useState<Hazard>('all')
  const [alerts, setAlerts] = useState<AlertScope>('major')
  const [attentionRows, setAttentionRows] = useState<(AttentionObservation | RegionAttentionObservation)[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const activeLocations = useMemo(() => {
    if (placeScope === 'world') return ['__global__']
    if (placeScope === 'eu27') return ['__eu27__']
    if (placeScope === 'country') return country ? [country] : []
    return groupCountries
  }, [country, groupCountries, placeScope])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    const request = placeScope === 'world' || placeScope === 'eu27'
      ? fetchRegionAttention(placeScope === 'world' ? 'global' : 'eu27', coverageStart, coverageEnd)
      : fetchAttentionWindow({ start: coverageStart, end: coverageEnd, geographies: activeLocations, topics: [topic] })
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
  }, [activeLocations, coverageEnd, coverageStart, placeScope, topic])

  const relevantEvents = useMemo(() => keyEvents.filter((event) => {
    const eventDate = event.startAt.slice(0, 10)
    if (eventDate < coverageStart || eventDate > coverageEnd) return false
    if (alerts === 'major' && event.alertLevel === 'Green') return false
    if (alerts === 'green' && event.alertLevel !== 'Green') return false
    if (hazard !== 'all' && event.hazardType !== hazard) return false
    if (placeScope === 'world') return true
    if (placeScope === 'eu27') return event.geographyIds.some((item) => EU27.has(item))
    return event.geographyIds.some((item) => activeLocations.includes(item))
  }), [activeLocations, alerts, coverageEnd, coverageStart, hazard, keyEvents, placeScope])

  const eventDates = useMemo(() => {
    const grouped = new Map<string, KeyEvent[]>()
    for (const event of relevantEvents) {
      const day = event.startAt.slice(0, 10)
      grouped.set(day, [...(grouped.get(day) ?? []), event])
    }
    return grouped
  }, [relevantEvents])

  const dailyPoints = useMemo(() => {
    const byLocation = new Map<string, Map<string, AttentionObservation | RegionAttentionObservation>>()
    for (const row of attentionRows) {
      if (row.topicId !== topic) continue
      const rowLocation = 'geography' in row
        ? row.geography
        : row.regionId === 'global' ? '__global__' : '__eu27__'
      const byDate = byLocation.get(rowLocation) ?? new Map<string, AttentionObservation | RegionAttentionObservation>()
      byDate.set(row.date, row)
      byLocation.set(rowLocation, byDate)
    }
    return dateRange(coverageStart, coverageEnd).map((date) => {
      const rows = activeLocations.map((location) => byLocation.get(location)?.get(date))
      if (!activeLocations.length || rows.some((row) => !row)) return { date, daily: null }
      const daily = rows.reduce((total, row) => total + Number(measure === 'matched' ? row?.matchedCount ?? 0 : row?.politicalCount ?? 0), 0)
      return { date, daily }
    })
  }, [activeLocations, attentionRows, coverageEnd, coverageStart, measure, topic])

  const observedValues = dailyPoints.flatMap((point) => point.daily == null ? [] : [point.daily])
  const dailyPeak = observedValues.length ? Math.max(...observedValues) : 0
  const dailyAverage = observedValues.length
    ? observedValues.reduce((total, value) => total + value, 0) / observedValues.length
    : 0
  const missingDays = dailyPoints.filter((point) => point.daily == null).length
  const markerHeight = dailyPeak > 0 ? dailyPeak * 0.975 : 0
  const chartPoints = dailyPoints.map((point) => {
    const events = eventDates.get(point.date)
    const isRed = events?.some((event) => event.alertLevel === 'Red') ?? false
    const isOrange = events?.some((event) => event.alertLevel === 'Orange') ?? false
    return {
      ...point,
      greenEvent: events && !isRed && !isOrange ? markerHeight : null,
      orangeEvent: events && !isRed && isOrange ? markerHeight : null,
      redEvent: events && isRed ? markerHeight : null,
      eventNames: events?.map((event) => event.name) ?? [],
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

  const addGroupCountry = (selected: string) => {
    if (!selected || groupCountries.includes(selected) || groupCountries.length >= MAX_GROUP_COUNTRIES) return
    setGroupCountries((current) => [...current, selected])
  }

  return (
    <section className="timeline-workspace">
      <aside className="timeline-controls">
        <div className="lab-section-heading"><span>1</span><div><small>Observed publishing</small><h2>Configure timeline</h2></div></div>
        <div className="lab-form">
          <label><span>Geography</span><select value={placeScope} onChange={(event) => setPlaceScope(event.target.value as PlaceScope)}><option value="world">World</option><option value="eu27">EU27</option><option value="country">Single country</option><option value="group">Country group</option></select></label>
          {placeScope === 'country' && <label><span>Country</span><select value={country} onChange={(event) => setCountry(event.target.value)}>{countryOptions.map((item) => <option key={item} value={item}>{geographyLabels[item] || item}</option>)}</select></label>}
          {placeScope === 'group' && <>
            <label><span>Add country</span><select aria-label="Add timeline country" value="" disabled={groupCountries.length >= MAX_GROUP_COUNTRIES} onChange={(event) => addGroupCountry(event.target.value)}><option value="">{groupCountries.length >= MAX_GROUP_COUNTRIES ? 'Eight-country maximum' : 'Choose a country…'}</option>{countryOptions.filter((item) => !groupCountries.includes(item)).map((item) => <option key={item} value={item}>{geographyLabels[item] || item}</option>)}</select></label>
            <div className="comparison-country-list" aria-label="Timeline country group">{groupCountries.map((item) => <span key={item}>{geographyLabels[item] || item}<button type="button" aria-label={`Remove ${geographyLabels[item] || item}`} disabled={groupCountries.length <= 2} onClick={() => setGroupCountries((current) => current.filter((value) => value !== item))}>×</button></span>)}</div>
          </>}
          <label><span>Attention topic</span><select value={topic} onChange={(event) => setTopic(event.target.value as Topic)}>{Object.entries(TOPICS).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select></label>
          <label><span>Attention measure</span><select value={measure} onChange={(event) => setMeasure(event.target.value as Measure)}><option value="matched">All matching articles</option><option value="political">Political articles</option></select></label>
          <label><span>Event alerts</span><select value={alerts} onChange={(event) => setAlerts(event.target.value as AlertScope)}><option value="major">Orange and Red</option><option value="all">Green, Orange and Red</option><option value="green">Green only</option></select><small>Green is a lower humanitarian-impact tier, not an absence of an event.</small></label>
          <label><span>Key event type</span><select value={hazard} onChange={(event) => setHazard(event.target.value as Hazard)}><option value="all">Floods and wildfires</option><option value="flood">Floods</option><option value="wildfire">Wildfires</option></select></label>
        </div>
        <div className="analysis-definition"><Info size={15} /><p><strong>Observed daily attention.</strong> Each point is the distinct matching URL count for that UTC day in the selected publishing markets. Missing provider dates are not estimated or treated as zero. Event colours are GDACS impact tiers; their rules differ by hazard.</p></div>
      </aside>

      <div className="timeline-results">
        {loading ? <div className="activity-state"><Activity size={20} /> Loading daily attention…</div> : error ? <div className="activity-state error"><CircleAlert size={20} /><strong>Attention timeline unavailable</strong><p>{error}</p></div> : <section className="timeline-chart-card">
          <div className="result-heading"><div><span className="eyebrow">Daily attention</span><h2>{TOPICS[topic].label} in {placeLabel}</h2></div><div className="timeline-total"><strong>{compactCount(Math.round(dailyAverage))}</strong><small>average {measure === 'matched' ? 'matching' : 'political'} articles/day · peak {compactCount(dailyPeak)} · {relevantEvents.length} events</small></div></div>
          <div className="timeline-chart" role="img" aria-label={`Daily ${TOPICS[topic].label.toLowerCase()} attention in ${placeLabel} with event markers`}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartPoints} margin={{ top: 20, right: 18, bottom: 2, left: 4 }}>
                <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(value) => new Intl.DateTimeFormat('en-GB', { month: 'short', timeZone: 'UTC' }).format(new Date(value))} minTickGap={45} tick={{ fontSize: 9, fill: '#738179' }} />
                <YAxis domain={[0, 'auto']} width={56} tickFormatter={(value) => compactCount(Number(value))} tick={{ fontSize: 9, fill: '#738179' }} />
                <Tooltip labelFormatter={(value) => new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(String(value)))} formatter={(value, name, item) => name === 'Events' ? [(item.payload.eventNames as string[]).join(' · '), `${item.payload.eventCount} event${item.payload.eventCount === 1 ? '' : 's'}`] : [Number(value).toLocaleString('en-GB'), 'Articles that day']} />
                {coverageStart <= GDELT_OUTAGE.end && coverageEnd >= GDELT_OUTAGE.start && <ReferenceArea x1={GDELT_OUTAGE.start} x2={GDELT_OUTAGE.end} fill="#bd8b3b" fillOpacity={0.1} stroke="#bd8b3b" strokeOpacity={0.35} label={{ value: 'GDELT gap', position: 'insideTop', fill: '#806127', fontSize: 8 }} />}
                {[...eventDates.entries()].map(([date, events]) => <ReferenceLine key={date} x={date} stroke={events.some((event) => event.alertLevel === 'Red') ? '#b6523b' : events.some((event) => event.alertLevel === 'Orange') ? '#bd8b3b' : '#789342'} strokeWidth={1} strokeDasharray="3 4" strokeOpacity={0.62} />)}
                <Line type="monotone" dataKey="daily" name="Daily articles" stroke={TOPICS[topic].color} strokeWidth={2.3} dot={false} connectNulls={false} />
                <Scatter dataKey="greenEvent" name="Events" legendType="none" fill="#789342" shape="diamond" />
                <Scatter dataKey="orangeEvent" name="Events" legendType="none" fill="#bd8b3b" shape="diamond" />
                <Scatter dataKey="redEvent" name="Events" legendType="none" fill="#b6523b" shape="diamond" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="timeline-key"><span><i style={{ borderColor: '#789342' }} />Green alert</span><span><i style={{ borderColor: '#bd8b3b' }} />Orange alert</span><span><i style={{ borderColor: '#b6523b' }} />Red alert</span><small>Hover a diamond for event names · {missingDays} unavailable day{missingDays === 1 ? '' : 's'} excluded</small></div>
        </section>}
      </div>
    </section>
  )
}
