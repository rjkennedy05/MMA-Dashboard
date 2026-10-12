-- Protect side-based singles, parlay legs, research and saved analysis even
-- when an older importer writes directly. No historical rows are rewritten.
begin;

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

commit;
