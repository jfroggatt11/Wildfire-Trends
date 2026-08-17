import deployedConfig from './supabase-config.json'

export type AttentionObservation = {
  date: string
  source: string
  topicId: string
  geography: string
  matchedCount: number | null
  attentionShare: number | null
  attentionIndex: number | null
  politicalCount: number | null
  politicalActorCount: number | null
  governmentActionCount: number | null
  partyPoliticsCount: number | null
  officialSourceCount: number | null
}

type SupabaseConfig = { url: string; publicKey: string }

export type WindowQuery = {
  start: string
  end: string
  geographies?: string[]
  excludeGeographies?: string[]
  topics?: string[]
}

const ATTENTION_SELECT = [
  'observation_date',
  'source',
  'topic_id',
  'geography',
  'matched_count',
  'country_attention_share',
  'attention_index',
  'political_count',
  'political_actor_count',
  'government_action_count',
  'party_politics_count',
  'official_source_count',
].join(',')

function runtimeConfig(): SupabaseConfig | null {
  const enabled = import.meta.env.VITE_USE_SUPABASE === 'true' || deployedConfig.enabled
  if (!enabled) return null
  const url = (import.meta.env.VITE_SUPABASE_URL || deployedConfig.url)?.replace(/\/$/, '')
  const publicKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || deployedConfig.publicKey
  return url && publicKey ? { url, publicKey } : null
}

export function isSupabaseEnabled() {
  return runtimeConfig() !== null
}

function appendWindowFilters(params: URLSearchParams, query: WindowQuery) {
  params.set('observation_date', `gte.${query.start}`)
  params.append('observation_date', `lte.${query.end}`)
  if (query.geographies?.length) params.set('geography', `in.(${query.geographies.join(',')})`)
  if (query.excludeGeographies?.length) params.set('geography', `not.in.(${query.excludeGeographies.join(',')})`)
  if (query.topics?.length) params.set('topic_id', `in.(${query.topics.join(',')})`)
}

export function buildAttentionUrl(baseUrl: string, query: WindowQuery, offset = 0, limit = 1000) {
  const params = new URLSearchParams({
    select: ATTENTION_SELECT,
    order: 'observation_date.asc,topic_id.asc,geography.asc',
    offset: String(offset),
    limit: String(limit),
  })
  appendWindowFilters(params, query)
  return `${baseUrl.replace(/\/$/, '')}/rest/v1/daily_attention?${params}`
}

function requestHeaders(config: SupabaseConfig) {
  return {
    apikey: config.publicKey,
    Authorization: `Bearer ${config.publicKey}`,
  }
}

async function responseJson(response: Response) {
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Supabase request failed (${response.status}): ${detail.slice(0, 240)}`)
  }
  return response.json()
}

export async function fetchAttentionWindow(query: WindowQuery): Promise<AttentionObservation[]> {
  const config = runtimeConfig()
  if (!config) throw new Error('Supabase frontend access is not enabled')
  const pageSize = 1000
  const result: AttentionObservation[] = []
  for (let offset = 0; ; offset += pageSize) {
    const response = await fetch(buildAttentionUrl(config.url, query, offset, pageSize), {
      headers: requestHeaders(config),
    })
    const rows = await responseJson(response) as Record<string, unknown>[]
    result.push(...rows.map(mapAttentionRow))
    if (rows.length < pageSize) return result
  }
}

export function mapAttentionRow(row: Record<string, unknown>): AttentionObservation {
  return {
    date: String(row.observation_date),
    source: String(row.source),
    topicId: String(row.topic_id),
    geography: String(row.geography),
    matchedCount: numberOrNull(row.matched_count),
    attentionShare: numberOrNull(row.country_attention_share),
    attentionIndex: numberOrNull(row.attention_index),
    politicalCount: numberOrNull(row.political_count),
    politicalActorCount: numberOrNull(row.political_actor_count),
    governmentActionCount: numberOrNull(row.government_action_count),
    partyPoliticsCount: numberOrNull(row.party_politics_count),
    officialSourceCount: numberOrNull(row.official_source_count),
  }
}

function numberOrNull(value: unknown) {
  return value == null ? null : Number(value)
}
