do $$
declare
  dwcs_promotion_id bigint;
  dwcs_event_id bigint;
begin
  select promotion_id
  into dwcs_promotion_id
  from public.promotions
  where lower(name) in (
    'dwcs',
    'dana white contender series',
    'dana whites contender series',
    'dana white''s contender series'
  )
  limit 1;

  if dwcs_promotion_id is null then
    raise exception 'DWCS promotion row was not found.';
  end if;

  select event_id
  into dwcs_event_id
  from public.events
  where promotion_id = dwcs_promotion_id
    and event_date = '2026-08-11'
  order by event_id
  limit 1;

  if dwcs_event_id is null then
    insert into public.events (
      promotion_id,
      event_name,
      event_date,
      event_start_time,
      watch_platform,
      venue,
      city,
      state_region,
      country,
      event_status
    )
    values (
      dwcs_promotion_id,
      'Dana White''s Contender Series: Season 10, Week 1',
      '2026-08-11',
      '2026-08-12 00:00:00+00',
      'Paramount+',
      'Meta APEX',
      'Las Vegas',
      'Nevada',
      'United States',
      'upcoming'
    )
    returning event_id into dwcs_event_id;
  else
    update public.events
    set
      event_name = 'Dana White''s Contender Series: Season 10, Week 1',
      event_start_time = '2026-08-12 00:00:00+00',
      watch_platform = 'Paramount+',
      venue = 'Meta APEX',
      city = 'Las Vegas',
      state_region = 'Nevada',
      country = 'United States',
      event_status = 'upcoming',
      updated_at = now()
    where event_id = dwcs_event_id;
  end if;

  insert into public.fighters (
    first_name,
    last_name,
    full_name,
    status
  )
  select
    fighter.first_name,
    fighter.last_name,
    fighter.full_name,
    'active'
  from (
    values
      ('Jon', 'Kunneman', 'Jon Kunneman'),
      ('Joseph', 'Kropschot', 'Joseph Kropschot'),
      ('Thomas', 'Pagliarulo', 'Thomas Pagliarulo'),
      ('Ananias', 'Mulumba', 'Ananias Mulumba'),
      ('Bilal', 'Hasan', 'Bilal Hasan'),
      ('Mridul', 'Saikia', 'Mridul Saikia'),
      ('Anthony', 'Wint', 'Anthony Wint'),
      ('Matt', 'Adams', 'Matt Adams'),
      ('Abe', 'Alsaghir', 'Abe Alsaghir'),
      ('Fabrizio', 'Escarrega', 'Fabrizio Escarrega')
  ) as fighter(first_name, last_name, full_name)
  where not exists (
    select 1
    from public.fighters existing
    where lower(existing.full_name) = lower(fighter.full_name)
  );

  insert into public.fights (
    event_id,
    fighter_a_id,
    fighter_b_id,
    weight_class_id,
    scheduled_rounds,
    fight_order,
    fight_status,
    is_title_fight
  )
  select
    dwcs_event_id,
    fighter_a.fighter_id,
    fighter_b.fighter_id,
    weight_class.weight_class_id,
    3,
    matchup.fight_order,
    'scheduled',
    false
  from (
    values
      ('Jon Kunneman', 'Joseph Kropschot', 'Middleweight', 1),
      ('Anthony Wint', 'Matt Adams', 'Heavyweight', 2),
      ('Abe Alsaghir', 'Fabrizio Escarrega', 'Lightweight', 3),
      ('Thomas Pagliarulo', 'Ananias Mulumba', 'Featherweight', 4),
      ('Bilal Hasan', 'Mridul Saikia', 'Flyweight', 5)
  ) as matchup(fighter_a_name, fighter_b_name, weight_class_name, fight_order)
  join public.fighters fighter_a
    on lower(fighter_a.full_name) = lower(matchup.fighter_a_name)
  join public.fighters fighter_b
    on lower(fighter_b.full_name) = lower(matchup.fighter_b_name)
  join public.weight_classes weight_class
    on weight_class.name = matchup.weight_class_name
    and weight_class.gender = 'Men'
  where not exists (
    select 1
    from public.fights existing
    where existing.event_id = dwcs_event_id
      and (
        (
          existing.fighter_a_id = fighter_a.fighter_id
          and existing.fighter_b_id = fighter_b.fighter_id
        )
        or (
          existing.fighter_a_id = fighter_b.fighter_id
          and existing.fighter_b_id = fighter_a.fighter_id
        )
      )
  );
end
$$;
