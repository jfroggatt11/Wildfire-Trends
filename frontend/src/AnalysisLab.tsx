import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { Activity, ArrowRight, Check, CircleAlert, Info } from 'lucide-react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import EventActivityView from './EventActivity'
import AttentionTimeline from './AttentionTimeline'
import { fetchEventEffects, isSupabaseEnabled } from './supabase'
import type { EventEffectObservation } from './supabase'
import { fromUtcDay, inclusiveDays, toUtcDay } from './analysisTime'

type HazardType = 'wildfire' | 'flood'
type LabScope = 'affected' | 'other_eu27' | 'rest_world' | 'global'
type LabTiming = 'onset' | 'persistence'
type LabMeasure = 'matched' | 'political' | 'political_share'
type TopicId = 'climate_change' | 'electric_vehicles'
type AlertCohort = 'major' | 'green' | 'all'
type CountryRankingSort = 'events' | 'response'

type StudyEvent = {
  id: string
  name: string
  hazardType: HazardType
  alertLevel: 'Green' | 'Orange' | 'Red'
  alertScore: number | null
  startAt: string
  endAt: string
  geographyIds: string[]
  severity?: number | null
  severityUnit?: string | null
}

type StudyEffect = {
  eventId: string
  hazardType: HazardType
  alertLevel: 'Green' | 'Orange' | 'Red'
  startAt: string
  endAt: string
  geographyIds: string[]
  scope: LabScope
  topicId: TopicId
  windowDays: number
  timing: LabTiming
  complete: boolean
  missingDays: number
  overlap: boolean
  matchedPreMean: number | null
  matchedPostMean: number | null
  matchedChange: number | null
  matchedPercentChange: number | null
  politicalPreMean: number | null
  politicalPostMean: number | null
  politicalChange: number | null
  politicalPercentChange: number | null
  politicalSharePre: number | null
  politicalSharePost: number | null
  politicalShareChange: number | null
}

type StudySeries = {
  eventId: string
  scope: LabScope
  topicId: TopicId
  timing: LabTiming
  points: [number, number | null, number | null][]
}

export type EventStudyData = {
  schemaVersion: number
  generatedAt: string
  studyYear: number
  coverage: {
    start: string
    end: string
    observedDays: number
    geographies: number
    excludedPeriods?: { start: string; end: string; label: string; evidenceUrl: string }[]
  }
  topics: TopicId[]
  hazards: HazardType[]
  alerts: ('Orange' | 'Red')[]
  windows: number[]
  timings: LabTiming[]
  scopes: LabScope[]
  events: StudyEvent[]
  effects: StudyEffect[]
  series: StudySeries[]
  method: Record<string, string>
}

const TOPICS: Record<TopicId, { label: string; color: string }> = {
  climate_change: { label: 'Climate change', color: '#286e59' },
  electric_vehicles: { label: 'Electric vehicles', color: '#6575b7' },
}

const SCOPES: Record<LabScope, { label: string; description: string }> = {
  affected: { label: 'Affected countries', description: 'Publishing markets directly affected by each event' },
  other_eu27: { label: 'Other EU27', description: 'EU publishing markets excluding affected countries' },
  rest_world: { label: 'Rest of world', description: 'Non-EU markets excluding affected countries' },
  global: { label: 'Global', description: 'All 197 mapped publishing markets' },
}

const MEASURES: Record<LabMeasure, { label: string; short: string; unit: string }> = {
  matched: { label: 'All matching articles', short: 'Article attention', unit: '%' },
  political: { label: 'Political articles', short: 'Political volume', unit: '%' },
  political_share: { label: 'Political share', short: 'Politicisation', unit: 'pp' },
}

const HYPOTHESES = [
  { id: 'attention', number: 'H1', title: 'Climate attention', copy: 'Do major events increase climate-change coverage?' },
  { id: 'spillover', number: 'H2', title: 'EV spillover', copy: 'Does attention spill over into electric-vehicle discourse?' },
  { id: 'geography', number: 'H3', title: 'Geographic diffusion', copy: 'Does the response extend into other EU media markets?' },
  { id: 'political', number: 'H4', title: 'Politicisation', copy: 'Does political content grow as a share of topic coverage?' },
] as const

