-- Upgrade an existing v12 database; this is not a fresh-database schema.
-- Stop dashboard imports and the Discord runner; keep a database backup first.
begin;
do $$
declare t text;
begin
  foreach t in array array['events','fighters','fights','promotions','weight_classes','external_ids','data_sources','odds',
    'fight_research','event_research','bet_tickets','bet_legs','fighter_history_entries','fighter_history_coverage',
    'data_sync_runs','history_maintenance_runs','fight_stats','fight_round_stats'] loop
    if to_regclass('public.'||t) is null then raise exception 'Existing v12 schema is incomplete: missing %. Restore the working database schema before upgrading.',t; end if;
  end loop;
  if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='bet_tickets' and column_name='archived_at') then
    raise exception 'Apply the existing v12 migrations through 030 before this upgrade.';
  end if;
end $$;

-- 202610120031_protect_fight_identity.sql
-- Protect side-based singles, parlay legs, research and saved analysis even
-- when an older importer writes directly. No historical rows are rewritten.


create or replace function public.protect_mma_fight_identity()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.fight_id is distinct from old.fight_id
     or new.event_id is distinct from old.event_id then
    raise exception using
      errcode = '23514',
      message = format('Fight #%s identity cannot be moved to another ID or event.', old.fight_id),
      hint = 'Preserve existing bets and research. Review the provider mapping or create a separate rebooked fight.';
  end if;

  if new.fighter_a_id is not distinct from old.fighter_a_id
     and new.fighter_b_id is not distinct from old.fighter_b_id then
    return new;
  end if;

  if new.fighter_a_id is not distinct from old.fighter_b_id
     and new.fighter_b_id is not distinct from old.fighter_a_id then
    new.fighter_a_id := old.fighter_a_id;
    new.fighter_b_id := old.fighter_b_id;
    return new;
  end if;

  raise exception using
    errcode = '23514',
    message = format('Fight #%s stored participants cannot be replaced.', old.fight_id),
    hint = 'Preserve existing bets and research. Review the replacement or fighter identity mapping.';
end;
$$;

drop trigger if exists protect_mma_fight_identity on public.fights;
create trigger protect_mma_fight_identity
before update of fight_id, event_id, fighter_a_id, fighter_b_id
on public.fights
for each row execute function public.protect_mma_fight_identity();

comment on function public.protect_mma_fight_identity() is
  'Keeps stored fight IDs, event assignments and fighter sides stable for bets and research. Provider side reversals retain the original sides.';



-- 202610120032_coordinate_imports.sql
-- Service-only leases and atomic provider writes. Existing records are retained.


alter table public.events add column if not exists card_observed_at timestamptz;
alter table public.fights add column if not exists source_observed_at timestamptz;
alter table public.fights add column if not exists result_confirmed_at timestamptz;
alter table public.fights add column if not exists result_source_id bigint references public.data_sources(source_id);
alter table public.odds add column if not exists observed_at timestamptz;

create table if not exists public.mma_sync_leases (
  lease_name text primary key,
  holder uuid not null,
  fence bigint not null default 1,
  heartbeat_at timestamptz not null,
  expires_at timestamptz not null
);
alter table public.mma_sync_leases enable row level security;
revoke all on public.mma_sync_leases from public, anon, authenticated;
grant select, insert, update, delete on public.mma_sync_leases to service_role;

-- Keep previous provider aliases when a source changes its competition ID.
-- The original external_ids table remains the current pointer for old clients.
create table if not exists public.mma_external_aliases (
  source_id bigint not null references public.data_sources(source_id),
  entity_type text not null check (entity_type in ('event','fight','fighter')),
  external_id text not null,
  internal_id bigint not null,
  external_url text,
  observed_at timestamptz not null default now(),
  primary key (source_id, entity_type, external_id)
);
alter table public.mma_external_aliases enable row level security;
revoke all on public.mma_external_aliases from public, anon, authenticated;
grant select, insert, update, delete on public.mma_external_aliases to service_role;
insert into public.mma_external_aliases (source_id,entity_type,external_id,internal_id,external_url)
select source_id,entity_type,external_id,min(internal_id),max(external_url)
from public.external_ids
where entity_type in ('event','fight','fighter') and external_id is not null
group by source_id,entity_type,external_id
having count(distinct internal_id)=1
on conflict do nothing;

create or replace function public.mma_claim_sync_lease(p_holder uuid, p_seconds integer default 180)
returns jsonb language plpgsql set search_path=public as $$
declare current_lease public.mma_sync_leases;
begin
  perform pg_advisory_xact_lock(hashtextextended('mma-import',0));
  select * into current_lease from public.mma_sync_leases where lease_name='imports' for update;
  if found and current_lease.expires_at > clock_timestamp() then
    if current_lease.holder <> p_holder then
      return jsonb_build_object('acquired',false);
    end if;
    return jsonb_build_object('acquired',true,'fence',current_lease.fence);
  end if;
  insert into public.mma_sync_leases (lease_name,holder,fence,heartbeat_at,expires_at)
  values ('imports',p_holder,coalesce(current_lease.fence,0)+1,clock_timestamp(),
    clock_timestamp()+make_interval(secs=>greatest(30,least(p_seconds,600))))
  on conflict (lease_name) do update set holder=excluded.holder,fence=excluded.fence,
    heartbeat_at=excluded.heartbeat_at,expires_at=excluded.expires_at;
  -- Recover abandoned status rows only after the previous writer's lease expires.
  update public.data_sync_runs set status='failed',finished_at=now(),
    summary=summary || '{"publishable":false,"interrupted":true,"recovery":"Previous import lease expired before completion."}'::jsonb
  where status='running';
  update public.history_maintenance_runs set status='failed',finished_at=now(),
    summary=summary || '{"interrupted":true}'::jsonb where status='running';
  return jsonb_build_object('acquired',true,'fence',coalesce(current_lease.fence,0)+1);
