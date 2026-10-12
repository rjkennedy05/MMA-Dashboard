-- Optional full rollback of migration 031. Removes the guard, not user data.
-- Older dashboard versions can also run with the guard left in place.
begin;
drop trigger if exists protect_mma_fight_identity on public.fights;
drop function if exists public.protect_mma_fight_identity();
commit;
