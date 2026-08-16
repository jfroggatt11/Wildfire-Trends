create table if not exists public.articles (
  record_id text primary key,
  article_date date not null,
  source text not null default 'gdelt_ngrams',
  topic_id text not null check (topic_id in ('climate_change', 'electric_vehicles')),
  geography text not null,
  url text not null,
  domain text,
  published_at timestamptz,
  outlet_name text,
  outlet_logo text,
  outlet_twitter text,
  title text,
  image_url text,
  description text,
  language text,
  author text,
  political_actor boolean not null default false,
  government_action boolean not null default false,
  party_politics boolean not null default false,
  official_source boolean not null default false,
  political boolean generated always as (
    political_actor or government_action or party_politics or official_source
  ) stored,
  match_evidence jsonb not null default '[]'::jsonb,
  match_evidence_total integer not null default 0,
  match_evidence_truncated boolean not null default false,
  collected_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  constraint articles_match_evidence_total_nonnegative
    check (match_evidence_total >= 0)
);

create index if not exists articles_window_idx
  on public.articles (article_date, topic_id, geography, published_at desc);
create index if not exists articles_topic_date_idx
  on public.articles (topic_id, article_date, published_at desc);
create index if not exists articles_political_window_idx
  on public.articles (article_date, topic_id, geography, published_at desc)
  where political;

alter table public.articles enable row level security;

revoke all on table public.articles from anon, authenticated;
grant select on table public.articles to anon, authenticated;
grant all on table public.articles to service_role;

drop policy if exists "Public read-only article explorer" on public.articles;
create policy "Public read-only article explorer"
  on public.articles
  for select
  to anon, authenticated
  using (true);

comment on table public.articles is
  'Frontend serving copy of the canonical local GDELT NGrams article Parquet panel.';