const COHORT_ALERTS: Record<AlertCohort, EventEffectObservation['alertLevel'][]> = {
  major: ['Orange', 'Red'],
  green: ['Green'],
  all: ['Green', 'Orange', 'Red'],
}

const COUNTRY_RANKING_THRESHOLDS = [1, 2, 3, 5, 10]

function combineStudies(studies: EventStudyData[]): EventStudyData | null {
  if (!studies.length) return null
  const ordered = [...studies].sort((left, right) => left.coverage.start.localeCompare(right.coverage.start))
  const events = new Map(ordered.flatMap((study) => study.events).map((event) => [event.id, event]))
  const excludedPeriods = new Map(ordered.flatMap((study) => study.coverage.excludedPeriods ?? []).map((period) => [`${period.start}:${period.end}`, period]))
  return {
    ...ordered[0],
    studyYear: 0,
    generatedAt: ordered.map((study) => study.generatedAt).sort().at(-1) ?? ordered[0].generatedAt,
    coverage: {
      start: ordered[0].coverage.start,
      end: ordered.at(-1)!.coverage.end,
      observedDays: ordered.reduce((total, study) => total + study.coverage.observedDays, 0),
      geographies: Math.max(...ordered.map((study) => study.coverage.geographies)),
      excludedPeriods: [...excludedPeriods.values()],
    },
    events: [...events.values()],
    effects: ordered.flatMap((study) => study.effects),
    series: ordered.flatMap((study) => study.series),
  }
}

function median(values: number[]) {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function quartile(values: number[], fraction: number) {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))]
}

function effectValue(effect: StudyEffect, measure: LabMeasure) {
  if (measure === 'matched') return effect.matchedPercentChange
  if (measure === 'political') return effect.politicalPercentChange
  return effect.politicalShareChange
}

