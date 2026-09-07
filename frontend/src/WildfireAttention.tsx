import { useMemo, useState } from 'react'
import { ArrowRight, CircleAlert, Flame, Info } from 'lucide-react'
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export type WildfireAttentionMeasure = 'matched' | 'political' | 'political_share'
export type WildfireAttentionScale = 'absolute' | 'relative'
export type WildfireAttentionScope = 'affected' | 'other_eu27' | 'rest_world' | 'global'
export type WildfireAttentionTopic = 'climate_change' | 'electric_vehicles'

export type WildfireAttentionEvent = {
  id: string
  name: string
  hazardType: 'wildfire' | 'flood'
  alertLevel: 'Green' | 'Orange' | 'Red'
  startAt: string
  geographyIds: string[]
  severity?: number | null
  severityUnit?: string | null
}

export type WildfireAttentionEffect = {
  eventId: string
  hazardType: 'wildfire' | 'flood'
  scope: WildfireAttentionScope
  topicId: WildfireAttentionTopic
  windowDays: number
  timing: 'onset' | 'persistence'
  complete: boolean
  overlap: boolean
  matchedChange: number | null
  matchedPercentChange: number | null
  politicalChange: number | null
  politicalPercentChange: number | null
  politicalShareChange: number | null
}

export type WildfireAttentionRow = {
  event: WildfireAttentionEvent
  effect: WildfireAttentionEffect
  response: number
  areaHectares: number | null
  logArea: number | null
  expectedFromSeverity: number | null
  excessFromSeverity: number | null
}

type RowConfiguration = {
  scope: WildfireAttentionScope
  topic: WildfireAttentionTopic
  windowDays: number
  measure: WildfireAttentionMeasure
  scale: WildfireAttentionScale
  excludeOverlaps: boolean
}

const TOPICS: Record<WildfireAttentionTopic, string> = {
  climate_change: 'Climate change',
  electric_vehicles: 'Electric vehicles',
}

const SCOPES: Record<WildfireAttentionScope, { label: string; description: string }> = {
  affected: { label: 'Affected countries', description: 'Publishing markets directly affected by each fire' },
  other_eu27: { label: 'Other EU27', description: 'EU publishing markets excluding affected countries' },
  rest_world: { label: 'Rest of world', description: 'Non-EU markets excluding affected countries' },
  global: { label: 'Global', description: 'All 197 mapped publishing markets' },
}

const MEASURES: Record<WildfireAttentionMeasure, string> = {
  matched: 'All matching articles',
  political: 'Political articles',
  political_share: 'Political share',
}

