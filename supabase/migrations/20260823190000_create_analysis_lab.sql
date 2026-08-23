create table if not exists public.event_effects (
  event_id text not null,
  hazard_type text not null check (hazard_type in ('wildfire', 'flood')),
  alert_level text not null check (alert_level in ('Green', 'Orange', 'Red')),
  start_at date not null,
  end_at date not null,
  geography_ids text[] not null default '{}',
  scope text not null check (scope in ('affected', 'other_eu27', 'rest_world', 'global')),
  topic_id text not null check (topic_id in ('climate_change', 'electric_vehicles')),
  window_days integer not null check (window_days in (7, 14, 28)),
  timing text not null check (timing in ('onset', 'persistence')),
  complete boolean not null,
  missing_days integer not null,
  overlap boolean not null,
  matched_pre_mean double precision,
  matched_post_mean double precision,
  matched_change double precision,
  matched_percent_change double precision,
  political_pre_mean double precision,
  political_post_mean double precision,
  political_change double precision,
  political_percent_change double precision,
  political_share_pre double precision,
  political_share_post double precision,
  political_share_change double precision,
  primary key (event_id, scope, topic_id, window_days, timing)
);

create index if not exists event_effects_specification_idx
  on public.event_effects (scope, window_days, timing, topic_id, alert_level, hazard_type);
create index if not exists event_effects_event_idx
  on public.event_effects (event_id);

create table if not exists public.daily_event_activity (
  activity_date date not null,
  geography text not null,
  hazard_type text not null check (hazard_type in ('wildfire', 'flood')),
  alert_level text not null check (alert_level in ('Green', 'Orange', 'Red')),
  events_started integer not null default 0,
  events_active integer not null default 0,
  events_ended integer not null default 0,
  primary key (activity_date, geography, hazard_type, alert_level)
);

create index if not exists daily_event_activity_lookup_idx
  on public.daily_event_activity (geography, activity_date, alert_level, hazard_type);

create table if not exists public.daily_attention_regions (
  observation_date date not null,
  region_id text not null check (region_id in ('global', 'eu27')),
  topic_id text not null check (topic_id in ('climate_change', 'electric_vehicles')),
  matched_count bigint not null,
  political_count bigint not null,
  political_actor_count bigint not null,
  government_action_count bigint not null,
  party_politics_count bigint not null,
  official_source_count bigint not null,
  political_share double precision,
  primary key (observation_date, region_id, topic_id)
);

create index if not exists daily_attention_regions_lookup_idx
  on public.daily_attention_regions (region_id, observation_date, topic_id);

alter table public.event_effects enable row level security;
alter table public.daily_event_activity enable row level security;
alter table public.daily_attention_regions enable row level security;

revoke all on table public.event_effects from anon, authenticated;
revoke all on table public.daily_event_activity from anon, authenticated;
revoke all on table public.daily_attention_regions from anon, authenticated;
grant select on table public.event_effects to anon, authenticated;
grant select on table public.daily_event_activity to anon, authenticated;
grant select on table public.daily_attention_regions to anon, authenticated;
grant all on table public.event_effects to service_role;
grant all on table public.daily_event_activity to service_role;
grant all on table public.daily_attention_regions to service_role;

drop policy if exists "Public read-only event effects" on public.event_effects;
create policy "Public read-only event effects"
  on public.event_effects for select to anon, authenticated using (true);

drop policy if exists "Public read-only event activity" on public.daily_event_activity;
create policy "Public read-only event activity"
  on public.daily_event_activity for select to anon, authenticated using (true);

drop policy if exists "Public read-only regional attention" on public.daily_attention_regions;
create policy "Public read-only regional attention"
  on public.daily_attention_regions for select to anon, authenticated using (true);

comment on table public.event_effects is
  'Precomputed complete-window event effects for Analysis Lab filtering.';
comment on table public.daily_event_activity is
  'Sparse GDACS event starts, active events and endings by affected country and region.';
comment on table public.daily_attention_regions is
  'Daily GDELT NGrams attention aggregated across global and EU27 publishing markets.';
