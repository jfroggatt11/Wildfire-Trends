const DAY_MS = 86_400_000

export const toUtcDay = (value: string) => Math.floor(new Date(`${value}T00:00:00Z`).getTime() / DAY_MS)

export const fromUtcDay = (value: number) => new Date(value * DAY_MS).toISOString().slice(0, 10)

export function monthTicks(start: string, end: string) {
  const startDate = new Date(`${start}T00:00:00Z`)
  const endDate = new Date(`${end}T00:00:00Z`)
  const spanDays = toUtcDay(end) - toUtcDay(start) + 1
  const stepMonths = spanDays > 400 ? 2 : 1
  const cursor = new Date(Date.UTC(startDate.getUTCFullYear(), startDate.getUTCMonth(), 1))
  if (cursor < startDate) cursor.setUTCMonth(cursor.getUTCMonth() + 1)
  const ticks: string[] = []
  while (cursor <= endDate) {
    ticks.push(cursor.toISOString().slice(0, 10))
    cursor.setUTCMonth(cursor.getUTCMonth() + stepMonths)
  }
  return ticks
}

export function formatAxisDate(value: string, multiYear: boolean) {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    ...(multiYear ? { year: '2-digit' as const } : {}),
    timeZone: 'UTC',
  }).format(new Date(`${value}T00:00:00Z`))
}

export function inclusiveDays(start: string, end: string) {
  return Math.max(0, toUtcDay(end) - toUtcDay(start) + 1)
}
