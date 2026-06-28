create extension if not exists pgcrypto;

create table if not exists public.page_visits (
  id uuid primary key default gen_random_uuid(),
  visitor_id text not null,
  session_id text not null unique,
  page_path text default '/',
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

alter table public.page_visits enable row level security;

create index if not exists page_visits_visitor_id_idx
on public.page_visits (visitor_id);

create index if not exists page_visits_created_at_idx
on public.page_visits (created_at);

create index if not exists page_visits_last_seen_at_idx
on public.page_visits (last_seen_at);

create or replace function public.get_page_visit_stats()
returns table(active integer, total integer, today integer)
language sql
security definer
set search_path = public
as $$
  select
    count(distinct session_id) filter (
      where last_seen_at >= now() - interval '5 minutes'
    )::integer as active,
    count(distinct visitor_id)::integer as total,
    count(distinct visitor_id) filter (
      where (created_at at time zone 'Asia/Seoul')::date = (now() at time zone 'Asia/Seoul')::date
    )::integer as today
  from public.page_visits;
$$;

create or replace function public.record_page_visit(
  p_visitor_id text,
  p_session_id text,
  p_page_path text default '/'
)
returns table(active integer, total integer, today integer)
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.page_visits (visitor_id, session_id, page_path, last_seen_at)
  values (
    left(coalesce(p_visitor_id, ''), 128),
    left(coalesce(p_session_id, ''), 128),
    left(coalesce(p_page_path, '/'), 300),
    now()
  )
  on conflict (session_id)
  do update set
    last_seen_at = excluded.last_seen_at,
    page_path = excluded.page_path;

  return query
  select * from public.get_page_visit_stats();
end;
$$;

grant execute on function public.get_page_visit_stats() to anon;
grant execute on function public.record_page_visit(text, text, text) to anon;
