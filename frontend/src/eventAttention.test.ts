import { describe, expect, it } from 'vitest'
import { dailyEventPoints, eventDateRange, sumCompleteMarkets } from './eventAttention'

const row = (date: string, geography: string, matchedCount: number | null) =>
  ({ date, geography, topicId: 'climate_change', matchedCount, politicalCount: matchedCount })

describe('complete daily event evidence', () => {
  it('keeps missing dates on the time axis and preserves observed zero', () => {
    const points = dailyEventPoints([row('2025-06-13', 'italy', 0), row('2025-07-02', 'italy', 4)],
      ['italy'], ['climate_change'], '2025-06-13', '2025-07-02', '2025-06-13', 'matchedCount')
    expect(points).toHaveLength(20)
    expect(points[0].climate_change).toBe(0)
    expect(points.slice(1, -1).every((point) => point.climate_change === null)).toBe(true)
    expect(points.at(-1)?.relativeDay).toBe(19)
  })

  it('does not sum partially observed, unsupported or duplicate markets', () => {
    const rows = [row('2025-01-01', 'italy', 3), row('2025-01-01', 'france', null)]
    expect(sumCompleteMarkets(rows, ['italy', 'france'], 'matchedCount')).toBeNull()
    expect(sumCompleteMarkets(rows, ['italy', 'missing'], 'matchedCount')).toBeNull()
    expect(sumCompleteMarkets([rows[0], rows[0]], ['italy'], 'matchedCount')).toBeNull()
    expect(sumCompleteMarkets([rows[0], row('2025-01-01', 'france', 0)], ['italy', 'france'], 'matchedCount')).toBe(3)
  })
})

it('includes the full first pre-event date even when GDACS timestamps are not midnight', () => {
  const range = eventDateRange('2025-02-01T01:00:00Z', '2025-02-02T23:00:00Z')
  expect(range.start.toISOString()).toBe('2025-01-04T00:00:00.000Z')
  expect(range.end.toISOString()).toBe('2025-03-02T00:00:00.000Z')
})
