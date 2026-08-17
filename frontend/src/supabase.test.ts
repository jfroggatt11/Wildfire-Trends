import { describe, expect, it } from 'vitest'
import { buildAttentionUrl, mapAttentionRow } from './supabase'

describe('Supabase REST queries', () => {
  it('builds a bounded attention query for selected media markets', () => {
    const url = new URL(buildAttentionUrl('https://example.supabase.co/', {
      start: '2025-02-01',
      end: '2025-02-28',
      geographies: ['GBR', 'FRA'],
      topics: ['climate_change', 'electric_vehicles'],
    }, 1000, 500))

    expect(url.pathname).toBe('/rest/v1/daily_attention')
    expect(url.searchParams.getAll('observation_date')).toEqual(['gte.2025-02-01', 'lte.2025-02-28'])
    expect(url.searchParams.get('geography')).toBe('in.(GBR,FRA)')
    expect(url.searchParams.get('topic_id')).toBe('in.(climate_change,electric_vehicles)')
    expect(url.searchParams.get('offset')).toBe('1000')
    expect(url.searchParams.get('limit')).toBe('500')
  })
})

describe('Supabase response mapping', () => {
  it('maps snake-case attention rows to the atlas model', () => {
    expect(mapAttentionRow({
      observation_date: '2025-01-01', source: 'gdelt_ngrams', topic_id: 'climate_change', geography: 'GBR',
      matched_count: 12, country_attention_share: 0.4, attention_index: null, political_count: 3,
      political_actor_count: 1, government_action_count: 2, party_politics_count: 0, official_source_count: 1,
    })).toMatchObject({ date: '2025-01-01', topicId: 'climate_change', matchedCount: 12, politicalCount: 3 })
  })
})
