-- Service-only leases and atomic provider writes. Existing records are retained.
begin;

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
commit;
