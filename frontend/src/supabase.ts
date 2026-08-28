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

export type EventEffectObservation = {
  eventId: string
  hazardType: 'wildfire' | 'flood'
  alertLevel: 'Green' | 'Orange' | 'Red'
  startAt: string
  endAt: string
  geographyIds: string[]
  scope: 'affected' | 'other_eu27' | 'rest_world' | 'global'
  topicId: 'climate_change' | 'electric_vehicles'
  windowDays: number
  timing: 'onset' | 'persistence'
  complete: boolean
  missingDays: number
  overlap: boolean
  matchedPreMean: number | null
  matchedPostMean: number | null
  matchedChange: number | null
  matchedPercentChange: number | null
  politicalPreMean: number | null
  politicalPostMean: number | null
  politicalChange: number | null
  politicalPercentChange: number | null
  politicalSharePre: number | null
  politicalSharePost: number | null
  politicalShareChange: number | null
}

export type EventActivityObservation = {
  date: string
  geography: string
  hazardType: 'wildfire' | 'flood'
  alertLevel: 'Green' | 'Orange' | 'Red'
  eventsStarted: number
  eventsActive: number
  eventsEnded: number
}

export type RegionAttentionObservation = {
  date: string
  regionId: 'global' | 'eu27'
  topicId: 'climate_change' | 'electric_vehicles'
  matchedCount: number
  politicalCount: number
  politicalActorCount: number
  governmentActionCount: number
  partyPoliticsCount: number
  officialSourceCount: number
  politicalShare: number | null
}

export type EventEffectQuery = {
  start: string
  end: string
  scope: EventEffectObservation['scope']
  windowDays: number
  timing: EventEffectObservation['timing']
  alerts?: EventEffectObservation['alertLevel'][]
  hazard?: EventEffectObservation['hazardType']
}

export function buildEventEffectsUrl(
  baseUrl: string,
  query: EventEffectQuery,
  offset = 0,
  limit = 1000,
) {
  const select = [
    'event_id', 'hazard_type', 'alert_level', 'start_at', 'end_at', 'geography_ids',
    'scope', 'topic_id', 'window_days', 'timing', 'complete', 'missing_days', 'overlap',
    'matched_pre_mean', 'matched_post_mean', 'matched_change', 'matched_percent_change',
    'political_pre_mean', 'political_post_mean', 'political_change',
    'political_percent_change', 'political_share_pre', 'political_share_post',
    'political_share_change',
  ].join(',')
  const params = new URLSearchParams({
    select,
    scope: `eq.${query.scope}`,
    window_days: `eq.${query.windowDays}`,
    timing: `eq.${query.timing}`,
    start_at: `gte.${query.start}`,
    order: 'event_id.asc,topic_id.asc',
    offset: String(offset),
    limit: String(limit),
  })
  params.append('start_at', `lte.${query.end}`)
  if (query.alerts?.length) params.set('alert_level', `in.(${query.alerts.join(',')})`)
  if (query.hazard) params.set('hazard_type', `eq.${query.hazard}`)
  return `${baseUrl.replace(/\/$/, '')}/rest/v1/event_effects?${params}`
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

export function isKnownAttentionOutage(value: string) {
  return value >= '2025-06-14' && value <= '2025-07-01'
}

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

async function fetchPagedRows(urlForPage: (offset: number, limit: number) => string) {
  const config = runtimeConfig()
  if (!config) throw new Error('Supabase frontend access is not enabled')
  const pageSize = 1000
  const pagesPerWave = 4
  const first = await fetchJsonWithRetry(urlForPage(0, pageSize), config, true)
  const result: Record<string, unknown>[] = [...first.rows]
  if (first.rows.length < pageSize) return result
  if (first.total != null) {
    const offsets = Array.from(
      { length: Math.max(0, Math.ceil(first.total / pageSize) - 1) },
      (_, index) => (index + 1) * pageSize,
    )
    for (let index = 0; index < offsets.length; index += pagesPerWave) {
      const pages = await Promise.all(offsets.slice(index, index + pagesPerWave).map((offset) =>
        fetchJsonWithRetry(urlForPage(offset, pageSize), config),
      ))
      for (const page of pages) result.push(...page.rows)
    }
    return result
  }
  for (let offset = pageSize; ; offset += pageSize) {
    const page = await fetchJsonWithRetry(urlForPage(offset, pageSize), config)
    result.push(...page.rows)
    if (page.rows.length < pageSize) return result
  }
}

async function fetchJsonWithRetry(url: string, config: SupabaseConfig, countExact = false) {
  let lastError: Error | null = null
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 12_000)
    let response: Response
    try {
      response = await fetch(url, {
        headers: { ...requestHeaders(config), ...(countExact ? { Prefer: 'count=exact' } : {}) },
        signal: controller.signal,
      })
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))
      window.clearTimeout(timeout)
      if (attempt < 2) {
        await new Promise((resolve) => window.setTimeout(resolve, 300 * 2 ** attempt))
        continue
      }
      throw lastError
    }
    window.clearTimeout(timeout)
    if (response.ok) {
      const range = response.headers.get('content-range')
      const totalText = range?.split('/')[1]
      return {
        rows: await response.json() as Record<string, unknown>[],
        total: totalText && totalText !== '*' ? Number(totalText) : null,
      }
    }
    const detail = await response.text()
    lastError = new Error(`Supabase request failed (${response.status}): ${detail.slice(0, 240)}`)
    if (response.status !== 429 && response.status < 500) throw lastError
    if (attempt < 2) await new Promise((resolve) => window.setTimeout(resolve, 300 * 2 ** attempt))
  }
  throw lastError ?? new Error('Supabase request failed')
}

