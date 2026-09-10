import type { AttentionChartPoint } from './AttentionChart'
import { summarizeChange } from './utils'
import type { StudyEffect } from './AnalysisLab'

export type AnalysisSelection = {
  topic: StudyEffect['topicId']
  scope: StudyEffect['scope'] | 'eu27' | 'international'
  measure: 'matched' | 'political' | 'political_share'
  windowDays: number
  timing: StudyEffect['timing']
}
export const DEFAULT_SELECTION: AnalysisSelection = {
  topic: 'climate_change', scope: 'affected', measure: 'matched', windowDays: 14, timing: 'onset',
}
export function readAnalysisSelection(search: string): AnalysisSelection {
  const params = new URLSearchParams(search)
  const choice = <T extends string>(key: string, values: readonly T[], fallback: T): T => {
    const value = params.get(key)
    return values.includes(value as T) ? value as T : fallback
  }
  return {
    topic: choice('topic', ['climate_change', 'electric_vehicles'], DEFAULT_SELECTION.topic),
    scope: choice('scope', ['affected', 'other_eu27', 'rest_world', 'global', 'eu27', 'international'], DEFAULT_SELECTION.scope),
    measure: choice('measure', ['matched', 'political', 'political_share'], DEFAULT_SELECTION.measure),
    windowDays: [7, 14, 28].includes(Number(params.get('window'))) ? Number(params.get('window')) : 14,
    timing: choice('timing', ['onset', 'persistence'], DEFAULT_SELECTION.timing),
  }
}
export function selectionUrl(href: string, eventId: string | null, selection: AnalysisSelection) {
  const url = new URL(href)
  const parameters = { event: eventId, topic: selection.topic, scope: selection.scope, measure: selection.measure, window: String(selection.windowDays), timing: selection.timing }
  for (const [key, value] of Object.entries(parameters)) {
    if (eventId && value) url.searchParams.set(key, value)
    else url.searchParams.delete(key)
  }
  return url
}
export function comparisonDates(start: string, end: string, windowDays: number, timing: AnalysisSelection['timing']) {
  const shift = (date: string, days: number) => new Date(Date.parse(`${date.slice(0, 10)}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10)
  return {
    before: Array.from({ length: windowDays }, (_, index) => shift(start, index - windowDays)),
    after: Array.from({ length: windowDays }, (_, index) => shift(timing === 'onset' ? start : end, index + (timing === 'onset' ? 0 : 1))),
  }
}
export function effectValue(effect: StudyEffect, measure: AnalysisSelection['measure']) {
  return measure === 'matched' ? effect.matchedPercentChange : measure === 'political' ? effect.politicalPercentChange : effect.politicalShareChange
}
export function median(values: number[]) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}
/** Require usable estimates for the same event in every requested window. */
export function windowSensitivity(effects: StudyEffect[], windows: number[], measure: AnalysisSelection['measure'], excludeOverlaps = true) {
  const eligible = effects.filter((effect) => effect.complete && (!excludeOverlaps || !effect.overlap) && effectValue(effect, measure) != null)
  const ids = windows.map((window) => new Set(eligible.filter((effect) => effect.windowDays === window).map((effect) => effect.eventId)))
  const common = new Set([...ids[0] ?? []].filter((id) => ids.every((set) => set.has(id))))
  return windows.map((windowDays) => {
    const rows = eligible.filter((effect) => effect.windowDays === windowDays)
    const fixed = rows.filter((effect) => common.has(effect.eventId))
    return { windowDays, count: rows.length, median: median(rows.map((effect) => effectValue(effect, measure)!)), fixedCount: fixed.length, fixedMedian: median(fixed.map((effect) => effectValue(effect, measure)!)) }
  })
}
/** A transparent display flag, not an inferential threshold. */
export function lowBaseline(total: number | null) { return total != null && total < 20 }
export function countEvidence(effect: { windowDays: number; matchedPreMean?: number | null; matchedPostMean?: number | null; politicalPreMean?: number | null; politicalPostMean?: number | null }, measure: AnalysisSelection['measure']) {
  const political = measure === 'political'
  const before = political ? effect.politicalPreMean : effect.matchedPreMean
  const after = political ? effect.politicalPostMean : effect.matchedPostMean
  if (before == null || after == null) return 'Counts unavailable'
  const change = after - before
  return `${measure === 'political_share' ? 'Matched denominator: ' : ''}${before.toFixed(2)} → ${after.toFixed(2)} ${political ? 'political ' : ''}URLs/day · ${change > 0 ? '+' : ''}${change.toFixed(2)}/day · ${(before * effect.windowDays).toFixed(0)} baseline URLs${lowBaseline(before * effect.windowDays) ? ' · Low baseline (<20 URLs)' : ''}`
}

/** Share is a ratio of period totals, never an unweighted mean of daily shares. */
export function summarizeEventComparison(points: AttentionChartPoint[], start: string, end: string, selection: AnalysisSelection) {
  const { windowDays, timing, topic, measure } = selection
  const byDate = new Map(points.map((point) => [point.date, point]))
  const dates = comparisonDates(start, end, windowDays, timing)
  const collect = (dates: string[], field: string) => {
    const values: number[] = []
    const missing: string[] = []
    for (const date of dates) {
      const value = byDate.get(date)?.[field]
      if (typeof value === 'number' && Number.isFinite(value)) values.push(value)
      else missing.push(date)
    }
    return { values, missing }
  }
  const field = measure === 'political_share' ? `${topic}_political` : topic
  const before = collect(dates.before, field)
  const after = collect(dates.after, field)
  const beforeMatched = collect(dates.before, `${topic}_matched`)
  const afterMatched = collect(dates.after, `${topic}_matched`)
  const total = (values: number[]) => values.reduce((a, b) => a + b, 0)
  let result = before.missing.length || after.missing.length ? null : summarizeChange(before.values, after.values)
  if (measure === 'political_share' && result) {
    const beforeTotal = total(beforeMatched.values)
    const afterTotal = total(afterMatched.values)
    if (beforeMatched.missing.length || afterMatched.missing.length || !beforeTotal || !afterTotal) result = null
    else {
      const beforeMean = total(before.values) / beforeTotal * 100
      const afterMean = total(after.values) / afterTotal * 100
      result = { beforeMean, afterMean, difference: afterMean - beforeMean, percentChange: null }
    }
  }
  return { before, after, result, baselineTotal: total(measure === 'political_share' ? beforeMatched.values : before.values), comparisonTotal: total(measure === 'political_share' ? afterMatched.values : after.values) }
}