end; $$;

create or replace function public.mma_renew_sync_lease(p_holder uuid,p_fence bigint,p_seconds integer default 180)
returns boolean language plpgsql set search_path=public as $$
begin
  update public.mma_sync_leases set heartbeat_at=clock_timestamp(),
    expires_at=clock_timestamp()+make_interval(secs=>greatest(30,least(p_seconds,600)))
  where lease_name='imports' and holder=p_holder and fence=p_fence and expires_at>clock_timestamp();
  return found;
end; $$;

create or replace function public.mma_release_sync_lease(p_holder uuid,p_fence bigint)
returns boolean language plpgsql set search_path=public as $$
begin
  -- Retain the fence counter so an old worker cannot reclaim a reused token.
  update public.mma_sync_leases set expires_at=clock_timestamp()
  where lease_name='imports' and holder=p_holder and fence=p_fence;
  return found;
end; $$;

create or replace function public.mma_check_import_lease(p_holder uuid,p_fence bigint)
returns void language plpgsql set search_path=public as $$
declare current_lease public.mma_sync_leases;
begin
  perform pg_advisory_xact_lock(hashtextextended('mma-import',0));
  select * into current_lease from public.mma_sync_leases where lease_name='imports' for share;
  if p_holder is not null then
    if not found or current_lease.holder is distinct from p_holder or current_lease.fence is distinct from p_fence
       or current_lease.expires_at<=clock_timestamp() then
      raise exception using errcode='55P03',message='Import lease was lost; stale writer refused.';
    end if;
  elsif found and current_lease.expires_at>clock_timestamp() then
    raise exception using errcode='55P03',message='Another dashboard import is running.';
  end if;
end; $$;

create or replace function public.mma_find_external_identity(p_entity_type text,p_source_id bigint,p_external_id text)
returns jsonb language plpgsql set search_path=public as $$
declare ids bigint[]; mapping_id bigint;
begin
  select array_agg(distinct internal_id) into ids from (
    select internal_id from public.external_ids where entity_type=p_entity_type
      and source_id=p_source_id and external_id=p_external_id
    union all
    select internal_id from public.mma_external_aliases where entity_type=p_entity_type
      and source_id=p_source_id and external_id=p_external_id
  ) matches;
  if coalesce(cardinality(ids),0)>1 then
    raise exception using errcode='23514',message='Ambiguous external identity; review existing mappings.';
  end if;
  if coalesce(cardinality(ids),0)=0 then return null; end if;
  select external_id_map_id into mapping_id from public.external_ids
    where entity_type=p_entity_type and source_id=p_source_id and internal_id=ids[1]
    order by external_id_map_id limit 1;
  return jsonb_build_object('internal_id',ids[1],'external_id_map_id',mapping_id);
end; $$;

create or replace function public.mma_preserve_results()
returns trigger language plpgsql set search_path=public as $$
begin
  if new.fight_status='completed' and new.result_type in ('draw','no_contest') then new.fight_status:=new.result_type; end if;
  if new.fight_status in ('draw','no_contest') then new.winner_id:=null; end if;
  if new.winner_id is not null and new.winner_id not in (new.fighter_a_id,new.fighter_b_id) then
    raise exception 'Winner does not belong to the stored participants' using errcode='23514';
  end if;
  if tg_op='INSERT' then
    if new.fight_status in ('draw','no_contest') or (new.fight_status='completed' and new.winner_id is not null) then
      new.result_confirmed_at:=coalesce(new.source_observed_at,now());
    end if;
    return new;
  end if;
  if old.ruleset is not null and new.ruleset is distinct from old.ruleset
     and (exists(select 1 from public.bet_legs where fight_id=old.fight_id)
       or exists(select 1 from public.fight_research where fight_id=old.fight_id and bet_side is not null and coalesce(stake_units,0)>0)) then
    raise exception 'A saved bet cannot switch to another ruleset; review required' using errcode='23514';
  end if;
  if old.fight_status in ('completed','draw','no_contest') and new.fight_status in ('completed','draw','no_contest')
     and (new.fight_status is distinct from old.fight_status or new.winner_id is distinct from old.winner_id)
     and new.result_source_id is distinct from old.result_source_id and old.result_source_id is not null then
    raise exception 'Sources disagree about a confirmed result; review required' using errcode='23514';
  end if;
  if old.fight_status in ('completed','draw','no_contest') and
     (new.fight_status not in ('completed','draw','no_contest') or
      (new.fight_status='completed' and new.winner_id is null)) then
    new.fight_status:=old.fight_status;
    new.winner_id:=old.winner_id;
    new.result_type:=old.result_type;
    new.method:=old.method;
    new.finish_round:=old.finish_round;
    new.finish_time_seconds:=old.finish_time_seconds;
    new.result_confirmed_at:=old.result_confirmed_at;
    new.result_source_id:=old.result_source_id;
  elsif new.fight_status=old.fight_status and new.winner_id is not distinct from old.winner_id then
    new.result_source_id:=coalesce(old.result_source_id,new.result_source_id);
    new.method:=coalesce(new.method,old.method);
    new.finish_round:=coalesce(new.finish_round,old.finish_round);
    new.finish_time_seconds:=coalesce(new.finish_time_seconds,old.finish_time_seconds);
  end if;
  if new.fight_status in ('draw','no_contest') then new.winner_id:=null; end if;
  if new.fight_status in ('draw','no_contest') or (new.fight_status='completed' and new.winner_id is not null) then
    if new.fight_status is distinct from old.fight_status or new.winner_id is distinct from old.winner_id then
      new.result_confirmed_at:=coalesce(new.source_observed_at,now());
    end if;
  end if;
  return new;
end; $$;
drop trigger if exists mma_preserve_results on public.fights;
create trigger mma_preserve_results before insert or update on public.fights
for each row execute function public.mma_preserve_results();

