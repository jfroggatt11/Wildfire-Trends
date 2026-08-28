import { describe, expect, it } from 'vitest'
import { rollingAverageValues } from './AttentionTimeline'

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
