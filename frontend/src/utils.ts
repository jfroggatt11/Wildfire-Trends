export function formatDate(value: string | null | undefined, fallback = 'Open') {
  if (!value) return fallback
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return fallback
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(parsed)
}

export function dateWithinRange(value: string, start: string, end: string) {
  if (start && value < start) return false
  if (end && value > end) return false
  return true
}

export function newestFirst(
  left: { publishedAt: string | null; date: string },
  right: { publishedAt: string | null; date: string },
) {
  const leftDate = left.publishedAt || left.date || ''
  const rightDate = right.publishedAt || right.date || ''
  return rightDate.localeCompare(leftDate)
}

export type PoliticalSignalInput = {
  politicalActor: boolean
  governmentAction: boolean
  partyPolitics: boolean
  officialSource: boolean
}

const POLITICAL_SIGNALS = [
  ['politicalActor', 'Political actor'],
  ['governmentAction', 'Government action'],
  ['partyPolitics', 'Party politics'],
  ['officialSource', 'Official source'],
] as const

export function getPoliticalSignals(article: PoliticalSignalInput) {
  return POLITICAL_SIGNALS.filter(([field]) => article[field]).map(([, label]) => label)
}

export function hasPoliticalSignal(article: PoliticalSignalInput) {
  return getPoliticalSignals(article).length > 0
}