create or replace function public.mma_preserve_event_status()
returns trigger language plpgsql set search_path=public as $$
begin
  if old.event_status='completed' and new.event_status in ('scheduled','upcoming','live')
     and not(new.event_status='live' and exists(select 1 from public.fights where event_id=old.event_id and fight_status='live'))
     and exists(select 1 from public.fights where event_id=old.event_id and (fight_status in ('draw','no_contest') or (fight_status='completed' and winner_id is not null))) then
    new.event_status:=old.event_status;
  elsif old.event_status='live' and new.event_status in ('scheduled','upcoming') then
    new.event_status:=old.event_status;
  end if;
  return new;
end; $$;
drop trigger if exists mma_preserve_event_status on public.events;
create trigger mma_preserve_event_status before update on public.events
for each row execute function public.mma_preserve_event_status();

create or replace function public.mma_upsert_import_entity(
  p_entity_type text,p_payload jsonb,p_source_id bigint,p_external_id text,
  p_existing_id bigint default null,p_external_url text default null,
  p_holder uuid default null,p_fence bigint default null,p_catalog boolean default false
) returns jsonb language plpgsql set search_path=public as $$
declare
  target_table text; pk text; target_id bigint; mapped jsonb; row_data jsonb;
  columns_sql text; values_sql text; updates_sql text; current_mapping bigint;
  key text; outcome text;
begin
  perform public.mma_check_import_lease(p_holder,p_fence);
  target_table:=case p_entity_type when 'event' then 'events' when 'fighter' then 'fighters' when 'fight' then 'fights' end;
  pk:=case p_entity_type when 'event' then 'event_id' when 'fighter' then 'fighter_id' when 'fight' then 'fight_id' end;
  if target_table is null or coalesce(p_external_id,'')='' or jsonb_typeof(p_payload)<>'object' then
    raise exception 'Invalid provider entity payload.';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_entity_type||':'||p_source_id||':'||p_external_id,0));
  mapped:=public.mma_find_external_identity(p_entity_type,p_source_id,p_external_id);
  target_id:=coalesce(p_existing_id,(mapped->>'internal_id')::bigint);
  if p_existing_id is not null and mapped is not null and (mapped->>'internal_id')::bigint<>p_existing_id then
    -- Even an unused duplicate can receive a bet from an already-open tab.
    -- Source identities never move silently between historical fight records.
    raise exception 'Conflicting mapped identity requires review; both records were retained.' using errcode='23514';
  end if;
  if p_payload ? pk then raise exception 'Provider payload cannot set an internal primary key.'; end if;
  for key in select jsonb_object_keys(p_payload) loop
    if not exists(select 1 from pg_attribute where attrelid=to_regclass('public.'||target_table)
        and attname=key and attnum>0 and not attisdropped) then
      raise exception 'Unsupported provider field: %',key;
    end if;
  end loop;
  if p_catalog then
    if p_entity_type<>'event' then raise exception 'Catalog may only write events.'; end if;
    select coalesce(jsonb_object_agg(k,v),'{}'::jsonb) into p_payload
      from jsonb_each(p_payload) entries(k,v) where k in ('promotion_id','event_name','event_date','updated_at');
    if target_id is null then p_payload:=p_payload||'{"event_status":"scheduled"}'::jsonb; end if;
  elsif p_entity_type='event' then
    p_payload:=p_payload||jsonb_build_object('card_observed_at',clock_timestamp());
  elsif p_entity_type='fight' and p_payload<>'{}'::jsonb then
    p_payload:=p_payload||jsonb_build_object('source_observed_at',clock_timestamp());
    if p_payload->>'fight_status' in ('draw','no_contest') or (p_payload->>'fight_status'='completed' and nullif(p_payload->>'winner_id','') is not null) then
      p_payload:=p_payload||jsonb_build_object('result_source_id',p_source_id);
    end if;
  end if;
  select string_agg(format('%I',k),',' order by k),string_agg(format('r.%I',k),',' order by k),
    string_agg(format('%I=r.%I',k,k),',' order by k)
    into columns_sql,values_sql,updates_sql from jsonb_object_keys(p_payload) keys(k);
  if p_payload='{}'::jsonb then
    if target_id is null then raise exception 'Cannot create an empty entity'; end if;
    execute format('select to_jsonb(t.*) from public.%I t where %I=$1',target_table,pk) using target_id into row_data;
    if row_data is null then raise exception 'Mapped entity does not exist; review required.'; end if;
    outcome:='updated';
  elsif target_id is null then
    execute format('insert into public.%I (%s) select %s from jsonb_populate_record(null::public.%I,$1) r returning to_jsonb(%I.*)',
      target_table,columns_sql,values_sql,target_table,target_table) using p_payload into row_data;
    target_id:=(row_data->>pk)::bigint; outcome:='imported';
  else
    execute format('update public.%I t set %s from jsonb_populate_record(null::public.%I,$1) r where t.%I=$2 returning to_jsonb(t.*)',
      target_table,updates_sql,target_table,pk) using p_payload,target_id into row_data;
    if row_data is null then raise exception 'Mapped entity does not exist; review required.'; end if;
    outcome:='updated';
  end if;
  -- Save old pointer identities before changing a provider's current pointer.
  insert into public.mma_external_aliases (source_id,entity_type,external_id,internal_id,external_url)
    select source_id,entity_type,external_id,internal_id,external_url from public.external_ids
    where source_id=p_source_id and entity_type=p_entity_type and internal_id=target_id
    on conflict do nothing;
  select external_id_map_id into current_mapping from public.external_ids
    where entity_type=p_entity_type and source_id=p_source_id and internal_id=target_id
    order by external_id_map_id limit 1;
  if current_mapping is null then
    insert into public.external_ids (entity_type,internal_id,source_id,external_id,external_url,updated_at)
    values(p_entity_type,target_id,p_source_id,p_external_id,p_external_url,now());
  else
    update public.external_ids set external_id=p_external_id,external_url=coalesce(p_external_url,external_url),updated_at=now()
      where external_id_map_id=current_mapping;
  end if;
  insert into public.mma_external_aliases (source_id,entity_type,external_id,internal_id,external_url)
  values(p_source_id,p_entity_type,p_external_id,target_id,p_external_url)
  on conflict (source_id,entity_type,external_id) do update set
    internal_id=excluded.internal_id,external_url=coalesce(excluded.external_url,mma_external_aliases.external_url),observed_at=now();
  return jsonb_build_object('status',outcome,'internal_id',target_id,'row',row_data);
