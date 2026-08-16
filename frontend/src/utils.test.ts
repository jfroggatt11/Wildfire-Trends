import { describe, expect, it } from 'vitest'
import { dateWithinRange, formatDate, getPoliticalSignals, hasPoliticalSignal, newestFirst, permutationIncreaseTest } from './utils'

describe('formatDate', () => {
  it('formats valid UTC dates', () => {
    expect(formatDate('2025-01-31')).toBe('31 Jan 2025')
  })

  it('does not throw while a keyboard-edited date is empty or incomplete', () => {
    expect(formatDate('')).toBe('Open')
    expect(formatDate(null)).toBe('Open')
    expect(formatDate('not-a-date')).toBe('Open')
  })
})

describe('dateWithinRange', () => {
  it('accepts open start and end boundaries', () => {
    expect(dateWithinRange('2025-01-15', '', '')).toBe(true)
    expect(dateWithinRange('2025-01-15', '', '2025-01-31')).toBe(true)
    expect(dateWithinRange('2025-01-15', '2025-01-01', '')).toBe(true)
  })

  it('keeps the boundaries inclusive', () => {
    expect(dateWithinRange('2025-01-01', '2025-01-01', '2025-01-31')).toBe(true)
    expect(dateWithinRange('2025-02-01', '2025-01-01', '2025-01-31')).toBe(false)
  })

  it('returns no match for reversed boundaries without throwing', () => {
    expect(dateWithinRange('2025-01-15', '2025-02-01', '2025-01-31')).toBe(false)
  })
})

describe('newestFirst', () => {
  it('sorts nullable publication timestamps using the canonical date fallback', () => {
    const rows = [
      { publishedAt: null, date: '2025-01-02' },
      { publishedAt: '2025-01-03T09:00:00Z', date: '2025-01-03' },
      { publishedAt: null, date: '2025-01-01' },
    ]
    expect(rows.sort(newestFirst).map((row) => row.date)).toEqual(['2025-01-03', '2025-01-02', '2025-01-01'])
  })
})

describe('political article signals', () => {
  it('identifies and names every configured political framing signal', () => {
    const article = {
      politicalActor: true,
      governmentAction: false,
      partyPolitics: true,
      officialSource: false,
    }
    expect(hasPoliticalSignal(article)).toBe(true)
    expect(getPoliticalSignals(article)).toEqual(['Political actor', 'Party politics'])
  })

  it('does not classify an article without a political signal', () => {
    const article = {
      politicalActor: false,
      governmentAction: false,
      partyPolitics: false,
      officialSource: false,
    }
    expect(hasPoliticalSignal(article)).toBe(false)
    expect(getPoliticalSignals(article)).toEqual([])
  })
})

describe('permutationIncreaseTest', () => {
  it('finds a clear directional increase with an exact short-window test', () => {
    const result = permutationIncreaseTest([0, 1, 0, 1, 0, 1, 0], [8, 9, 8, 10, 9, 8, 10])
    expect(result?.method).toBe('exact')
    expect(result?.difference).toBeGreaterThan(8)
    expect(result?.pValue).toBeLessThan(0.05)
  })

  it('does not label unchanged observations as an increase', () => {
    const result = permutationIncreaseTest([2, 3, 2, 3], [2, 3, 2, 3])
    expect(result?.difference).toBe(0)
    expect(result?.pValue).toBeGreaterThanOrEqual(0.5)
  })

  it('requires at least two observations on each side', () => {
    expect(permutationIncreaseTest([1], [2, 3])).toBeNull()
  })
})
