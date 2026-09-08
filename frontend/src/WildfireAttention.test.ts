import { describe, expect, it } from 'vitest'
import {
  addSeverityBenchmark,
  buildWildfireAttentionRows,
  pairWildfireTopicRows,
  reportedWildfireHectares,
} from './WildfireAttention'
import type { WildfireAttentionEffect, WildfireAttentionEvent, WildfireAttentionRow } from './WildfireAttention'

function event(overrides: Partial<WildfireAttentionEvent> = {}): WildfireAttentionEvent {
  return {
    id: 'fire-1',
    name: 'Test fire',
    hazardType: 'wildfire',
    alertLevel: 'Orange',
    startAt: '2025-07-01',
    geographyIds: ['italy'],
    severity: 10_000,
    severityUnit: 'ha',
    ...overrides,
  }
}

function effect(overrides: Partial<WildfireAttentionEffect> = {}): WildfireAttentionEffect {
  return {
    eventId: 'fire-1',
    hazardType: 'wildfire',
    scope: 'affected',
    topicId: 'climate_change',
    windowDays: 14,
    timing: 'onset',
    complete: true,
    overlap: false,
    matchedChange: 12,
    matchedPercentChange: 60,
    politicalChange: 3,
    politicalPercentChange: 30,
    politicalShareChange: 2,
    ...overrides,
  }
}

describe('buildWildfireAttentionRows', () => {
  it('builds the selected wildfire specification and excludes overlaps', () => {
    const events = new Map<string, WildfireAttentionEvent>([['fire-1', event()]])
    const effects = [effect(), effect({ eventId: 'fire-2', overlap: true })]
    const result = buildWildfireAttentionRows(effects, events, {
      scope: 'affected',
      topic: 'climate_change',
      windowDays: 14,
      measure: 'matched',
      scale: 'absolute',
      excludeOverlaps: true,
    })
    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({ response: 12, areaHectares: 10_000, logArea: 4 })
  })

  it('supports relative and political-share responses', () => {
    const events = new Map<string, WildfireAttentionEvent>([['fire-1', event()]])
    const base = { scope: 'affected' as const, topic: 'climate_change' as const, windowDays: 14, excludeOverlaps: true }
    expect(buildWildfireAttentionRows([effect()], events, { ...base, measure: 'matched', scale: 'relative' }).rows[0].response).toBe(60)
    expect(buildWildfireAttentionRows([effect()], events, { ...base, measure: 'political_share', scale: 'absolute' }).rows[0].response).toBe(2)
  })
})

describe('severity benchmark', () => {
  it('calculates a transparent log-area relationship and residuals', () => {
    const rows = [1, 2, 3].map((logArea): WildfireAttentionRow => ({
      event: event({ id: `fire-${logArea}`, severity: 10 ** logArea }),
      effect: effect({ eventId: `fire-${logArea}` }),
      areaHectares: 10 ** logArea,
      logArea,
      response: 2 * logArea + 1,
      expectedFromSeverity: null,
      excessFromSeverity: null,
    }))
    const result = addSeverityBenchmark(rows)
    expect(result.correlation).toBeCloseTo(1)
    expect(result.rows.map((row) => row.expectedFromSeverity)).toEqual([3, 5, 7])
    expect(result.rows.map((row) => row.excessFromSeverity)).toEqual([0, 0, 0])
  })

  it('does not invent burned area from missing or incompatible severity', () => {
    expect(reportedWildfireHectares(event({ severityUnit: 'people' }))).toBeNull()
    expect(reportedWildfireHectares(event({ severity: -1 }))).toBeNull()
    expect(reportedWildfireHectares(event({ hazardType: 'flood' }))).toBeNull()
  })
})

describe('paired topic rows', () => {
  it('joins climate and EV responses from the same wildfire', () => {
    const shared = {
      event: event(),
      areaHectares: 10_000,
      logArea: 4,
      expectedFromSeverity: null,
      excessFromSeverity: null,
    }
    const rows: WildfireAttentionRow[] = [
      { ...shared, effect: effect({ topicId: 'climate_change' }), response: 12 },
      { ...shared, effect: effect({ topicId: 'electric_vehicles' }), response: 4 },
      { ...shared, event: event({ id: 'unpaired' }), effect: effect({ eventId: 'unpaired' }), response: 7 },
    ]
    expect(pairWildfireTopicRows(rows)).toEqual([{
      eventId: 'fire-1',
      logArea: 4,
      climateChange: 12,
      electricVehicles: 4,
    }])
  })
})
