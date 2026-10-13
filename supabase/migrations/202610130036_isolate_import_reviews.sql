-- Preserve each good bout/book while quarantining data conflicts in another.
-- Existing strict RPCs remain available; leases and infrastructure errors abort.
begin;
do $$
begin
  if to_regprocedure('public.mma_apply_import_batch(jsonb,uuid,bigint)') is null
    or to_regprocedure('public.mma_record_odds(jsonb,uuid,bigint)') is null
    or to_regclass('public.mma_odds_observations') is null
    or to_regprocedure('public.mma_discord_snapshot(date,date,bigint[])') is null then
    raise exception 'Apply the personal reliability upgrade through migration 035 before migration 036.';
  end if;
end $$;
create or replace function public.mma_apply_import_batch_resilient(
  p_operations jsonb,p_holder uuid default null,p_fence bigint default null
) returns jsonb language plpgsql set search_path=public,pg_temp as $$
declare
  part record; operation jsonb; payload jsonb; key text; existing_id bigint;
  prepared jsonb; saved jsonb; ids jsonb:='{}'; results jsonb:='[]'; failures jsonb:='[]';
  affected bigint[]:='{}'; states jsonb; message text; saved_ids jsonb;
begin
  perform public.mma_check_import_lease(p_holder,p_fence);
  if jsonb_typeof(p_operations) is distinct from 'array' or jsonb_array_length(p_operations)>500 then
    raise exception 'Invalid resilient import batch';
  end if;
  for part in
    select coalesce(value->>'bout_group','__card__') as group_id,
      jsonb_agg(value order by ordinality) as operations
    from jsonb_array_elements(p_operations) with ordinality
    group by coalesce(value->>'bout_group','__card__') order by min(ordinality)
  loop
    if part.group_id<>'__card__' and part.group_id !~ '^[0-9]{1,3}$' then
      raise exception 'Invalid bout group';
    end if;
    prepared:='[]';
    for operation in select value from jsonb_array_elements(part.operations) loop
      if part.group_id<>'__card__' and operation->>'p_entity_type'='event' then
        raise exception 'An event identity cannot be isolated as a bout';
      end if;
      payload:=operation->'p_payload';
      foreach key in array array['event_id','fighter_a_id','fighter_b_id','winner_id'] loop
        if payload ? key and ids ? (payload->>key) then
          payload:=jsonb_set(payload,array[key],ids->(payload->>key));
        end if;
      end loop;
      operation:=jsonb_set(operation,'{p_payload}',payload);
      existing_id:=(operation->>'p_existing_id')::bigint;
      if existing_id<0 and ids ? existing_id::text then
        operation:=jsonb_set(operation,'{p_existing_id}',ids->existing_id::text);
      end if;
      prepared:=prepared||jsonb_build_array(operation);
    end loop;
    begin
      saved:=public.mma_apply_import_batch(prepared,p_holder,p_fence);
    exception when integrity_constraint_violation or data_exception or raise_exception then
      if part.group_id='__card__' then raise; end if;
      get stacked diagnostics message=message_text;
      failures:=failures||jsonb_build_array(jsonb_build_object(
        'group',part.group_id,'code',sqlstate,'message',message));
      continue;
    end;
    ids:=ids||coalesce(saved->'ids','{}'::jsonb);
    results:=results||coalesce(saved->'results','[]'::jsonb);
    for saved_ids in select value from jsonb_array_elements(saved->'results') loop
      if (saved_ids->'row') ? 'event_name' then
        affected:=array_append(affected,(saved_ids->>'internal_id')::bigint);
      end if;
    end loop;
  end loop;
  -- Recompute after all successful groups. Dates never create results.
  with card as (
    select event_id,count(*) n,bool_or(fight_status in ('live','in_progress')) live,
      bool_and(coalesce(fight_status,'unknown') in ('draw','no_contest','cancelled')
        or (coalesce(fight_status,'unknown')='completed' and winner_id is not null)) final
    from public.fights where event_id=any(affected) group by event_id
  ), phase as (
    select e.event_id,case when e.event_status in ('cancelled','canceled') then e.event_status
      when coalesce(c.live,false) then 'live' when c.n>0 and coalesce(c.final,false) then 'completed'
      when e.event_status='completed' then 'unknown' else e.event_status end event_status
    from public.events e left join card c using(event_id) where e.event_id=any(affected)
  ) update public.events e set event_status=p.event_status from phase p where e.event_id=p.event_id;
  select coalesce(jsonb_object_agg(event_id::text,event_status),'{}') into states
    from public.events where event_id=any(affected);
  return jsonb_build_object('ids',ids,'results',results,'event_states',states,'failed_groups',failures);
end $$;

create or replace function public.mma_record_odds_resilient(
  p_rows jsonb,p_holder uuid default null,p_fence bigint default null
) returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare part record; saved jsonb; inserted integer:=0; unchanged integer:=0; skipped integer:=0;
  failures jsonb:='[]'; message text;
begin
  perform public.mma_check_import_lease(p_holder,p_fence);
  if jsonb_typeof(p_rows) is distinct from 'array' or jsonb_array_length(p_rows)>2000 then raise exception 'Invalid odds batch'; end if;
  for part in select value->>'fight_id' fight_id,value->>'sportsbook_key' book,value->>'source_id' source_id,
      jsonb_agg(value order by ordinality) as quotes
    from jsonb_array_elements(p_rows) with ordinality
    group by value->>'fight_id',value->>'sportsbook_key',value->>'source_id' order by min(ordinality)
  loop
    begin
      if jsonb_array_length(part.quotes)<>2
        or (select count(distinct value->>'fighter_id') from jsonb_array_elements(part.quotes))<>2 then
        raise exception 'A sportsbook moneyline must contain one price for each participant';
      end if;
      -- An older response must not refresh just one side of a newer pair.
      if exists(select 1 from jsonb_array_elements(part.quotes) quote
        join public.mma_odds_observations previous
          on previous.fight_id=(quote->>'fight_id')::bigint
          and previous.fighter_id=(quote->>'fighter_id')::bigint
          and previous.sportsbook_key=quote->>'sportsbook_key'
        where previous.provider_updated_at>nullif(quote->>'provider_updated_at','')::timestamptz) then
        skipped:=skipped+2;
        continue;
      end if;
      saved:=public.mma_record_odds(part.quotes,p_holder,p_fence);
    exception when integrity_constraint_violation or data_exception or no_data_found or raise_exception then
      get stacked diagnostics message=message_text;
      failures:=failures||jsonb_build_array(jsonb_build_object('fight_id',part.fight_id,
        'sportsbook_key',part.book,'message',message,'code',sqlstate));
      skipped:=skipped+jsonb_array_length(part.quotes);
      continue;
    end;
    inserted:=inserted+coalesce((saved->>'inserted')::integer,0);
    unchanged:=unchanged+coalesce((saved->>'unchanged')::integer,0);
    skipped:=skipped+coalesce((saved->>'skipped')::integer,0);
  end loop;
  return jsonb_build_object('inserted',inserted,'unchanged',unchanged,'skipped',skipped,'errors',failures);
end $$;
revoke all on function public.mma_apply_import_batch_resilient(jsonb,uuid,bigint),
  public.mma_record_odds_resilient(jsonb,uuid,bigint) from public,anon,authenticated;
grant execute on function public.mma_apply_import_batch_resilient(jsonb,uuid,bigint),
  public.mma_record_odds_resilient(jsonb,uuid,bigint) to service_role;
notify pgrst,'reload schema';
commit;