function median(values: number[]) {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function responseValue(
  effect: WildfireAttentionEffect,
  measure: WildfireAttentionMeasure,
  scale: WildfireAttentionScale,
) {
  if (measure === 'political_share') return effect.politicalShareChange
  if (measure === 'matched') return scale === 'relative' ? effect.matchedPercentChange : effect.matchedChange
  return scale === 'relative' ? effect.politicalPercentChange : effect.politicalChange
}

export function reportedWildfireHectares(event: WildfireAttentionEvent) {
  if (event.hazardType !== 'wildfire' || event.severityUnit?.toLowerCase() !== 'ha') return null
  if (event.severity == null || !Number.isFinite(event.severity) || event.severity <= 0) return null
  return event.severity
}

export function addSeverityBenchmark(rows: WildfireAttentionRow[]) {
  const usable = rows.filter((row) => row.logArea != null)
  if (usable.length < 2) return { rows, correlation: null, usableCount: usable.length }

  const meanX = usable.reduce((total, row) => total + (row.logArea ?? 0), 0) / usable.length
  const meanY = usable.reduce((total, row) => total + row.response, 0) / usable.length
  const sumXX = usable.reduce((total, row) => total + ((row.logArea ?? 0) - meanX) ** 2, 0)
  const sumYY = usable.reduce((total, row) => total + (row.response - meanY) ** 2, 0)
  const sumXY = usable.reduce((total, row) => total + ((row.logArea ?? 0) - meanX) * (row.response - meanY), 0)
  const slope = sumXX > 0 ? sumXY / sumXX : 0
  const intercept = meanY - slope * meanX
  const correlation = sumXX > 0 && sumYY > 0 ? sumXY / Math.sqrt(sumXX * sumYY) : null

  return {
    rows: rows.map((row) => {
      if (row.logArea == null) return row
      const expectedFromSeverity = intercept + slope * row.logArea
      return { ...row, expectedFromSeverity, excessFromSeverity: row.response - expectedFromSeverity }
    }),
    correlation,
    usableCount: usable.length,
  }
}

export function buildWildfireAttentionRows(
  effects: WildfireAttentionEffect[],
  events: Map<string, WildfireAttentionEvent>,
  configuration: RowConfiguration,
) {
  const rows = effects.flatMap((effect): WildfireAttentionRow[] => {
    const event = events.get(effect.eventId)
    if (!event || event.hazardType !== 'wildfire' || effect.hazardType !== 'wildfire') return []
    if (!effect.complete || effect.scope !== configuration.scope || effect.topicId !== configuration.topic) return []
    if (effect.windowDays !== configuration.windowDays || effect.timing !== 'onset') return []
    if (configuration.excludeOverlaps && effect.overlap) return []
    const response = responseValue(effect, configuration.measure, configuration.scale)
    if (response == null || !Number.isFinite(response)) return []
    const areaHectares = reportedWildfireHectares(event)
    return [{
      event,
      effect,
      response,
      areaHectares,
      logArea: areaHectares == null ? null : Math.log10(areaHectares),
      expectedFromSeverity: null,
      excessFromSeverity: null,
    }]
  })
  return addSeverityBenchmark(rows)
}

function formatCompact(value: number) {
  return Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function formatArea(value: number | null) {
  return value == null ? 'Not reported' : `${formatCompact(value)} ha`
}

function formatResponse(value: number | null, measure: WildfireAttentionMeasure, scale: WildfireAttentionScale, digits = 1) {
  if (value == null || !Number.isFinite(value)) return '—'
  const sign = value > 0 ? '+' : ''
  if (measure === 'political_share') return `${sign}${value.toFixed(digits)} pp`
  if (scale === 'relative') return `${sign}${value.toFixed(digits)}%`
  return `${sign}${value.toFixed(digits)}/day`
}

function eventLabel(event: WildfireAttentionEvent, labels: Record<string, string>) {
  const country = event.geographyIds.map((id) => labels[id] || id.replaceAll('_', ' ')).join(', ')
  return country || event.name
}

function ScatterTooltip({
  active,
  payload,
  geographyLabels,
  measure,
  scale,
}: {
  active?: boolean
  payload?: { payload: WildfireAttentionRow }[]
  geographyLabels: Record<string, string>
  measure: WildfireAttentionMeasure
  scale: WildfireAttentionScale
}) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  return <div className="wildfire-scatter-tooltip">
    <strong>{eventLabel(row.event, geographyLabels)}</strong>
    <small>{new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(row.event.startAt))}</small>
    <dl>
      <div><dt>Reported area</dt><dd>{formatArea(row.areaHectares)}</dd></div>
      <div><dt>Attention response</dt><dd>{formatResponse(row.response, measure, scale)}</dd></div>
      <div><dt>Severity benchmark</dt><dd>{formatResponse(row.expectedFromSeverity, measure, scale)}</dd></div>
      <div><dt>Excess attention</dt><dd>{formatResponse(row.excessFromSeverity, measure, scale)}</dd></div>
    </dl>
  </div>
}

