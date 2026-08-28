import { describe, expect, it } from 'vitest'
import { formatAxisDate, fromUtcDay, inclusiveDays, monthTicks, toUtcDay } from './analysisTime'

describe('analysis time helpers', () => {
  it('round-trips UTC day slider values', () => {
    expect(fromUtcDay(toUtcDay('2025-06-14'))).toBe('2025-06-14')
  })

  it('creates one unambiguous tick per month for a single year', () => {
    expect(monthTicks('2025-01-01', '2025-06-30')).toEqual([
      '2025-01-01', '2025-02-01', '2025-03-01', '2025-04-01', '2025-05-01', '2025-06-01',
    ])
    expect(formatAxisDate('2025-02-01', false)).toBe('1 Feb')
  })

  it('uses alternate months and adds years for a long multi-year range', () => {
    expect(monthTicks('2025-01-01', '2026-06-30')).toEqual([
      '2025-01-01', '2025-03-01', '2025-05-01', '2025-07-01', '2025-09-01',
      '2025-11-01', '2026-01-01', '2026-03-01', '2026-05-01',
    ])
    expect(formatAxisDate('2026-01-01', true)).toBe('1 Jan 26')
    expect(inclusiveDays('2025-01-01', '2025-01-31')).toBe(31)
  })
})
