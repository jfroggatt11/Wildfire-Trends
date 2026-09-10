import { describe, expect, it } from 'vitest'
import study2025 from '../public/data/event-study.json?raw'
import study2026 from '../public/data/event-study-2026.json?raw'
import { DEFAULT_SELECTION, comparisonDates, countEvidence, readAnalysisSelection, selectionUrl, summarizeEventComparison, windowSensitivity } from './analysisEvidence'
import type { AnalysisSelection } from './analysisEvidence'
import { buildTimeline } from './AnalysisLab'
import type { EventStudyData, StudyEffect } from './AnalysisLab'
import { buildEventChart } from './App'
import type { AttentionChartPoint } from './AttentionChart'

const effect = (eventId: string, windowDays: number, value: number | null, overrides: Partial<StudyEffect> = {}) => ({ eventId, windowDays, matchedPercentChange: value, complete: true, overlap: false, ...overrides }) as StudyEffect

describe('shareable analysis selections', () => {
  it('round-trips every supported scope, measure, timing and topic without changing unrelated URL state', () => {
    for (const scope of ['affected', 'other_eu27', 'rest_world', 'global', 'eu27', 'international'] as const) {
      for (const measure of ['matched', 'political', 'political_share'] as const) {
        for (const timing of ['onset', 'persistence'] as const) {
          const selection: AnalysisSelection = { scope, measure, timing, topic: 'electric_vehicles', windowDays: 28 }
          const url = selectionUrl('https://example.org/?preview=1#map', 'gdacs:FL:1', selection)
          expect(readAnalysisSelection(url.search)).toEqual(selection)
          expect(url.searchParams.get('event')).toBe('gdacs:FL:1')
          expect(url.searchParams.get('preview')).toBe('1')
          expect(url.hash).toBe('#map')
        }
      }
    }
  })
  it('rejects invalid query options and clears analysis parameters on close', () => {
    expect(readAnalysisSelection('?window=-14&scope=invalid&timing=bad&topic=bad&measure=bad')).toEqual(DEFAULT_SELECTION)
    const url = selectionUrl('https://example.org/?event=abc&scope=global&topic=climate_change&preview=1', null, DEFAULT_SELECTION)
    expect(url.search).toBe('?preview=1')
  })
  it('includes onset day and preserves a cross-year baseline for post-end comparisons', () => {
    expect(comparisonDates('2026-01-01T18:00:00Z', '2026-01-03', 2, 'onset')).toEqual({ before: ['2025-12-30', '2025-12-31'], after: ['2026-01-01', '2026-01-02'] })
    expect(comparisonDates('2026-01-01', '2026-01-03', 2, 'persistence')).toEqual({ before: ['2025-12-30', '2025-12-31'], after: ['2026-01-04', '2026-01-05'] })
  })
})

describe('evidence and fixed event cohorts', () => {
  it('intersects eligibility across every window including overlap and measure availability', () => {
    const effects = [effect('A', 7, 10), effect('A', 14, 20), effect('A', 28, 30), effect('B', 7, 100), effect('B', 14, 200), effect('B', 28, 300, { overlap: true }), effect('C', 7, 500), effect('C', 14, null), effect('C', 28, 900)]
    expect(windowSensitivity(effects, [7, 14, 28], 'matched')).toEqual([
      { windowDays: 7, count: 3, median: 100, fixedCount: 1, fixedMedian: 10 },
      { windowDays: 14, count: 2, median: 110, fixedCount: 1, fixedMedian: 20 },
      { windowDays: 28, count: 2, median: 465, fixedCount: 1, fixedMedian: 30 },
    ])
    expect(windowSensitivity(effects, [7, 14, 28], 'matched', false)[0].fixedCount).toBe(2)
    expect(windowSensitivity([effect('A', 7, 10)], [7, 14, 28], 'matched')[0].fixedMedian).toBeNull()
  })
  it('makes a two-to-three URL change and the low baseline explicit', () => {
    expect(countEvidence({ windowDays: 14, matchedPreMean: 2 / 14, matchedPostMean: 3 / 14 }, 'matched')).toBe('0.14 → 0.21 URLs/day · +0.07/day · 2 baseline URLs · Low baseline (<20 URLs)')
  })
  it('keeps missing curve days as gaps and counts contributing events separately', () => {
    const study = { series: [
      { eventId: 'A', scope: 'affected', topicId: 'climate_change', timing: 'onset', points: [[-1, 10, null], [1, 20, null]] },
      { eventId: 'B', scope: 'affected', topicId: 'climate_change', timing: 'onset', points: [[1, 40, 2]] },
    ] } as EventStudyData
    const points = buildTimeline(study, [effect('A', 7, 10, { matchedPreMean: 10 }), effect('B', 7, 10, { matchedPreMean: 10 })], 'climate_change', 'affected', 'matched', 'onset')
    expect(points.find((point) => point.day === -1)).toEqual({ day: -1, median: 0, events: 1 })
    expect(points.find((point) => point.day === 0)).toEqual({ day: 0, median: null, events: 0 })
    expect(points.find((point) => point.day === 1)).toEqual({ day: 1, median: 200, events: 2 })
    expect(points).toHaveLength(57)
  })
  it('uses period totals for political share, preserves zero-count days, and rejects missing denominators', () => {
    const selection: AnalysisSelection = { ...DEFAULT_SELECTION, windowDays: 2, measure: 'political_share' }
    const points = [[0, 0], [100, 10], [10, 10], [90, 0]].map(([matched, political], index) => ({ date: `2026-01-0${index + 1}`, relativeDay: index - 2, climate_change_matched: matched, climate_change_political: political }))
    const result = summarizeEventComparison(points, '2026-01-03', '2026-01-03', selection)
    expect(result.result).toEqual({ beforeMean: 10, afterMean: 10, difference: 0, percentChange: null })
    expect(result.baselineTotal).toBe(100)
    expect(summarizeEventComparison(points.slice(1), '2026-01-03', '2026-01-03', selection).result).toBeNull()
    const missing = points.map((point, index) => ({ ...point, climate_change_matched: index === 1 ? null : point.climate_change_matched }))
    expect(summarizeEventComparison(missing, '2026-01-03', '2026-01-03', selection).result).toBeNull()
  })
})