end; $$;

create or replace function public.mma_apply_import_batch(
  p_operations jsonb,p_holder uuid default null,p_fence bigint default null
) returns jsonb language plpgsql set search_path=public as $$
declare
  operation jsonb; payload jsonb; ids jsonb:='{}'::jsonb; results jsonb:='[]'::jsonb;
  saved jsonb; key text; ref bigint; existing_id bigint; temporary_id bigint; affected bigint[]:='{}'; states jsonb;
begin
  perform public.mma_check_import_lease(p_holder,p_fence);
  if jsonb_typeof(p_operations)<>'array' or jsonb_array_length(p_operations)>500 then
    raise exception 'Import batch is invalid or exceeds the event limit.';
  end if;
  for operation in select value from jsonb_array_elements(p_operations) loop
    payload:=operation->'p_payload';
    foreach key in array array['event_id','fighter_a_id','fighter_b_id','winner_id'] loop
      if payload ? key and (payload->>key)::bigint<0 then
        ref:=(ids->>(payload->>key))::bigint;
        if ref is null then raise exception 'Unresolved temporary import identity.'; end if;
        payload:=jsonb_set(payload,array[key],to_jsonb(ref));
      end if;
    end loop;
    existing_id:=(operation->>'p_existing_id')::bigint;
    if existing_id<0 then
      existing_id:=(ids->>existing_id::text)::bigint;
      if existing_id is null then raise exception 'Unresolved temporary existing identity.'; end if;
    end if;
    saved:=public.mma_upsert_import_entity(operation->>'p_entity_type',payload,
      (operation->>'p_source_id')::bigint,operation->>'p_external_id',existing_id,
      operation->>'p_external_url',p_holder,p_fence,coalesce((operation->>'p_catalog')::boolean,false));
    temporary_id:=(operation->>'temporary_id')::bigint;
    if temporary_id<0 then ids:=ids||jsonb_build_object(temporary_id::text,saved->'internal_id'); end if;
    results:=results||jsonb_build_array(saved);
    if operation->>'p_entity_type'='event' then affected:=array_append(affected,(saved->>'internal_id')::bigint); end if;
  end loop;
  -- Whole-event cancellation is positive evidence; a missing source row is not.
  update public.fights f set fight_status='cancelled',source_observed_at=clock_timestamp(),updated_at=now()
    from public.events e where f.event_id=e.event_id and e.event_id=any(affected)
      and e.event_status in ('cancelled','canceled') and f.fight_status in ('scheduled','upcoming');
  -- Reconcile after every bout has committed inside this transaction. Dates
  -- alone cannot finalize a card, and a missing winner remains unresolved.
  with card as (
    select event_id,count(*) n,bool_or(fight_status='live') live,
      bool_and(coalesce(fight_status,'unknown') in ('draw','no_contest','cancelled') or (coalesce(fight_status,'unknown')='completed' and winner_id is not null)) final
    from public.fights where event_id=any(affected) group by event_id
  ), phase as (
    select e.event_id,case when e.event_status in ('cancelled','canceled') then e.event_status
      when coalesce(c.live,false) then 'live' when c.n>0 and coalesce(c.final,false) then 'completed'
      when e.event_status='completed' then 'unknown' else e.event_status end event_status
    from public.events e left join card c using(event_id) where e.event_id=any(affected)
  ) update public.events e set event_status=p.event_status from phase p where e.event_id=p.event_id;
  select coalesce(jsonb_object_agg(event_id::text,event_status),'{}') into states from public.events where event_id=any(affected);
  return jsonb_build_object('ids',ids,'results',results,'event_states',states);
end; $$;

revoke all on function public.mma_apply_import_batch(jsonb,uuid,bigint) from public,anon,authenticated;
grant execute on function public.mma_apply_import_batch(jsonb,uuid,bigint) to service_role;

create index if not exists mma_external_aliases_internal_idx on public.mma_external_aliases(entity_type,internal_id);
create index if not exists mma_fights_event_idx on public.fights(event_id);
create index if not exists mma_events_promotion_date_idx on public.events(promotion_id,event_date);
create index if not exists mma_odds_recent_market_idx on public.odds(fight_id,market_type,recorded_at desc);

revoke all on function public.mma_claim_sync_lease(uuid,integer),public.mma_renew_sync_lease(uuid,bigint,integer),
  public.mma_release_sync_lease(uuid,bigint),public.mma_check_import_lease(uuid,bigint),
  public.mma_find_external_identity(text,bigint,text),
  public.mma_upsert_import_entity(text,jsonb,bigint,text,bigint,text,uuid,bigint,boolean)
  from public,anon,authenticated;
grant execute on function public.mma_claim_sync_lease(uuid,integer),public.mma_renew_sync_lease(uuid,bigint,integer),
  public.mma_release_sync_lease(uuid,bigint),public.mma_check_import_lease(uuid,bigint),
  public.mma_find_external_identity(text,bigint,text),
  public.mma_upsert_import_entity(text,jsonb,bigint,text,bigint,text,uuid,bigint,boolean)
  to service_role;
notify pgrst,'reload schema';


-- 202610120033_fresh_odds_and_reads.sql
-- Requires the existing dashboard schema and migrations 001-032.

