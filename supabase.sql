-- Run once in the Supabase SQL Editor. Application data are accessible only by the server service role.
create table if not exists public.studio_objects (
  kind text not null,
  id text not null,
  body jsonb not null,
  created_at timestamptz not null default now(),
  primary key (kind,id)
);
alter table public.studio_objects enable row level security;
revoke all on public.studio_objects from anon, authenticated;
grant select,insert,update,delete on public.studio_objects to service_role;

insert into storage.buckets (id,name,public,file_size_limit)
values ('studio-media','studio-media',false,26214400)
on conflict (id) do nothing;
