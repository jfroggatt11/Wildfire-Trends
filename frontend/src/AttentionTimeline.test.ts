import { describe, expect, it } from 'vitest'
import { rollingAverageValues, rollingTotalValues, wildfireAreaHectares, wildfireSizeBand } from './AttentionTimeline'

describe('rollingAverageValues', () => {
  it('keeps daily values unchanged', () => {
    expect(rollingAverageValues([2, 4, null, 8], 1)).toEqual([2, 4, null, 8])
  })

  it('calculates a trailing average only after a complete window', () => {
    expect(rollingAverageValues([1, 2, 3, 4, 5, 6, 7, 8], 7)).toEqual([
      null, null, null, null, null, null, 4, 5,
    ])
  })

  it('does not smooth across missing provider dates', () => {
    expect(rollingAverageValues([1, 2, 3, null, 5, 6, 7], 7)).toEqual([
      null, null, null, null, null, null, null,
    ])
    expect(rollingAverageValues([null, 2, 3, 4, 5, 6, 7, 8], 7).at(-1)).toBe(5)
  })
})

describe('wildfireSizeBand', () => {
  it('assigns explicit burned-area bands at their boundaries', () => {
    expect(wildfireSizeBand({ hazardType: 'wildfire', severity: 4_999, severityUnit: 'ha' })).toBe('under_5k')
    expect(wildfireSizeBand({ hazardType: 'wildfire', severity: 5_000, severityUnit: 'ha' })).toBe('5k_10k')
    expect(wildfireSizeBand({ hazardType: 'wildfire', severity: 10_000, severityUnit: 'ha' })).toBe('10k_50k')
    expect(wildfireSizeBand({ hazardType: 'wildfire', severity: 50_000, severityUnit: 'ha' })).toBe('50k_plus')
  })

  it('does not invent a comparable size for floods or missing units', () => {
    expect(wildfireSizeBand({ hazardType: 'flood', severity: 50_000, severityUnit: 'ha' })).toBeNull()
    expect(wildfireSizeBand({ hazardType: 'wildfire', severity: 50_000, severityUnit: null })).toBeNull()
  })

  it('recognises case-insensitive hectare units and rejects invalid totals', () => {
    expect(wildfireAreaHectares({ hazardType: 'wildfire', severity: 12_500, severityUnit: 'HA' })).toBe(12_500)
    expect(wildfireAreaHectares({ hazardType: 'wildfire', severity: -1, severityUnit: 'ha' })).toBeNull()
    expect(wildfireAreaHectares({ hazardType: 'flood', severity: 12_500, severityUnit: 'ha' })).toBeNull()
  })
})

describe('rollingTotalValues', () => {
  it('keeps daily event-area totals unchanged', () => {
    expect(rollingTotalValues([0, 5_000, 2_000], 1)).toEqual([0, 5_000, 2_000])
  })

  it('sums whole-event hectares over the selected trailing window', () => {
    expect(rollingTotalValues([1_000, 0, 2_000, 3_000, 0, 0, 1_000], 7)).toEqual([
      null, null, null, null, null, null, 7_000,
    ])
  })
})
