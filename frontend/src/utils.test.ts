import { describe, expect, it } from 'vitest'
import { dateWithinRange, formatDate, getPoliticalSignals, hasPoliticalSignal, newestFirst } from './utils'

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
