-- Read-only findings. Do not merge/delete records from these results alone.
-- Run against the existing working project after migrations 031-035.

-- Duplicate event headers with the same promotion, title and day.
select promotion_id,event_date,lower(trim(event_name)) event_name,array_agg(event_id order by event_id) event_ids
from public.events group by promotion_id,event_date,lower(trim(event_name)) having count(*)>1;

-- Same stored opponents, event and sport: inspect source IDs and saved tickets.
select event_id,least(fighter_a_id,fighter_b_id) fighter_one,greatest(fighter_a_id,fighter_b_id) fighter_two,
  coalesce(ruleset,'MMA') ruleset,array_agg(fight_id order by fight_id) fight_ids
from public.fights group by event_id,least(fighter_a_id,fighter_b_id),greatest(fighter_a_id,fighter_b_id),coalesce(ruleset,'MMA')
having count(*)>1;

-- Ambiguous external identities, including retained aliases.
with identities as (
  select source_id,entity_type,external_id,internal_id from public.external_ids
  union select source_id,entity_type,external_id,internal_id from public.mma_external_aliases
)
select source_id,entity_type,external_id,array_agg(distinct internal_id) internal_ids
from identities group by source_id,entity_type,external_id having count(distinct internal_id)>1;

-- Invalid result identity needs review; do not guess the winner.
select fight_id,event_id,fighter_a_id,fighter_b_id,winner_id,fight_status
from public.fights where winner_id is not null and winner_id not in(fighter_a_id,fighter_b_id);

-- Legacy unclaimed research is preserved; an edit claims it to that account.
select 'fight_research' table_name,count(*) unclaimed from public.fight_research where owner_id is null
union all select 'event_research',count(*) from public.event_research where owner_id is null;
