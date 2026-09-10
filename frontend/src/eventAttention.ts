import type { AttentionChartPoint } from './AttentionChart'

export type DailyMarketCount = {
  date: string
  topicId: string
  geography: string
  matchedCount: number | null
  politicalCount: number | null
}

/** Missing markets and null observations are never inferred to be zero. */
export function sumCompleteMarkets(
  rows: DailyMarketCount[],
  markets: string[],
  field: 'matchedCount' | 'politicalCount',
): number | null {
  if (!markets.length) return null
  let sum = 0
  for (const market of markets) {
    const matches = rows.filter((row) => row.geography === market)
    if (matches.length !== 1) return null
    const value = matches[0][field]
    if (value == null || !Number.isFinite(value)) return null
    sum += value
  }
  return sum
}

export function dailyEventPoints(
  rows: DailyMarketCount[], markets: string[], topics: string[],
  start: string, end: string, origin: string, field: 'matchedCount' | 'politicalCount',
): AttentionChartPoint[] {
  const groups = new Map<string, DailyMarketCount[]>()
  for (const row of rows) {
    const key = `${row.date}:${row.topicId}`
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  const points: AttentionChartPoint[] = []
  const originTime = Date.parse(`${origin.slice(0, 10)}T00:00:00Z`)
  for (let time = Date.parse(`${start}T00:00:00Z`); time <= Date.parse(`${end}T00:00:00Z`); time += 86400000) {
    const date = new Date(time).toISOString().slice(0, 10)
    const point: AttentionChartPoint = { date, relativeDay: (time - originTime) / 86400000 }
    for (const topic of topics) {
      point[topic] = sumCompleteMarkets(groups.get(`${date}:${topic}`) ?? [], markets, field)
    }
    points.push(point)
  }
  return points
}

/** Analysis operates on UTC calendar dates, not the provider's clock time. */
export function eventDateRange(startAt: string, endAt: string, days = 28) {
  return {
    start: new Date(Date.parse(`${startAt.slice(0, 10)}T00:00:00Z`) - days * 86400000),
    end: new Date(Date.parse(`${endAt.slice(0, 10)}T00:00:00Z`) + days * 86400000),
  }
}