export async function fetchAttentionWindow(query: WindowQuery): Promise<AttentionObservation[]> {
  const config = runtimeConfig()
  if (!config) throw new Error('Supabase frontend access is not enabled')
  const rows = await fetchPagedRows((offset, limit) =>
    buildAttentionUrl(config.url, query, offset, limit))
  return rows.map(mapAttentionRow).filter((row) => !isKnownAttentionOutage(row.date))
}

export async function fetchEventEffects(query: EventEffectQuery): Promise<EventEffectObservation[]> {
  const config = runtimeConfig()
  if (!config) throw new Error('Supabase frontend access is not enabled')
  const rows = await fetchPagedRows((offset, limit) =>
    buildEventEffectsUrl(config.url, query, offset, limit))
  return rows.map(mapEventEffect)
}

export async function fetchEventActivity(query: {
  geography?: string
  geographies?: string[]
  start: string
  end: string
  alerts?: EventActivityObservation['alertLevel'][]
  hazard?: EventActivityObservation['hazardType']
}): Promise<EventActivityObservation[]> {
  const config = runtimeConfig()
  if (!config) throw new Error('Supabase frontend access is not enabled')
  const rows = await fetchPagedRows((offset, limit) => {
    const params = new URLSearchParams({
      select: 'activity_date,geography,hazard_type,alert_level,events_started,events_active,events_ended',
      activity_date: `gte.${query.start}`,
      order: 'activity_date.asc',
      offset: String(offset),
      limit: String(limit),
    })
    if (query.geographies?.length) params.set('geography', `in.(${query.geographies.join(',')})`)
    else if (query.geography) params.set('geography', `eq.${query.geography}`)
    params.append('activity_date', `lte.${query.end}`)
    if (query.alerts?.length) params.set('alert_level', `in.(${query.alerts.join(',')})`)
    if (query.hazard) params.set('hazard_type', `eq.${query.hazard}`)
    return `${config.url}/rest/v1/daily_event_activity?${params}`
  })
  return rows.map(mapEventActivityRow)
}

export function mapEventActivityRow(row: Record<string, unknown>): EventActivityObservation {
  return {
    date: String(row.activity_date),
    geography: String(row.geography),
    hazardType: String(row.hazard_type) as EventActivityObservation['hazardType'],
    alertLevel: String(row.alert_level) as EventActivityObservation['alertLevel'],
    eventsStarted: Number(row.events_started),
    eventsActive: Number(row.events_active),
    eventsEnded: Number(row.events_ended),
  }
}

export async function fetchRegionAttention(
  regionId: RegionAttentionObservation['regionId'], start: string, end: string,
): Promise<RegionAttentionObservation[]> {
  const config = runtimeConfig()
  if (!config) throw new Error('Supabase frontend access is not enabled')
  const rows = await fetchPagedRows((offset, limit) => {
    const params = new URLSearchParams({
      select: 'observation_date,region_id,topic_id,matched_count,political_count,political_actor_count,government_action_count,party_politics_count,official_source_count,political_share',
      region_id: `eq.${regionId}`,
      observation_date: `gte.${start}`,
      order: 'observation_date.asc,topic_id.asc',
      offset: String(offset),
      limit: String(limit),
    })
    params.append('observation_date', `lte.${end}`)
    return `${config.url}/rest/v1/daily_attention_regions?${params}`
  })
  return rows.map(mapRegionAttentionRow).filter((row) => !isKnownAttentionOutage(row.date))
}

export function mapRegionAttentionRow(row: Record<string, unknown>): RegionAttentionObservation {
  return {
    date: String(row.observation_date),
    regionId: String(row.region_id) as RegionAttentionObservation['regionId'],
    topicId: String(row.topic_id) as RegionAttentionObservation['topicId'],
    matchedCount: Number(row.matched_count),
    politicalCount: Number(row.political_count),
    politicalActorCount: Number(row.political_actor_count),
    governmentActionCount: Number(row.government_action_count),
    partyPoliticsCount: Number(row.party_politics_count),
    officialSourceCount: Number(row.official_source_count),
    politicalShare: numberOrNull(row.political_share),
  }
}

export function mapEventEffect(row: Record<string, unknown>): EventEffectObservation {
  return {
    eventId: String(row.event_id),
    hazardType: String(row.hazard_type) as EventEffectObservation['hazardType'],
    alertLevel: String(row.alert_level) as EventEffectObservation['alertLevel'],
    startAt: String(row.start_at),
    endAt: String(row.end_at),
    geographyIds: Array.isArray(row.geography_ids) ? row.geography_ids.map(String) : [],
    scope: String(row.scope) as EventEffectObservation['scope'],
    topicId: String(row.topic_id) as EventEffectObservation['topicId'],
    windowDays: Number(row.window_days),
    timing: String(row.timing) as EventEffectObservation['timing'],
    complete: Boolean(row.complete),
    missingDays: Number(row.missing_days),
    overlap: Boolean(row.overlap),
    matchedPreMean: numberOrNull(row.matched_pre_mean),
    matchedPostMean: numberOrNull(row.matched_post_mean),
    matchedChange: numberOrNull(row.matched_change),
    matchedPercentChange: numberOrNull(row.matched_percent_change),
    politicalPreMean: numberOrNull(row.political_pre_mean),
    politicalPostMean: numberOrNull(row.political_post_mean),
    politicalChange: numberOrNull(row.political_change),
    politicalPercentChange: numberOrNull(row.political_percent_change),
    politicalSharePre: numberOrNull(row.political_share_pre),
    politicalSharePost: numberOrNull(row.political_share_post),
    politicalShareChange: numberOrNull(row.political_share_change),
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
