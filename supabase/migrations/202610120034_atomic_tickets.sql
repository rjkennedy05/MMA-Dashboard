begin;
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
commit;
