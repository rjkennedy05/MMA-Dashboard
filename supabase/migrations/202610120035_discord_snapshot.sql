begin;
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