function formatEffect(value: number | null, measure: LabMeasure, digits = 0) {
  if (value == null || !Number.isFinite(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(digits)}${measure === 'political_share' ? ' pp' : '%'}`
}

function eventLabel(event: StudyEvent, labels: Record<string, string>) {
  const country = event.geographyIds.map((id) => labels[id] || id.replaceAll('_', ' ')).join(', ')
  return country || event.name
}

function buildTimeline(
  study: EventStudyData,
  includedEffects: StudyEffect[],
  topic: TopicId,
  scope: LabScope,
  measure: LabMeasure,
  timing: LabTiming,
) {
  const valuesByDay = new Map<number, number[]>()
  const effects = new Map(includedEffects.map((effect) => [effect.eventId, effect]))
  for (const series of study.series) {
    const effect = effects.get(series.eventId)
    if (series.topicId !== topic || series.scope !== scope || series.timing !== timing || !effect) continue
    const rawValue = ([, matched, political]: StudySeries['points'][number]) => {
      if (matched == null || political == null) return null
      if (measure === 'matched') return matched
      if (measure === 'political') return political
      return matched ? (political / matched) * 100 : null
    }
    const baseline = measure === 'matched'
      ? effect.matchedPreMean
      : measure === 'political'
        ? effect.politicalPreMean
        : effect.politicalSharePre
    if (baseline == null) continue
    for (const point of series.points) {
      const value = rawValue(point)
      if (value == null || (measure !== 'political_share' && baseline === 0)) continue
      const normalized = measure === 'political_share' ? value - baseline : ((value - baseline) / baseline) * 100
      const bucket = valuesByDay.get(point[0]) ?? []
      bucket.push(normalized)
      valuesByDay.set(point[0], bucket)
    }
  }
  return [...valuesByDay.entries()]
    .sort(([left], [right]) => left - right)
    .map(([day, values]) => ({ day, median: median(values), events: values.length }))
}

function StudyTimeline({ points, measure, timing }: { points: ReturnType<typeof buildTimeline>; measure: LabMeasure; timing: LabTiming }) {
  return (
    <div className="study-timeline" aria-label="Median event-time response">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 12, right: 16, bottom: 3, left: 0 }}>
          <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" vertical={false} />
          <XAxis dataKey="day" tickFormatter={(value) => value === 0 ? (timing === 'onset' ? 'Start' : 'End +1') : `${value > 0 ? '+' : ''}${value}d`} tick={{ fontSize: 9, fill: '#738179' }} />
          <YAxis width={45} tickFormatter={(value) => `${value > 0 ? '+' : ''}${Math.round(value)}${measure === 'political_share' ? '' : '%'}`} tick={{ fontSize: 9, fill: '#738179' }} />
          <Tooltip formatter={(value) => [formatEffect(Number(value), measure, 1), 'Median change']} labelFormatter={(day) => Number(day) === 0 ? (timing === 'onset' ? 'Event starts' : 'First day after event end') : `Relative day ${Number(day) > 0 ? '+' : ''}${day}`} />
          <ReferenceLine x={0} stroke="#bd8b3b" strokeDasharray="5 4" />
          <ReferenceLine y={0} stroke="#9eaaa4" />
          <Line type="monotone" dataKey="median" stroke="#286e59" strokeWidth={2.5} dot={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function AnalysisLab({
  studies,
  geographyLabels,
  eventGeographies,
  catalogueEvents,
  onOpenEvent,
}: {
  studies: EventStudyData[]
  geographyLabels: Record<string, string>
  eventGeographies: string[]
  catalogueEvents: StudyEvent[]
  onOpenEvent: (id: string) => void
}) {
  const availableYears = useMemo(
    () => [...new Set(studies.map((item) => item.studyYear))].sort((left, right) => left - right),
    [studies],
  )
  const combinedStudy = useMemo(() => combineStudies(studies), [studies])
  const [selectedPeriod, setSelectedPeriod] = useState('all')
  const study = selectedPeriod === 'all'
    ? combinedStudy
    : studies.find((item) => item.studyYear === Number(selectedPeriod)) ?? combinedStudy
  const [rangeStart, setRangeStart] = useState(() => combinedStudy?.coverage.start ?? '')
  const [rangeEnd, setRangeEnd] = useState(() => combinedStudy?.coverage.end ?? '')
  const [mode, setMode] = useState<'study' | 'activity' | 'timeline'>('study')
  const [hypothesis, setHypothesis] = useState('attention')
  const [cohort, setCohort] = useState<AlertCohort>('major')
  const [hazard, setHazard] = useState<'all' | HazardType>('all')
  const [scope, setScope] = useState<LabScope>('affected')
  const [windowDays, setWindowDays] = useState(14)
  const [timing, setTiming] = useState<LabTiming>('onset')
  const [topic, setTopic] = useState<TopicId>('climate_change')
  const [measure, setMeasure] = useState<LabMeasure>('matched')
  const [excludeOverlaps, setExcludeOverlaps] = useState(true)
  const [countryRankingMinimum, setCountryRankingMinimum] = useState(3)
  const [countryRankingSort, setCountryRankingSort] = useState<CountryRankingSort>('events')
  const [remoteEffects, setRemoteEffects] = useState<StudyEffect[] | null>(null)
  const [remoteLoading, setRemoteLoading] = useState(false)
  const [remoteError, setRemoteError] = useState<string | null>(null)

  const updateSelectedPeriod = (period: string) => {
    const nextStudy = period === 'all'
      ? combinedStudy
      : studies.find((item) => item.studyYear === Number(period)) ?? combinedStudy
    setSelectedPeriod(period)
    if (nextStudy) {
      setRangeStart(nextStudy.coverage.start)
      setRangeEnd(nextStudy.coverage.end)
    }
  }

  useEffect(() => {
    if (!study) return
    setRangeStart(study.coverage.start)
    setRangeEnd(study.coverage.end)
  }, [study])

  useEffect(() => {
    if (cohort === 'major') {
      setRemoteEffects(null)
      setRemoteError(null)
      setRemoteLoading(false)
      return
    }
    if (!isSupabaseEnabled()) {
      setRemoteEffects(null)
      setRemoteError('All-alert event effects require the Supabase analysis tables.')
      return
    }
    if (!study) return
    let active = true
    setRemoteLoading(true)
    setRemoteEffects(null)
    setRemoteError(null)
    fetchEventEffects({
      start: rangeStart,
      end: rangeEnd,
      scope,
      windowDays,
      timing,
      alerts: COHORT_ALERTS[cohort],
      hazard: hazard === 'all' ? undefined : hazard,
    })
      .then((rows) => active && setRemoteEffects(rows as StudyEffect[]))
      .catch(() => {
        if (!active) return
        setRemoteEffects(null)
        setRemoteError('The all-alert event-effect table is not available from Supabase yet.')
      })
      .finally(() => active && setRemoteLoading(false))
    return () => { active = false }
  }, [cohort, hazard, rangeEnd, rangeStart, scope, study, timing, windowDays])

  const sourceEffects = useMemo(
    () => (cohort === 'major' ? study?.effects ?? [] : remoteEffects ?? []).filter((effect) => effect.startAt.slice(0, 10) >= rangeStart && effect.startAt.slice(0, 10) <= rangeEnd),
    [cohort, rangeEnd, rangeStart, remoteEffects, study],
  )
  const eventMap = useMemo(() => {
    const map = new Map(study?.events.map((event) => [event.id, event]) ?? [])
    for (const effect of remoteEffects ?? []) {
      if (map.has(effect.eventId)) continue
      map.set(effect.eventId, {
        id: effect.eventId,
        name: effect.eventId,
        hazardType: effect.hazardType,
        alertLevel: effect.alertLevel,
        alertScore: null,
        startAt: effect.startAt,
        endAt: effect.endAt,
        geographyIds: effect.geographyIds,
      })
    }
    return map
  }, [remoteEffects, study])
  const candidateEvents = useMemo(
    () => {
      if (cohort === 'major') return study?.events.filter((event) => event.startAt.slice(0, 10) >= rangeStart && event.startAt.slice(0, 10) <= rangeEnd && (hazard === 'all' || event.hazardType === hazard)) ?? []
      return [...new Set(sourceEffects.map((effect) => effect.eventId))]
        .map((id) => eventMap.get(id))
        .filter((event): event is StudyEvent => Boolean(event))
    },
    [cohort, eventMap, hazard, rangeEnd, rangeStart, sourceEffects, study],
  )
  const specification = useMemo(
    () => sourceEffects.filter((effect) => {
      const event = eventMap.get(effect.eventId)
      return effect.scope === scope && effect.windowDays === windowDays && effect.timing === timing &&
        effect.topicId === topic && Boolean(event) && (hazard === 'all' || event?.hazardType === hazard)
    }),
    [eventMap, hazard, scope, sourceEffects, timing, topic, windowDays],
  )
  const completeEffects = useMemo(() => specification.filter((effect) => effect.complete), [specification])
  const includedEffects = useMemo(
    () => completeEffects.filter((effect) => !excludeOverlaps || !effect.overlap),
    [completeEffects, excludeOverlaps],
  )
  const includedIds = useMemo(() => new Set(includedEffects.map((effect) => effect.eventId)), [includedEffects])
  const timeline = useMemo(
    () => study ? buildTimeline(study, includedEffects, topic, scope, measure, timing) : [],
    [includedEffects, measure, scope, study, timing, topic],
  )

  const topicSummaries = (Object.keys(TOPICS) as TopicId[]).map((topicId) => {
    const rows = sourceEffects.filter((effect) => effect.topicId === topicId && effect.scope === scope && effect.windowDays === windowDays && effect.timing === timing && effect.complete && includedIds.has(effect.eventId))
    return {
      topic: topicId,
      count: rows.length,
      matched: median(rows.map((effect) => effect.matchedPercentChange).filter((value): value is number => value != null)),
      political: median(rows.map((effect) => effect.politicalPercentChange).filter((value): value is number => value != null)),
      share: median(rows.map((effect) => effect.politicalShareChange).filter((value): value is number => value != null)),
    }
  })

  const values = includedEffects.map((effect) => effectValue(effect, measure)).filter((value): value is number => value != null)
  const pooledMedian = median(values)
  const lowerQuartile = quartile(values, 0.25)
  const upperQuartile = quartile(values, 0.75)
  const positiveShare = values.length ? values.filter((value) => value > 0).length / values.length * 100 : null
  const hazardSummaries = (['flood', 'wildfire'] as HazardType[]).map((hazardType) => {
    const hazardValues = includedEffects
      .filter((effect) => eventMap.get(effect.eventId)?.hazardType === hazardType)
      .map((effect) => effectValue(effect, measure))
      .filter((value): value is number => value != null)
    return { hazard: hazardType, count: hazardValues.length, value: median(hazardValues) }
  })
  const countryRows = [...new Set(candidateEvents.flatMap((event) => event.geographyIds))].map((country) => {
    const countryValues = includedEffects
      .filter((effect) => eventMap.get(effect.eventId)?.geographyIds.includes(country))
      .map((effect) => effectValue(effect, measure))
      .filter((value): value is number => value != null)
    return { country, count: countryValues.length, value: median(countryValues) }
  }).filter((row) => row.count >= countryRankingMinimum).sort((left, right) => {
    if (countryRankingSort === 'events') {
      return right.count - left.count || Math.abs(right.value ?? 0) - Math.abs(left.value ?? 0)
    }
    return Math.abs(right.value ?? 0) - Math.abs(left.value ?? 0) || right.count - left.count
  }).slice(0, 8)
  const rankedEvents = includedEffects
    .map((effect) => ({ effect, event: eventMap.get(effect.eventId), value: effectValue(effect, measure) }))
    .filter((row): row is typeof row & { event: StudyEvent; value: number } => Boolean(row.event) && row.value != null)
    .sort((left, right) => right.value - left.value)
    .slice(0, 10)

  const selectHypothesis = (id: typeof HYPOTHESES[number]['id']) => {
    setHypothesis(id)
    if (id === 'attention') { setTopic('climate_change'); setMeasure('matched') }
    if (id === 'spillover') { setTopic('electric_vehicles'); setMeasure('matched') }
    if (id === 'geography') { setTopic('climate_change'); setMeasure('matched'); setScope('other_eu27') }
    if (id === 'political') { setTopic('climate_change'); setMeasure('political_share') }
  }

  if (!study) {
    return <main className="lab-view"><div className="lab-loading"><Activity size={22} /> Preparing event-study results…</div></main>
  }

  const effectiveRangeStart = rangeStart || study.coverage.start
  const effectiveRangeEnd = rangeEnd || study.coverage.end
  const periodStartDay = toUtcDay(study.coverage.start)
  const periodEndDay = toUtcDay(study.coverage.end)
  const rangeStartDay = toUtcDay(effectiveRangeStart)
  const rangeEndDay = toUtcDay(effectiveRangeEnd)
  const periodSpan = Math.max(1, periodEndDay - periodStartDay)
  const rangeStyle = {
    '--range-start': `${((rangeStartDay - periodStartDay) / periodSpan) * 100}%`,
    '--range-end': `${((rangeEndDay - periodStartDay) / periodSpan) * 100}%`,
  } as CSSProperties
  const excludedDays = (study.coverage.excludedPeriods ?? []).reduce((total, period) => {
    const overlapStart = Math.max(rangeStartDay, toUtcDay(period.start))
    const overlapEnd = Math.min(rangeEndDay, toUtcDay(period.end))
    return total + Math.max(0, overlapEnd - overlapStart + 1)
  }, 0)
  const observedDays = inclusiveDays(effectiveRangeStart, effectiveRangeEnd) - excludedDays
  const formatRangeDate = (value: string) => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`))
  const periodLabel = selectedPeriod === 'all' ? 'Full period' : selectedPeriod

  return (
    <main className="lab-view">
      <section className="lab-hero">
        <div><span className="eyebrow">Analysis Lab · {periodLabel}</span><h1>Compare attention and event activity.</h1><p>Study individual flood and wildfire responses or compare rolling event exposure with climate and electric-vehicle attention across countries, the EU and the world.</p></div>
        <div className="lab-hero-controls">
          <label className="lab-year-select"><span>Study period</span><select aria-label="Study period" value={selectedPeriod} onChange={(event) => updateSelectedPeriod(event.target.value)}><option value="all">Whole available period</option>{availableYears.map((year) => <option key={year} value={year}>{year}</option>)}</select></label>
          <div className="lab-status"><span className="live-dot" /><div><strong>{observedDays} observed days</strong><small>{study.coverage.geographies} markets · {excludedDays ? 'provider gap excluded' : 'both topics'}</small></div></div>
          <div className="lab-date-range">
            <div className="lab-date-range-summary"><span>Date range</span><strong>{formatRangeDate(effectiveRangeStart)} — {formatRangeDate(effectiveRangeEnd)}</strong></div>
            <div className="lab-range-slider" style={rangeStyle}>
              <div className="lab-range-track" aria-hidden="true"><span /></div>
              <input className="range-start" aria-label="Analysis start date" type="range" min={periodStartDay} max={periodEndDay} value={rangeStartDay} onChange={(event) => setRangeStart(fromUtcDay(Math.min(Number(event.target.value), rangeEndDay)))} />
              <input className="range-end" aria-label="Analysis end date" type="range" min={periodStartDay} max={periodEndDay} value={rangeEndDay} onChange={(event) => setRangeEnd(fromUtcDay(Math.max(Number(event.target.value), rangeStartDay)))} />
            </div>
          </div>
        </div>
      </section>

      <div className="lab-mode-switch" role="tablist" aria-label="Analysis mode"><button role="tab" aria-selected={mode === 'study'} className={mode === 'study' ? 'active' : ''} onClick={() => setMode('study')}>Event study</button><button role="tab" aria-selected={mode === 'activity'} className={mode === 'activity' ? 'active' : ''} onClick={() => setMode('activity')}>Event activity</button><button role="tab" aria-selected={mode === 'timeline'} className={mode === 'timeline' ? 'active' : ''} onClick={() => setMode('timeline')}>Attention timeline</button></div>

      {mode === 'study' ? <><section className="lab-hypothesis-strip" aria-label="Research hypotheses">
        {HYPOTHESES.map((item) => <button key={item.id} className={hypothesis === item.id ? 'active' : ''} onClick={() => selectHypothesis(item.id)}><span>{item.number}</span><div><strong>{item.title}</strong><small>{item.copy}</small></div>{hypothesis === item.id && <Check size={15} />}</button>)}
      </section>

      <section className="lab-workspace">
        <aside className="study-config-panel">
          <div className="lab-section-heading"><span>1</span><div><small>Study design</small><h2>Configure comparison</h2></div></div>
          <div className="lab-form">
            <label><span>Event alert tier</span><select value={cohort} onChange={(event) => setCohort(event.target.value as AlertCohort)}><option value="all">All tiers · Green, Orange, Red</option><option value="major">Major tiers · Orange and Red</option><option value="green">Green tier only</option></select></label>
            <label><span>Event type</span><select value={hazard} onChange={(event) => setHazard(event.target.value as typeof hazard)}><option value="all">Floods and wildfires</option><option value="flood">Floods</option><option value="wildfire">Wildfires</option></select></label>
            <label><span>Media group</span><select value={scope} onChange={(event) => setScope(event.target.value as LabScope)}>{Object.entries(SCOPES).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select><small>{SCOPES[scope].description}</small></label>
            <label><span>Timing</span><select value={timing} onChange={(event) => setTiming(event.target.value as LabTiming)}><option value="onset">Response from event onset</option><option value="persistence">Persistence after event end</option></select></label>
            <label><span>Comparison window</span><select value={windowDays} onChange={(event) => setWindowDays(Number(event.target.value))}>{study.windows.map((window) => <option key={window} value={window}>{window} days before / after</option>)}</select></label>
            <label><span>Chart topic</span><select value={topic} onChange={(event) => setTopic(event.target.value as TopicId)}>{Object.entries(TOPICS).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select></label>
            <label><span>Chart measure</span><select value={measure} onChange={(event) => setMeasure(event.target.value as LabMeasure)}>{Object.entries(MEASURES).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select></label>
            <label className="overlap-control"><input type="checkbox" checked={excludeOverlaps} onChange={(event) => setExcludeOverlaps(event.target.checked)} /><span>Exclude same-country overlapping events</span></label>
          </div>
          <div className="analysis-definition"><Info size={15} /><p><strong>Associational estimate.</strong> Every event is compared with its own pre-event baseline. Results describe indexed publishing activity, not a causal effect or public opinion.</p></div>
        </aside>

        <div className="lab-results-panel">
          {remoteLoading && <div className="analysis-loading"><Activity size={15} /> Loading the selected all-alert cohort…</div>}
          {remoteError && <div className="analysis-loading error"><CircleAlert size={15} /> {remoteError}</div>}
          <div className="cohort-flow" aria-label="Event cohort eligibility">
            <div><strong>{candidateEvents.length}</strong><span>Cohort candidates</span></div><ArrowRight size={15} />
            <div><strong>{completeEffects.length}</strong><span>Complete windows</span></div><ArrowRight size={15} />
            <div className="included"><strong>{includedEffects.length}</strong><span>Included events</span></div>
          </div>

          {!includedEffects.length ? <div className="lab-empty"><CircleAlert size={20} /><strong>No eligible events for this specification</strong><p>Try including overlaps, selecting both hazards or using a shorter window.</p></div> : <>
            <section className="pooled-result">
              <div className="result-heading"><div><span className="eyebrow">Pooled response</span><h2>{TOPICS[topic].label} · {MEASURES[measure].short}</h2></div><span>{SCOPES[scope].label} · {timing === 'onset' ? 'onset' : 'post-event'} · {windowDays}d</span></div>
              <div className="headline-result-grid">
                <article><small>Median event response</small><strong>{formatEffect(pooledMedian, measure, 1)}</strong><span>Across {values.length} usable event estimates</span></article>
                <article><small>Middle 50% of events</small><strong>{formatEffect(lowerQuartile, measure)} to {formatEffect(upperQuartile, measure)}</strong><span>Event-level interquartile range</span></article>
                <article><small>Events with an increase</small><strong>{positiveShare == null ? '—' : `${positiveShare.toFixed(0)}%`}</strong><span>Direction only, not significance</span></article>
              </div>
              {cohort === 'major' ? <><div className="result-chart-heading"><div><strong>Median event-time pattern</strong><small>Daily change from each event’s own {windowDays}-day baseline · day 0 is {timing === 'onset' ? 'event onset' : 'the first day after event end'}</small></div><span><i style={{ background: TOPICS[topic].color }} />{TOPICS[topic].label}</span></div><StudyTimeline points={timeline} measure={measure} timing={timing} /></> : <div className="all-alert-chart-note"><Info size={16} /><div><strong>Detailed timelines remain available for the major-event cohort.</strong><p>The all-alert table serves event-level effects without downloading millions of daily event points. Use Event activity for the full time-series view.</p></div></div>}
            </section>

            <section className="topic-result-grid">
              {topicSummaries.map((summary) => <article key={summary.topic} data-topic={summary.topic}><header><i style={{ background: TOPICS[summary.topic].color }} /><div><strong>{TOPICS[summary.topic].label}</strong><small>{summary.count} events</small></div></header><dl><div><dt>All attention</dt><dd>{formatEffect(summary.matched, 'matched')}</dd></div><div><dt>Political volume</dt><dd>{formatEffect(summary.political, 'political')}</dd></div><div><dt>Political share</dt><dd>{formatEffect(summary.share, 'political_share', 1)}</dd></div></dl></article>)}
            </section>

            <section className="comparison-grid">
              <article className="hazard-comparison"><div className="result-heading"><div><span className="eyebrow">Event type</span><h3>Floods versus wildfires</h3></div></div>{hazardSummaries.map((row) => <div className="comparison-row" key={row.hazard}><span>{row.hazard === 'flood' ? 'Floods' : 'Wildfires'}<small>{row.count} events</small></span><i><b style={{ width: `${Math.min(100, Math.abs(row.value ?? 0))}%`, marginLeft: (row.value ?? 0) < 0 ? 'auto' : undefined }} /></i><strong>{formatEffect(row.value, measure)}</strong></div>)}</article>
              <article className="country-comparison">
                <div className="result-heading"><div><span className="eyebrow">Affected geography</span><h3>{countryRankingSort === 'events' ? 'Most frequently affected countries' : 'Largest country responses'}</h3></div><small>Event count and median response</small></div>
                <div className="country-ranking-controls">
                  <label><span>Minimum eligible events</span><select aria-label="Minimum eligible events" value={countryRankingMinimum} onChange={(event) => setCountryRankingMinimum(Number(event.target.value))}>{COUNTRY_RANKING_THRESHOLDS.map((minimum) => <option key={minimum} value={minimum}>{minimum}+</option>)}</select></label>
                  <label><span>Sort countries by</span><select aria-label="Sort countries by" value={countryRankingSort} onChange={(event) => setCountryRankingSort(event.target.value as CountryRankingSort)}><option value="events">Number of events</option><option value="response">Absolute response</option></select></label>
                </div>
                {countryRows.length ? countryRows.map((row) => <div className="country-row" key={row.country}><span>{geographyLabels[row.country] || row.country}</span><small>{row.count} event{row.count === 1 ? '' : 's'}</small><strong>{formatEffect(row.value, measure)}</strong></div>) : <p className="country-ranking-empty">No country has at least {countryRankingMinimum} eligible events for this specification. Lower the threshold or select the all-alert cohort to inspect repeated activity.</p>}
              </article>
            </section>

            <section className="ranked-events"><div className="result-heading"><div><span className="eyebrow">Event estimates</span><h3>Largest increases in this cohort</h3></div><small>Select an event to inspect its daily evidence</small></div><div className="ranked-event-table" role="table" aria-label="Ranked event effects"><div role="row"><span role="columnheader">Event</span><span role="columnheader">Type</span><span role="columnheader">Start</span><span role="columnheader">Change</span></div>{rankedEvents.map(({ event, value }) => <button role="row" key={event.id} onClick={() => onOpenEvent(event.id)}><span role="cell"><strong>{eventLabel(event, geographyLabels)}</strong><small>{event.alertLevel} alert</small></span><span role="cell">{event.hazardType === 'flood' ? 'Flood' : 'Wildfire'}</span><span role="cell">{new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(event.startAt))}</span><span role="cell"><b>{formatEffect(value, measure, 1)}</b><ArrowRight size={13} /></span></button>)}</div></section>
          </>}
        </div>
      </section>
      </> : mode === 'activity' ? <EventActivityView coverageStart={effectiveRangeStart} coverageEnd={effectiveRangeEnd} geographyLabels={geographyLabels} eventGeographies={eventGeographies} /> : <AttentionTimeline coverageStart={effectiveRangeStart} coverageEnd={effectiveRangeEnd} geographyLabels={geographyLabels} keyEvents={catalogueEvents} />}
    </main>
  )
}
