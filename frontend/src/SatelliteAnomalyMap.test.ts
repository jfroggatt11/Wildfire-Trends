import { describe, expect, it } from 'vitest'
import { anomalyColor } from './SatelliteAnomalyMap'

describe('anomalyColor', () => {
  it('uses distinct brown, neutral and green map colours', () => {
    expect(anomalyColor(-0.1)).toContain('hsl(28')
    expect(anomalyColor(null)).toBe('#e2e7e3')
    expect(anomalyColor(0)).toBe('#e2e7e3')
    expect(anomalyColor(0.1)).toContain('hsl(145')
  })
})
