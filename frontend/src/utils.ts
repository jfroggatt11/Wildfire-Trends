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

export type IncreaseTestResult = {
  beforeMean: number
  afterMean: number
  difference: number
  percentChange: number | null
  pValue: number
  permutations: number
  method: 'exact' | 'monte_carlo'
}

const average = (values: number[]) => values.reduce((total, value) => total + value, 0) / values.length

const combinationCount = (total: number, selected: number) => {
  const smaller = Math.min(selected, total - selected)
  let result = 1
  for (let index = 1; index <= smaller; index += 1) result = (result * (total - smaller + index)) / index
  return Math.round(result)
}

const seededRandom = (seed: number) => () => {
  seed |= 0
  seed = (seed + 0x6d2b79f5) | 0
  let value = Math.imul(seed ^ (seed >>> 15), 1 | seed)
  value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value
  return ((value ^ (value >>> 14)) >>> 0) / 4294967296
}

export function permutationIncreaseTest(before: number[], after: number[], iterations = 10_000): IncreaseTestResult | null {
  if (before.length < 2 || after.length < 2) return null
  const beforeMean = average(before)
  const afterMean = average(after)
  const difference = afterMean - beforeMean
  const pooled = [...before, ...after]
  const beforeSize = before.length
  const observedTolerance = difference - 1e-12
  const possibleCombinations = combinationCount(pooled.length, beforeSize)
  let extreme = 0
  let permutations = 0
  let method: IncreaseTestResult['method'] = 'exact'

  if (possibleCombinations <= 50_000) {
    const totalSum = pooled.reduce((total, value) => total + value, 0)
    const visit = (start: number, remaining: number, selectedSum: number) => {
      if (remaining === 0) {
        const permutedBefore = selectedSum / beforeSize
        const permutedAfter = (totalSum - selectedSum) / after.length
        if (permutedAfter - permutedBefore >= observedTolerance) extreme += 1
        permutations += 1
        return
      }
      for (let index = start; index <= pooled.length - remaining; index += 1) {
        visit(index + 1, remaining - 1, selectedSum + pooled[index])
      }
    }
    visit(0, beforeSize, 0)
  } else {
    method = 'monte_carlo'
    const seed = pooled.reduce((value, item, index) => (value * 31 + Math.round(item * 100) + index) | 0, 17)
    const random = seededRandom(seed)
    for (let iteration = 0; iteration < iterations; iteration += 1) {
      const shuffled = [...pooled]
      for (let index = shuffled.length - 1; index > 0; index -= 1) {
        const swapIndex = Math.floor(random() * (index + 1))
        const current = shuffled[index]
        shuffled[index] = shuffled[swapIndex]
        shuffled[swapIndex] = current
      }
      const permutedBefore = average(shuffled.slice(0, beforeSize))
      const permutedAfter = average(shuffled.slice(beforeSize))
      if (permutedAfter - permutedBefore >= observedTolerance) extreme += 1
    }
    permutations = iterations
  }

  return {
    beforeMean,
    afterMean,
    difference,
    percentChange: beforeMean === 0 ? null : (difference / beforeMean) * 100,
    pValue: method === 'exact' ? extreme / permutations : (extreme + 1) / (permutations + 1),
    permutations,
    method,
  }
}
