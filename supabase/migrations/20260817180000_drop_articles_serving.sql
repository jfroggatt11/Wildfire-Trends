-- Article-level records remain in canonical local Parquet for validation. The
-- public application serves only topic-country-day aggregate counts.
drop table if exists public.articles;
