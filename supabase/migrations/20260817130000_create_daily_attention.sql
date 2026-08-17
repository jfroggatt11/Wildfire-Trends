create table if not exists public.daily_attention (
  record_id text primary key,
  observation_date date not null,
  source text not null default 'gdelt_ngrams',
  topic_id text not null check (topic_id in ('climate_change', 'electric_vehicles')),
  query_id text not null,
  query_expression text not null default '',
  geography text not null,
  language text,
  matched_count bigint,
  global_monitored_count bigint,
  country_monitored_count bigint,
  global_attention_share double precision,
  country_attention_share double precision,
  attention_index double precision,
  political_count bigint,
  political_actor_count bigint,
  government_action_count bigint,
  party_politics_count bigint,
  official_source_count bigint,
  political_share_of_matched double precision,
  collected_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb
);

-- query_expression is intentionally not copied to the browser-serving table: the
-- full multilingual expression and provenance JSON remain in canonical Parquet.
alter table public.daily_attention
  alter column query_expression set default '';

create index if not exists daily_attention_window_idx
  on public.daily_attention (observation_date, topic_id, geography);
create index if not exists daily_attention_geography_window_idx
  on public.daily_attention (geography, observation_date, topic_id);

alter table public.daily_attention enable row level security;

revoke all on table public.daily_attention from anon, authenticated;
grant select on table public.daily_attention to anon, authenticated;
grant all on table public.daily_attention to service_role;

drop policy if exists "Public read-only daily attention" on public.daily_attention;
create policy "Public read-only daily attention"
  on public.daily_attention
  for select
  to anon, authenticated
  using (true);

comment on table public.daily_attention is
  'Frontend serving copy of canonical local GDELT NGrams topic-country-day Parquet rows.';
