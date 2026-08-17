create table if not exists public.articles (
  record_id text primary key,
  article_date date not null,
  topic_id text not null check (topic_id in ('climate_change', 'electric_vehicles')),
  geography text not null,
  url text not null,
  domain text,
  published_at timestamptz,
  outlet_name text,
  title text,
  language text,
  political_actor boolean not null default false,
  government_action boolean not null default false,
  party_politics boolean not null default false,
  official_source boolean not null default false,
  political boolean generated always as (
    political_actor or government_action or party_politics or official_source
  ) stored
);

create index if not exists articles_window_idx
  on public.articles (article_date, topic_id, geography, published_at desc);
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
  'Compact frontend serving copy; complete article metadata and match evidence remain in canonical local Parquet.';