alter table public.odds add column if not exists provider_updated_at timestamptz;
create table if not exists public.mma_odds_observations (
  observation_id bigint generated by default as identity primary key,
  fight_id bigint not null references public.fights(fight_id),
  fighter_id bigint not null references public.fighters(fighter_id),
  sportsbook_key text not null, sportsbook text not null,
  source_id bigint not null references public.data_sources(source_id),
  american_odds integer not null check(american_odds <= -100 or american_odds >= 100),
  observed_at timestamptz not null, provider_updated_at timestamptz,
  unique(fight_id,fighter_id,sportsbook_key,source_id)
);
alter table public.mma_odds_observations enable row level security;
revoke all on public.mma_odds_observations from public,anon,authenticated;
grant all on public.mma_odds_observations to service_role;
grant select on public.mma_odds_observations to authenticated;
drop policy if exists observations_read on public.mma_odds_observations;
create policy observations_read on public.mma_odds_observations for select to authenticated using(true);

create or replace function public.mma_record_odds(p_rows jsonb,p_holder uuid default null,p_fence bigint default null)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare r jsonb; old public.mma_odds_observations; f public.fights;
  stamp timestamptz := clock_timestamp(); provider_stamp timestamptz;
  inserted integer:=0; unchanged integer:=0; skipped integer:=0;
begin
  perform public.mma_check_import_lease(p_holder,p_fence);
  if jsonb_typeof(p_rows)<>'array' or jsonb_array_length(p_rows)>2000 then raise exception 'Invalid odds batch'; end if;
  for r in select value from jsonb_array_elements(p_rows) loop
    select * into strict f from public.fights where fight_id=(r->>'fight_id')::bigint;
    if (r->>'fighter_id')::bigint not in (f.fighter_a_id,f.fighter_b_id)
      or r->>'market_type'<>'moneyline' or nullif(r->>'sportsbook_key','') is null
      or not ((r->>'american_odds')::integer<=-100 or (r->>'american_odds')::integer>=100)
      then raise exception 'Invalid moneyline identity or price'; end if;
    perform pg_advisory_xact_lock(hashtextextended('mma-odds:'||(r->>'fight_id')||':'||
      (r->>'fighter_id')||':'||(r->>'sportsbook_key')||':'||(r->>'source_id'),0));
    provider_stamp := nullif(r->>'provider_updated_at','')::timestamptz;
    if provider_stamp>stamp+interval '5 minutes' then raise exception 'Odds source timestamp is in the future'; end if;
    select * into old from public.mma_odds_observations where fight_id=f.fight_id
      and fighter_id=(r->>'fighter_id')::bigint and sportsbook_key=r->>'sportsbook_key'
      and source_id=(r->>'source_id')::bigint for update;
    if provider_stamp is not null and exists(select 1 from public.mma_odds_observations previous
      where previous.fight_id=f.fight_id and previous.fighter_id=(r->>'fighter_id')::bigint
        and previous.sportsbook_key=r->>'sportsbook_key' and previous.provider_updated_at>provider_stamp)
      then skipped:=skipped+1; continue; end if;
    -- Rechecking an unchanged price refreshes its observation, not its movement history.
    if old.observation_id is not null and old.american_odds=(r->>'american_odds')::integer then
      unchanged:=unchanged+1;
    else
      insert into public.odds(fight_id,fighter_id,sportsbook,sportsbook_key,market_type,selection_name,
        american_odds,decimal_odds,implied_probability,source_id,recorded_at,observed_at,provider_updated_at,market_commence_time)
      values(f.fight_id,(r->>'fighter_id')::bigint,r->>'sportsbook',r->>'sportsbook_key','moneyline',r->>'selection_name',
        (r->>'american_odds')::integer,(r->>'decimal_odds')::numeric,(r->>'implied_probability')::numeric,
        (r->>'source_id')::bigint,stamp,stamp,provider_stamp,nullif(r->>'market_commence_time','')::timestamptz);
      inserted:=inserted+1;
    end if;
    insert into public.mma_odds_observations(fight_id,fighter_id,sportsbook_key,sportsbook,source_id,american_odds,observed_at,provider_updated_at)
      values(f.fight_id,(r->>'fighter_id')::bigint,r->>'sportsbook_key',r->>'sportsbook',(r->>'source_id')::bigint,
        (r->>'american_odds')::integer,stamp,provider_stamp)
      on conflict(fight_id,fighter_id,sportsbook_key,source_id) do update set
        sportsbook=excluded.sportsbook,american_odds=excluded.american_odds,observed_at=excluded.observed_at,
        provider_updated_at=coalesce(excluded.provider_updated_at,mma_odds_observations.provider_updated_at);
  end loop;
  return jsonb_build_object('inserted',inserted,'unchanged',unchanged,'skipped',skipped);
end $$;

-- Compact history: at most first/latest/last-known-pre-fight per side/book/source.
-- Security invoker preserves the dashboard's existing read policies.
create or replace function public.mma_moneyline_snapshots(p_fight_ids bigint[])
returns setof public.odds language sql stable security invoker set search_path=public,pg_temp as $$
  with ranked as (
    select o.odds_id,
      row_number() over(partition by o.fight_id,o.fighter_id,coalesce(o.sportsbook_key,o.sportsbook),o.source_id order by o.recorded_at,o.odds_id) first_rank,
      row_number() over(partition by o.fight_id,o.fighter_id,coalesce(o.sportsbook_key,o.sportsbook),o.source_id order by o.recorded_at desc,o.odds_id desc) latest_rank,
      row_number() over(partition by o.fight_id,o.fighter_id,coalesce(o.sportsbook_key,o.sportsbook),o.source_id
        order by (coalesce(o.provider_updated_at,o.recorded_at)<coalesce(o.market_commence_time,e.event_start_time,(e.event_date+1)::timestamptz)) desc,
          coalesce(o.provider_updated_at,o.recorded_at) desc,o.odds_id desc) close_rank
    from public.odds o join public.fights f using(fight_id) join public.events e using(event_id)
    where o.fight_id=any(p_fight_ids) and o.market_type='moneyline'
  ) select o.* from public.odds o join ranked r using(odds_id)
    where r.first_rank=1 or r.latest_rank=1 or r.close_rank=1;
