-- Replaces the visible rating/narrative worksheet with compact, researched
-- matchup style and career finish facts. Older research columns remain intact
-- so this migration never deletes prior user work.

alter table public.fight_research
  add column if not exists fighter_a_style text not null default '',
  add column if not exists fighter_b_style text not null default '',
  add column if not exists fighter_a_record_summary text not null default '',
  add column if not exists fighter_b_record_summary text not null default '',
  add column if not exists fighter_a_ko_wins smallint null,
  add column if not exists fighter_a_submission_wins smallint null,
  add column if not exists fighter_b_ko_wins smallint null,
  add column if not exists fighter_b_submission_wins smallint null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'fight_research_nonnegative_finish_counts'
      and conrelid = 'public.fight_research'::regclass
  ) then
    alter table public.fight_research
      add constraint fight_research_nonnegative_finish_counts check (
        (fighter_a_ko_wins is null or fighter_a_ko_wins >= 0)
        and (fighter_a_submission_wins is null or fighter_a_submission_wins >= 0)
        and (fighter_b_ko_wins is null or fighter_b_ko_wins >= 0)
        and (fighter_b_submission_wins is null or fighter_b_submission_wins >= 0)
      );
  end if;
end $$;

comment on column public.fight_research.fighter_a_style is
  'Short researched style label, such as pressure wrestler or range striker.';
comment on column public.fight_research.fighter_a_ko_wins is
  'Career KO/TKO wins from saved analyst research, not an automatic provider statistic.';