export default function WildfireAttention({
  effects,
  eventMap,
  geographyLabels,
  windows,
  cohort,
  onCohortChange,
  scope,
  onScopeChange,
  windowDays,
  onWindowDaysChange,
  topic,
  onTopicChange,
  measure,
  onMeasureChange,
  excludeOverlaps,
  onExcludeOverlapsChange,
  remoteLoading,
  remoteError,
  onOpenEvent,
}: {
  effects: WildfireAttentionEffect[]
  eventMap: Map<string, WildfireAttentionEvent>
  geographyLabels: Record<string, string>
  windows: number[]
  cohort: 'major' | 'green' | 'all'
  onCohortChange: (value: 'major' | 'green' | 'all') => void
  scope: WildfireAttentionScope
  onScopeChange: (value: WildfireAttentionScope) => void
  windowDays: number
  onWindowDaysChange: (value: number) => void
  topic: WildfireAttentionTopic
  onTopicChange: (value: WildfireAttentionTopic) => void
  measure: WildfireAttentionMeasure
  onMeasureChange: (value: WildfireAttentionMeasure) => void
  excludeOverlaps: boolean
  onExcludeOverlapsChange: (value: boolean) => void
  remoteLoading: boolean
  remoteError: string | null
  onOpenEvent: (id: string) => void
}) {
  const [scale, setScale] = useState<WildfireAttentionScale>('absolute')
  const [ranking, setRanking] = useState<'response' | 'excess'>('response')
  const analysis = useMemo(() => buildWildfireAttentionRows(effects, eventMap, {
    scope,
    topic,
    windowDays,
    measure,
    scale,
    excludeOverlaps,
  }), [eventMap, effects, excludeOverlaps, measure, scale, scope, topic, windowDays])
  const rows = analysis.rows
  const scatterRows = rows.filter((row): row is WildfireAttentionRow & { logArea: number; areaHectares: number } => row.logArea != null && row.areaHectares != null)
  const rankedRows = [...rows].sort((left, right) => {
    if (ranking === 'excess') return (right.excessFromSeverity ?? Number.NEGATIVE_INFINITY) - (left.excessFromSeverity ?? Number.NEGATIVE_INFINITY)
    return right.response - left.response
  }).slice(0, 12)
  const responses = rows.map((row) => row.response)
  const medianResponse = median(responses)
  const positiveShare = rows.length ? responses.filter((value) => value > 0).length / rows.length * 100 : null
  const strongest = [...rows].sort((left, right) => right.response - left.response)[0]
  const correlationLabel = analysis.correlation == null ? '—' : analysis.correlation.toFixed(2)

  return <section className="wildfire-workspace">
    <aside className="wildfire-controls">
      <div className="lab-section-heading"><span><Flame size={14} /></span><div><small>Fire selection</small><h2>Configure response</h2></div></div>
      <div className="lab-form">
        <label><span>Event alert tier</span><select aria-label="Wildfire alert tier" value={cohort} onChange={(event) => onCohortChange(event.target.value as typeof cohort)}><option value="all">All tiers · Green, Orange, Red</option><option value="major">Major tiers · Orange and Red</option><option value="green">Green tier only</option></select></label>
        <label><span>Media group</span><select aria-label="Wildfire media group" value={scope} onChange={(event) => onScopeChange(event.target.value as WildfireAttentionScope)}>{Object.entries(SCOPES).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select><small>{SCOPES[scope].description}</small></label>
        <label><span>Response window</span><select aria-label="Wildfire response window" value={windowDays} onChange={(event) => onWindowDaysChange(Number(event.target.value))}>{windows.map((window) => <option key={window} value={window}>{window} days before / after onset</option>)}</select></label>
        <label><span>Attention topic</span><select aria-label="Wildfire attention topic" value={topic} onChange={(event) => onTopicChange(event.target.value as WildfireAttentionTopic)}>{Object.entries(TOPICS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label><span>Attention measure</span><select aria-label="Wildfire attention measure" value={measure} onChange={(event) => onMeasureChange(event.target.value as WildfireAttentionMeasure)}>{Object.entries(MEASURES).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label><span>Change shown</span><select aria-label="Wildfire change shown" value={scale} disabled={measure === 'political_share'} onChange={(event) => setScale(event.target.value as WildfireAttentionScale)}><option value="absolute">Added articles per day</option><option value="relative">Percentage from baseline</option></select><small>{measure === 'political_share' ? 'Political share is always shown in percentage points.' : scale === 'absolute' ? 'Best for identifying the largest volume changes.' : 'Better for comparing differently sized media markets.'}</small></label>
        <label className="overlap-control"><input aria-label="Exclude overlapping wildfires" type="checkbox" checked={excludeOverlaps} onChange={(event) => onExcludeOverlapsChange(event.target.checked)} /><span>Exclude same-country overlapping events</span></label>
      </div>
      <div className="analysis-definition"><Info size={15} /><p><strong>Observed response, not causal effect.</strong> Each fire is compared with its own pre-event baseline. GDACS area is cumulative and may be revised after onset.</p></div>
    </aside>

    <div className="wildfire-results">
      {remoteLoading && <div className="analysis-loading"><Flame size={15} /> Loading the selected wildfire cohort…</div>}
      {remoteError && <div className="analysis-loading error"><CircleAlert size={15} /> {remoteError}</div>}
      <section className="wildfire-overview-card">
        <div className="result-heading"><div><span className="eyebrow">Wildfire attention</span><h2>Which fires broke through?</h2></div><span>{SCOPES[scope].label} · onset · {windowDays}d</span></div>
        <p className="wildfire-intro">Rank observed changes in publishing attention, then compare each fire with the response associated with its reported burned area.</p>
        <div className="wildfire-kpis">
          <article><small>Eligible fire responses</small><strong>{rows.length}</strong><span>Complete {windowDays}-day windows{excludeOverlaps ? ' without same-country overlaps' : ''}</span></article>
          <article><small>Median response</small><strong>{formatResponse(medianResponse, measure, scale)}</strong><span>{positiveShare == null ? 'No usable responses' : `${positiveShare.toFixed(0)}% of fires increased attention`}</span></article>
          <article><small>Largest observed increase</small><strong>{strongest ? formatResponse(strongest.response, measure, scale) : '—'}</strong><span>{strongest ? eventLabel(strongest.event, geographyLabels) : 'No eligible event'}</span></article>
          <article><small>Severity association</small><strong>{correlationLabel}</strong><span>Pearson r across {analysis.usableCount} fires with reported hectares</span></article>
        </div>
      </section>

      {!rows.length ? <div className="lab-empty"><CircleAlert size={20} /><strong>No eligible wildfire responses</strong><p>Try a different window, include overlaps, or use the absolute-change measure when the pre-event baseline was zero.</p></div> : <>
        <section className="wildfire-scatter-card">
          <div className="result-heading"><div><span className="eyebrow">Physical severity</span><h3>Does a larger burned area attract more attention?</h3></div><small>{scatterRows.length} fires with GDACS hectares</small></div>
          {scatterRows.length >= 2 ? <>
            <div className="wildfire-scatter" aria-label="Reported wildfire area versus attention response">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 16, right: 18, bottom: 22, left: 8 }}>
                  <CartesianGrid stroke="#dce4df" strokeDasharray="3 5" />
                  <XAxis type="number" dataKey="logArea" name="Reported burned area" domain={['dataMin', 'dataMax']} tickFormatter={(value) => formatCompact(10 ** Number(value))} tick={{ fontSize: 8, fill: '#738179' }} label={{ value: 'GDACS reported burned area (ha · log scale)', position: 'insideBottom', offset: -14, fontSize: 8, fill: '#718078' }} />
                  <YAxis type="number" dataKey="response" name="Attention response" width={48} tickFormatter={(value) => formatCompact(Number(value))} tick={{ fontSize: 8, fill: '#738179' }} />
                  <ReferenceLine y={0} stroke="#9eaaa4" />
                  <Tooltip cursor={{ strokeDasharray: '3 4' }} content={<ScatterTooltip geographyLabels={geographyLabels} measure={measure} scale={scale} />} />
                  <Scatter data={scatterRows} fill="#e46643" fillOpacity={0.78} stroke="#a8472e" strokeWidth={1} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <div className="wildfire-benchmark-note"><Info size={15} /><p><strong>Severity-only benchmark.</strong> “Excess attention” is the residual from a simple line relating the response to log reported hectares within this filtered cohort. It is descriptive, not an out-of-sample prediction.</p></div>
          </> : <div className="wildfire-chart-empty"><CircleAlert size={18} /><p>At least two eligible fires with hectare estimates are required for the severity comparison.</p></div>}
        </section>

        <section className="wildfire-ranking-card">
          <div className="result-heading"><div><span className="eyebrow">Fire ranking</span><h3>{ranking === 'response' ? 'Largest observed attention increases' : 'Most attention beyond the severity benchmark'}</h3></div><label className="wildfire-ranking-select"><span>Rank by</span><select aria-label="Rank wildfires by" value={ranking} onChange={(event) => setRanking(event.target.value as typeof ranking)}><option value="response">Observed response</option><option value="excess">Excess versus severity</option></select></label></div>
          <div className="wildfire-ranking-table" role="table" aria-label="Ranked wildfire attention responses">
            <div role="row"><span role="columnheader">Fire</span><span role="columnheader">Reported area</span><span role="columnheader">Response</span><span role="columnheader">Severity benchmark</span><span role="columnheader">Excess attention</span></div>
            {rankedRows.map((row) => <button role="row" key={row.event.id} onClick={() => onOpenEvent(row.event.id)}><span role="cell"><strong>{eventLabel(row.event, geographyLabels)}</strong><small>{row.event.alertLevel} · {new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(row.event.startAt))}</small></span><span role="cell">{formatArea(row.areaHectares)}</span><span role="cell"><b>{formatResponse(row.response, measure, scale)}</b></span><span role="cell">{formatResponse(row.expectedFromSeverity, measure, scale)}</span><span role="cell"><b className={(row.excessFromSeverity ?? 0) >= 0 ? 'positive' : 'negative'}>{formatResponse(row.excessFromSeverity, measure, scale)}</b><ArrowRight size={13} /></span></button>)}
          </div>
        </section>
      </>}
    </div>
  </section>
}