$$;

-- The scalar JSON response avoids PostgREST row caps and includes true history
-- counts; fetching three representative rows must not pretend only three exist.
create or replace function public.mma_moneyline_snapshot_summary(p_fight_ids bigint[])
returns jsonb language sql stable security invoker set search_path=public,pg_temp as $$
  with counts as (
    select fight_id,fighter_id,coalesce(sportsbook_key,sportsbook) book,source_id,count(*) n
      from public.odds where fight_id=any(p_fight_ids) and market_type='moneyline'
      group by fight_id,fighter_id,coalesce(sportsbook_key,sportsbook),source_id
  ) select coalesce(jsonb_agg(to_jsonb(o)||jsonb_build_object('snapshot_count',c.n,
      'snapshot_group',concat(c.book,':',c.source_id))),'[]')
    from public.mma_moneyline_snapshots(p_fight_ids) o join counts c on c.fight_id=o.fight_id and c.fighter_id=o.fighter_id
      and c.book=coalesce(o.sportsbook_key,o.sportsbook) and c.source_id is not distinct from o.source_id;
$$;

-- Bounded, fenced upserts for auxiliary importer data. No arbitrary tables/keys.
create or replace function public.mma_write_import_rows(p_table text,p_rows jsonb,p_holder uuid default null,p_fence bigint default null)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare keys text; cols text; assignments text; r jsonb; result jsonb; saved jsonb:='[]'; bad text;
begin
  perform public.mma_check_import_lease(p_holder,p_fence);
  keys := case p_table
    when 'fighter_history_entries' then 'fighter_id,source_id,external_bout_id'
    when 'fighter_history_coverage' then 'fighter_id'
    when 'fight_stats' then 'fight_id,fighter_id,stat_name,round_number,source_id'
    when 'fight_round_stats' then 'fight_id,fighter_id,round_number,source_id'
    when 'data_sync_runs' then 'data_sync_run_id'
    when 'history_maintenance_runs' then 'history_maintenance_run_id' end;
  if keys is null or jsonb_typeof(p_rows)<>'array' or jsonb_array_length(p_rows)>2000 then raise exception 'Invalid auxiliary import batch'; end if;
  for r in select value from jsonb_array_elements(p_rows) loop
    select k into bad from jsonb_object_keys(r) k where not exists (
      select 1 from pg_attribute a where a.attrelid=format('public.%I',p_table)::regclass
        and a.attname=k and a.attnum>0 and not a.attisdropped and (a.attidentity='' or p_table in ('data_sync_runs','history_maintenance_runs'))) limit 1;
    if bad is not null then raise exception 'Unsupported auxiliary field'; end if;
    select string_agg(format('%I',k),',' order by k),string_agg(format('%1$I=excluded.%1$I',k),',' order by k)
      into cols,assignments from jsonb_object_keys(r) k;
    execute format('insert into public.%1$I(%2$s) select %2$s from jsonb_populate_record(null::public.%1$I,$1)
      on conflict(%3$s) do update set %4$s returning to_jsonb(%1$I.*)',p_table,cols,keys,assignments) using r into result;
    saved:=saved||jsonb_build_array(result);
  end loop;
  return saved;
end $$;

revoke all on function public.mma_record_odds(jsonb,uuid,bigint),public.mma_write_import_rows(text,jsonb,uuid,bigint) from public,anon,authenticated;
grant execute on function public.mma_record_odds(jsonb,uuid,bigint),public.mma_write_import_rows(text,jsonb,uuid,bigint) to service_role;
revoke all on function public.mma_moneyline_snapshots(bigint[]) from public,anon;
grant execute on function public.mma_moneyline_snapshots(bigint[]) to authenticated,service_role;
revoke all on function public.mma_moneyline_snapshot_summary(bigint[]) from public,anon;
grant execute on function public.mma_moneyline_snapshot_summary(bigint[]) to authenticated,service_role;
create index if not exists mma_odds_observations_fresh_idx on public.mma_odds_observations(fight_id,observed_at desc);
notify pgrst,'reload schema';


-- 202610120034_atomic_tickets.sql

-- Legacy singles remain on fight_research. Each new single gets its own ticket.
alter table public.bet_tickets drop constraint if exists bet_tickets_ticket_type_check;
alter table public.bet_tickets add constraint bet_tickets_ticket_type_check check(ticket_type in ('single','parlay'));
alter table public.bet_tickets add column if not exists request_id uuid;
alter table public.bet_tickets add column if not exists revision integer not null default 1;
alter table public.bet_legs add column if not exists selected_fighter_id bigint references public.fighters(fighter_id);
create unique index if not exists bet_tickets_request_idx on public.bet_tickets(owner_id,request_id) where request_id is not null;

create or replace function public.mma_set_leg_identity() returns trigger language plpgsql set search_path=public,pg_temp as $$
declare expected bigint;
begin
  select case new.bet_side when 'fighter_a' then fighter_a_id when 'fighter_b' then fighter_b_id end into expected
    from public.fights where fight_id=new.fight_id;
  if expected is null then raise exception 'Ticket leg has no valid fighter'; end if;
  if new.selected_fighter_id is not null and new.selected_fighter_id<>expected then
    raise exception 'Ticket selection does not match its fighter'; end if;
  new.selected_fighter_id:=expected;
  return new;
end $$;
drop trigger if exists mma_set_leg_identity on public.bet_legs;
create trigger mma_set_leg_identity before insert or update on public.bet_legs for each row execute function public.mma_set_leg_identity();

create or replace function public.mma_ticket_revision() returns trigger language plpgsql as $$
begin
  new.revision:=old.revision+1;
  return new;
end $$;
drop trigger if exists mma_ticket_revision on public.bet_tickets;
create trigger mma_ticket_revision before update on public.bet_tickets for each row execute function public.mma_ticket_revision();

-- Invoker rights: every operation uses the existing owner policies, including legs.
create or replace function public.mma_save_ticket(p_ticket jsonb,p_legs jsonb,p_ticket_id bigint default null,p_revision integer default null)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare saved public.bet_tickets; leg jsonb; n integer; kind text:=p_ticket->>'ticket_type'; rid uuid;
begin
  if auth.uid() is null then raise exception 'Sign in before saving a ticket' using errcode='42501'; end if;
  if kind not in ('single','parlay') or nullif(trim(p_ticket->>'bet_sportsbook'),'') is null
    or jsonb_typeof(p_legs)<>'array' then raise exception 'Invalid ticket'; end if;
  n:=jsonb_array_length(p_legs);
  if (kind='single' and n<>1) or (kind='parlay' and (n<2 or n>30)) then raise exception 'Invalid ticket leg count'; end if;
  if (select count(distinct value->>'fight_id') from jsonb_array_elements(p_legs))<>n then raise exception 'Duplicate fight in ticket'; end if;
  if p_ticket_id is null then
    rid:=(p_ticket->>'request_id')::uuid;
    if rid is null then raise exception 'A retry identity is required'; end if;
    perform pg_advisory_xact_lock(hashtextextended(auth.uid()::text||':'||rid::text,0));
    select * into saved from public.bet_tickets where owner_id=auth.uid() and request_id=rid;
    if found then return to_jsonb(saved); end if;
    insert into public.bet_tickets(ticket_type,ticket_label,bet_sportsbook,ticket_price,stake_units,settlement_status,request_id)
      values(kind,coalesce(p_ticket->>'ticket_label',''),trim(p_ticket->>'bet_sportsbook'),(p_ticket->>'ticket_price')::integer,
        (p_ticket->>'stake_units')::numeric,coalesce(p_ticket->>'settlement_status','pending'),rid) returning * into saved;
  else
    select * into saved from public.bet_tickets where ticket_id=p_ticket_id and owner_id=auth.uid() for update;
    if not found then raise exception 'Ticket is unavailable' using errcode='42501'; end if;
    if saved.revision is distinct from p_revision then raise exception 'This ticket changed in another tab. Reload it before editing.' using errcode='40001'; end if;
    update public.bet_tickets set ticket_type=kind,ticket_label=coalesce(p_ticket->>'ticket_label',''),
      bet_sportsbook=trim(p_ticket->>'bet_sportsbook'),ticket_price=(p_ticket->>'ticket_price')::integer,
      stake_units=(p_ticket->>'stake_units')::numeric,settlement_status=coalesce(p_ticket->>'settlement_status','pending'),
      settled_at=case when coalesce(p_ticket->>'settlement_status','pending')='pending' then null else now() end,
      updated_at=now(),revision=revision+1 where ticket_id=p_ticket_id returning * into saved;
    delete from public.bet_legs where ticket_id=p_ticket_id;
  end if;
  n:=0;
  for leg in select value from jsonb_array_elements(p_legs) loop
    n:=n+1;
    insert into public.bet_legs(ticket_id,fight_id,bet_side,leg_price,leg_order)
      values(saved.ticket_id,(leg->>'fight_id')::bigint,leg->>'bet_side',(leg->>'leg_price')::integer,n);
  end loop;
  return to_jsonb(saved);
end $$;

create or replace function public.mma_archive_bet_period() returns timestamptz
language plpgsql security invoker set search_path=public,pg_temp as $$
declare stamp timestamptz:=now();
begin
  if auth.uid() is null then raise exception 'Sign in before archiving bets' using errcode='42501'; end if;
  update public.fight_research set bet_archived_at=stamp,updated_at=stamp
    where bet_archived_at is null and bet_side is not null and bet_price is not null and stake_units>0;
  update public.bet_tickets set archived_at=stamp,updated_at=stamp,revision=revision+1
    where owner_id=auth.uid() and archived_at is null;
  return stamp;
end $$;
revoke all on function public.mma_save_ticket(jsonb,jsonb,bigint,integer),public.mma_archive_bet_period() from public,anon;
grant execute on function public.mma_save_ticket(jsonb,jsonb,bigint,integer),public.mma_archive_bet_period() to authenticated;

alter table public.bet_tickets enable row level security;
alter table public.bet_legs enable row level security;
drop policy if exists dashboard_authenticated_read on public.bet_tickets;
drop policy if exists dashboard_authenticated_read on public.bet_legs;
revoke all on public.bet_tickets,public.bet_legs from anon;

-- Owned research becomes private; old unclaimed personal records remain usable.
-- No guess is made about the historical owner's account.
alter table public.fight_research enable row level security;
alter table public.event_research enable row level security;
revoke all on public.fight_research,public.event_research from anon;
alter table public.fight_research add column if not exists owner_id uuid;
alter table public.event_research add column if not exists owner_id uuid;
alter table public.fight_research alter column owner_id set default auth.uid();
alter table public.event_research alter column owner_id set default auth.uid();
create or replace function public.mma_claim_research_owner() returns trigger language plpgsql set search_path=public,pg_temp as $$
begin
  if auth.uid() is not null and new.owner_id is null then new.owner_id:=auth.uid(); end if;
  return new;
end $$;
do $$
declare t text; action text;
begin
  foreach t in array array['fight_research','event_research'] loop
    foreach action in array array['read','insert','update','delete'] loop
      execute format('drop policy if exists %I on public.%I','dashboard_authenticated_'||action,t);
      execute format('drop policy if exists %I on public.%I','research_owner_'||action,t);
    end loop;
    execute format('create policy research_owner_read on public.%I for select to authenticated using(owner_id=auth.uid() or owner_id is null)',t);
    execute format('create policy research_owner_insert on public.%I for insert to authenticated with check(owner_id=auth.uid())',t);
    execute format('create policy research_owner_update on public.%I for update to authenticated using(owner_id=auth.uid() or owner_id is null) with check(owner_id=auth.uid())',t);
    execute format('create policy research_owner_delete on public.%I for delete to authenticated using(owner_id=auth.uid() or owner_id is null)',t);
    execute format('drop trigger if exists mma_claim_research_owner on public.%I',t);
    execute format('create trigger mma_claim_research_owner before insert or update on public.%I for each row execute function public.mma_claim_research_owner()',t);
  end loop;
end $$;
notify pgrst,'reload schema';


-- 202610120035_discord_snapshot.sql

create or replace function public.mma_discord_snapshot(p_start date,p_end date,p_pending bigint[] default '{}')
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
begin
  if p_end<p_start or p_end-p_start>31 or cardinality(p_pending)>2000 then raise exception 'Invalid snapshot window'; end if;
  if not pg_try_advisory_xact_lock(hashtextextended('mma-import',0)) or exists(
    select 1 from public.mma_sync_leases where lease_name='imports' and expires_at>clock_timestamp()
  ) then raise exception 'Dashboard refresh is running; previous Discord snapshot retained' using errcode='55P03'; end if;
  return (
    with ev as (
      select e.*,to_jsonb(p) promotions from public.events e left join public.promotions p using(promotion_id)
        where e.event_date>=p_start and e.event_date<p_end or e.event_id=any(p_pending)
    ), fi as (
      select f.*,to_jsonb(a) fighter_a,to_jsonb(b) fighter_b,to_jsonb(w) weight_classes,to_jsonb(e) events
        from public.fights f join ev e using(event_id) left join public.fighters a on a.fighter_id=f.fighter_a_id
        left join public.fighters b on b.fighter_id=f.fighter_b_id
        left join public.weight_classes w using(weight_class_id) where f.event_id in(select event_id from ev)
    ), requested_tickets as (
      select distinct ticket_id from public.bet_legs where fight_id in(select fight_id from fi)
    ), legs as (
      select l.*,to_jsonb(f)||jsonb_build_object('fighter_a',to_jsonb(a),'fighter_b',to_jsonb(b),'events',to_jsonb(e)) fights
        from public.bet_legs l join public.fights f using(fight_id) join public.events e using(event_id)
        left join public.fighters a on a.fighter_id=f.fighter_a_id left join public.fighters b on b.fighter_id=f.fighter_b_id
        where l.ticket_id in(select ticket_id from requested_tickets)
    ), tickets as (
      select t.*,coalesce((select jsonb_agg(to_jsonb(l) order by l.leg_order) from legs l where l.ticket_id=t.ticket_id),'[]') bet_legs
        from public.bet_tickets t where t.ticket_id in(select ticket_id from requested_tickets)
    ), singles as (
      select r.*,to_jsonb(f) fights from public.fight_research r join fi f using(fight_id)
    )
    select jsonb_build_object(
      'events',coalesce((select jsonb_agg(to_jsonb(e)) from ev e),'[]'),
      'fights',coalesce((select jsonb_agg(to_jsonb(f)) from fi f),'[]'),
      'odds',coalesce((select jsonb_agg(to_jsonb(o)) from public.mma_moneyline_snapshots(array(select fight_id from fi)) o),'[]'),
      'external_ids',coalesce((select jsonb_agg(to_jsonb(x)) from public.external_ids x where x.entity_type='event' and x.internal_id in(select event_id from ev)),'[]'),
      'event_research',coalesce((select jsonb_agg(to_jsonb(r)) from public.event_research r where r.event_id in(select event_id from ev)),'[]'),
      'fight_research',coalesce((select jsonb_agg(to_jsonb(r)) from singles r),'[]'),
      'bet_legs',coalesce((select jsonb_agg(to_jsonb(l)) from legs l),'[]'),
      'bet_tickets',coalesce((select jsonb_agg(to_jsonb(t)) from tickets t),'[]'))
  );
end $$;

create table if not exists public.mma_discord_publishers(guild_id text primary key,holder uuid not null,expires_at timestamptz not null);
alter table public.mma_discord_publishers enable row level security;
revoke all on public.mma_discord_publishers from public,anon,authenticated;
grant all on public.mma_discord_publishers to service_role;
create or replace function public.mma_discord_publisher(p_guild text,p_holder uuid,p_action text)
returns boolean language plpgsql security definer set search_path=public,pg_temp as $$
declare owner public.mma_discord_publishers;
begin
  if p_guild !~ '^[0-9]{15,22}$' or p_holder is null then raise exception 'Invalid publisher'; end if;
  perform pg_advisory_xact_lock(hashtextextended('mma-discord:'||p_guild,0));
  select * into owner from public.mma_discord_publishers where guild_id=p_guild for update;
  if p_action='release' then
    delete from public.mma_discord_publishers where guild_id=p_guild and holder=p_holder; return true;
  end if;
  if p_action not in('claim','renew') then raise exception 'Invalid publisher action'; end if;
  if owner.guild_id is not null and owner.expires_at>clock_timestamp() and owner.holder<>p_holder then return false; end if;
  if p_action='renew' and (owner.guild_id is null or owner.holder<>p_holder or owner.expires_at<=clock_timestamp()) then return false; end if;
  insert into public.mma_discord_publishers values(p_guild,p_holder,clock_timestamp()+interval '180 seconds')
    on conflict(guild_id) do update set holder=excluded.holder,expires_at=excluded.expires_at;
  return true;
end $$;
revoke all on function public.mma_discord_snapshot(date,date,bigint[]),public.mma_discord_publisher(text,uuid,text) from public,anon,authenticated;
grant execute on function public.mma_discord_snapshot(date,date,bigint[]),public.mma_discord_publisher(text,uuid,text) to service_role;
notify pgrst,'reload schema';


commit;