describe('drawer agreement with exported study results', () => {
  for (const year of [2025, 2026]) {
    it(`matches every complete ${year} specification for all three measures`, () => {
      const study: EventStudyData = JSON.parse(year === 2025 ? study2025 : study2026)
      const seriesByKey = new Map<string, Map<string, [number | null, number | null]>>()
      for (const series of study.series) {
        const event = study.events.find((event) => event.id === series.eventId)!
        const origin = Date.parse(`${(series.timing === 'onset' ? event.startAt : event.endAt).slice(0, 10)}T00:00:00Z`) + (series.timing === 'onset' ? 0 : 86400000)
        const key = `${series.eventId}:${series.scope}:${series.topicId}`
        const rows = seriesByKey.get(key) ?? new Map()
        for (const [day, matched, political] of series.points) rows.set(new Date(origin + day * 86400000).toISOString().slice(0, 10), [matched, political])
        seriesByKey.set(key, rows)
      }
      for (const effect of study.effects.filter((effect) => effect.complete)) {
        const rows = seriesByKey.get(`${effect.eventId}:${effect.scope}:${effect.topicId}`)!
        for (const measure of ['matched', 'political', 'political_share'] as const) {
          const points: AttentionChartPoint[] = [...rows].map(([date, [matched, political]]) => ({ date, relativeDay: 0, [effect.topicId]: measure === 'matched' ? matched : political, [`${effect.topicId}_matched`]: matched, [`${effect.topicId}_political`]: political }))
          const result = summarizeEventComparison(points, effect.startAt, effect.endAt, { topic: effect.topicId, scope: effect.scope, measure, windowDays: effect.windowDays, timing: effect.timing }).result
          const expected = measure === 'matched' ? effect.matchedPercentChange : measure === 'political' ? effect.politicalPercentChange : effect.politicalShareChange
          const actual = measure === 'political_share' ? result?.difference : result?.percentChange
          if (expected == null) expect(actual ?? null).toBeNull()
          else expect(actual, `${effect.eventId}/${effect.scope}/${measure}/${effect.timing}/${effect.windowDays}`).toBeCloseTo(expected, 8)
        }
      }
    })
  }
  it('keeps other EU and rest-world country panels distinct, including absent supported markets', () => {
    const event = { id: 'test', startAt: '2026-01-10', endAt: '2026-01-10', geographyIds: ['france'] } as Parameters<typeof buildEventChart>[0]
    const rows = ['france', 'germany', 'brazil'].map((geography, index) => ({ geography, date: '2026-01-10', source: 'gdelt_ngrams', topicId: 'climate_change', matchedCount: (index + 1) * 10, politicalCount: index + 1 })) as Parameters<typeof buildEventChart>[1]
    const markets = ['france', 'germany', 'brazil']
    const atOnset = (scope: AnalysisSelection['scope'], panel = markets) => buildEventChart(event, rows, scope, 'all', panel, 'climate_change').points.find((point) => point.relativeDay === 0)?.climate_change
    expect(atOnset('affected')).toBe(10)
    expect(atOnset('other_eu27')).toBe(20)
    expect(atOnset('rest_world')).toBe(30)
    expect(atOnset('rest_world', [...markets, 'canada'])).toBeNull()
  })
})
