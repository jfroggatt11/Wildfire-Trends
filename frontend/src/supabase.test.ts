import { describe, expect, it } from 'vitest'
import {
  buildAttentionUrl,
  buildEventEffectsUrl,
  isKnownAttentionOutage,
  mapAttentionRow,
  mapEventActivityRow,
  mapEventEffect,
  mapRegionAttentionRow,
} from './supabase'

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

  it('classifies the confirmed GDELT outage as an inclusive missing interval', () => {
    expect(isKnownAttentionOutage('2025-06-13')).toBe(false)
    expect(isKnownAttentionOutage('2025-06-14')).toBe(true)
    expect(isKnownAttentionOutage('2025-07-01')).toBe(true)
    expect(isKnownAttentionOutage('2025-07-02')).toBe(false)
  })

  it('bounds event effects to the selected study year', () => {
    const url = new URL(buildEventEffectsUrl('https://example.supabase.co', {
      start: '2026-01-01', end: '2026-12-31', scope: 'affected', windowDays: 14,
      timing: 'onset', alerts: ['Orange', 'Red'],
    }))

    expect(url.searchParams.getAll('start_at')).toEqual(['gte.2026-01-01', 'lte.2026-12-31'])
    expect(url.searchParams.get('alert_level')).toBe('in.(Orange,Red)')
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

  it('maps all-alert effects and preserves affected-country arrays', () => {
    expect(mapEventEffect({
      event_id: 'gdacs:FL:1', hazard_type: 'flood', alert_level: 'Green',
      start_at: '2025-01-01', end_at: '2025-01-03', geography_ids: ['GBR', 'FRA'],
      scope: 'affected', topic_id: 'electric_vehicles', window_days: 14,
      timing: 'onset', complete: true, missing_days: 0, overlap: false,
      matched_pre_mean: 2, matched_post_mean: 3, matched_change: 1,
      matched_percent_change: 50, political_pre_mean: 1, political_post_mean: 2,
      political_change: 1, political_percent_change: 100, political_share_pre: 50,
      political_share_post: 66.7, political_share_change: 16.7,
    })).toMatchObject({
      eventId: 'gdacs:FL:1', alertLevel: 'Green', geographyIds: ['GBR', 'FRA'],
      topicId: 'electric_vehicles', matchedPercentChange: 50,
    })
  })

  it('maps activity and regional attention rows', () => {
    expect(mapEventActivityRow({
      activity_date: '2025-02-02', geography: '__eu27__', hazard_type: 'wildfire',
      alert_level: 'Orange', events_started: 2, events_active: 4, events_ended: 1,
    })).toEqual({
      date: '2025-02-02', geography: '__eu27__', hazardType: 'wildfire',
      alertLevel: 'Orange', eventsStarted: 2, eventsActive: 4, eventsEnded: 1,
    })
    expect(mapRegionAttentionRow({
      observation_date: '2025-02-02', region_id: 'eu27', topic_id: 'climate_change',
      matched_count: 20, political_count: 5, political_actor_count: 3,
      government_action_count: 2, party_politics_count: 1, official_source_count: 1,
      political_share: 25,
    })).toMatchObject({ date: '2025-02-02', regionId: 'eu27', politicalShare: 25 })
  })
})
