alter table public.odds
  add column if not exists sportsbook_key text null,
  add column if not exists market_commence_time timestamptz null;

update public.odds
set sportsbook_key = case sportsbook
  when 'BetMGM' then 'betmgm'
  when 'BetOnline.ag' then 'betonlineag'
  when 'BetRivers' then 'betrivers'
  when 'BetUS' then 'betus'
  when 'Bovada' then 'bovada'
  when 'DraftKings' then 'draftkings'
  when 'FanDuel' then 'fanduel'
  else sportsbook_key
end
where sportsbook_key is null;

create index if not exists odds_moneyline_history_idx
  on public.odds (
    fight_id,
    fighter_id,
    market_type,
    recorded_at desc
  );

comment on column public.odds.sportsbook_key is
  'Stable provider key for grouping a sportsbook across display-name changes.';

comment on column public.odds.market_commence_time is
  'Provider bout start attached to each snapshot; used to identify the final price tracked before the bout.';

notify pgrst, 'reload schema';
