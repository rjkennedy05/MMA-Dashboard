-- Registers lightweight official schedule catalogs. These sources establish
-- whether an event exists; detailed card/result providers still own fights.
insert into public.data_sources (name)
select 'UFC Official Event Catalog'
where not exists (
  select 1 from public.data_sources
  where lower(trim(name)) = 'ufc official event catalog'
);

insert into public.data_sources (name)
select 'PFL Official Event Catalog'
where not exists (
  select 1 from public.data_sources
  where lower(trim(name)) = 'pfl official event catalog'
);

-- Repair the three catalog omissions that triggered this reliability pass.
-- These inserts are repeat-safe and do not replace an existing provider-owned
-- event. Detailed providers remain responsible for later card/result updates.
do $$
declare
  dwcs_promotion_id bigint;
  pfl_promotion_id bigint;
  dwcs_event_id bigint;
  pfl_mena_event_id bigint;
  pfl_africa_event_id bigint;
begin
  select promotion_id into dwcs_promotion_id
  from public.promotions
  where lower(trim(name)) in (
    'dwcs',
    'dana white contender series',
    'dana whites contender series',
    'dana white''s contender series'
  )
  order by promotion_id
  limit 1;

  select promotion_id into pfl_promotion_id
  from public.promotions
  where lower(trim(name)) in ('pfl', 'professional fighters league')
  order by promotion_id
  limit 1;

  if dwcs_promotion_id is null then
    raise exception 'DWCS promotion row was not found.';
  end if;
  if pfl_promotion_id is null then
    raise exception 'PFL promotion row was not found.';
  end if;

  select event_id into dwcs_event_id
  from public.events
  where promotion_id = dwcs_promotion_id
    and event_date = '2026-10-06'
    and lower(event_name) like '%contender series%week 9%'
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
    ) values (
      dwcs_promotion_id,
      'Dana White''s Contender Series: Season 10, Week 9',
      '2026-10-06',
      '2026-10-06 23:00:00+00',
      'Paramount+',
      'Meta APEX',
      'Las Vegas',
      'Nevada',
      'United States',
      case when current_date > date '2026-10-06' then 'completed' else 'upcoming' end
    )
    returning event_id into dwcs_event_id;
  end if;

  insert into public.fighters (first_name, last_name, full_name, status)
  select seed.first_name, seed.last_name, seed.full_name, 'active'
  from (
    values
      ('Summer', 'Onley', 'Summer Onley'),
      ('Alivia', 'Bierley', 'Alivia Bierley'),
      ('Salhahuddin', 'Everett', 'Salhahuddin Everett'),
      ('Ozzy', 'Martin', 'Ozzy Martin'),
      ('Roque', 'Conceicao', 'Roque Conceicao'),
      ('Alexander', 'Chavez', 'Alexander Chavez'),
      ('Ryuho', 'Miyaguchi', 'Ryuho Miyaguchi'),
      ('Mateus', 'Soares', 'Mateus Soares'),
      ('Preston', 'LaGrange', 'Preston LaGrange'),
      ('Nell', 'Ariano', 'Nell Ariano')
  ) as seed(first_name, last_name, full_name)
  where not exists (
    select 1 from public.fighters existing
    where lower(existing.full_name) = lower(seed.full_name)
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
      ('Summer Onley', 'Alivia Bierley', 'Bantamweight', 'Women', 1),
      ('Salhahuddin Everett', 'Ozzy Martin', 'Welterweight', 'Men', 2),
      ('Roque Conceicao', 'Alexander Chavez', 'Flyweight', 'Men', 3),
      ('Ryuho Miyaguchi', 'Mateus Soares', 'Bantamweight', 'Men', 4),
      ('Preston LaGrange', 'Nell Ariano', 'Light Heavyweight', 'Men', 5)
  ) as matchup(
    fighter_a_name,
    fighter_b_name,
    weight_class_name,
    fighter_gender,
    fight_order
  )
  join public.fighters fighter_a
    on lower(fighter_a.full_name) = lower(matchup.fighter_a_name)
  join public.fighters fighter_b
    on lower(fighter_b.full_name) = lower(matchup.fighter_b_name)
  left join public.weight_classes weight_class
    on weight_class.name = matchup.weight_class_name
    and weight_class.gender = matchup.fighter_gender
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

  insert into public.events (
    promotion_id,
    event_name,
    event_date,
    event_start_time,
    city,
    country,
    event_status
  )
  select
    pfl_promotion_id,
    'PFL MENA 11',
    '2026-10-02',
    '2026-10-02 14:00:00+00',
    'Riyadh',
    'Saudi Arabia',
    'completed'
  where not exists (
    select 1 from public.events
    where promotion_id = pfl_promotion_id
      and event_date = '2026-10-02'
      and lower(event_name) like '%pfl%mena%11%'
  );

  select event_id into pfl_mena_event_id
  from public.events
  where promotion_id = pfl_promotion_id
    and event_date = '2026-10-02'
    and lower(event_name) like '%pfl%mena%11%'
  order by event_id
  limit 1;

  insert into public.events (
    promotion_id,
    event_name,
    event_date,
    event_start_time,
    city,
    country,
    event_status
  )
  select
    pfl_promotion_id,
    'PFL Africa Morocco',
    '2026-10-10',
    '2026-10-10 17:00:00+00',
    'Casablanca',
    'Morocco',
    case when current_date > date '2026-10-10' then 'completed' else 'upcoming' end
  where not exists (
    select 1 from public.events
    where promotion_id = pfl_promotion_id
      and event_date = '2026-10-10'
      and lower(event_name) like '%pfl%africa%morocco%'
  );

  select event_id into pfl_africa_event_id
  from public.events
  where promotion_id = pfl_promotion_id
    and event_date = '2026-10-10'
    and lower(event_name) like '%pfl%africa%morocco%'
  order by event_id
  limit 1;

  insert into public.fighters (first_name, last_name, full_name, status)
  select seed.first_name, seed.last_name, seed.full_name, 'active'
  from (
    values
      ('Mostafa Rashed', 'Nada', 'Mostafa Rashed Nada'),
      ('Osama', 'ElSeady', 'Osama ElSeady'),
      ('Badreddine', 'Diani', 'Badreddine Diani'),
      ('Hazem', 'Kayyali', 'Hazem Kayyali'),
      ('Ylies', 'Djiroun', 'Ylies Djiroun'),
      ('Assem', 'Ghanem', 'Assem Ghanem'),
      ('Mehdi', 'Saadi', 'Mehdi Saadi'),
      ('Shadi', 'Kabbani', 'Shadi Kabbani'),
      ('Abdelkrim', 'Zouad', 'Abdelkrim Zouad'),
      ('Omar', 'Hussein', 'Omar Hussein'),
      ('Mohammad', 'Fahmi', 'Mohammad Fahmi'),
      ('Ahmed', 'El Sisy', 'Ahmed El Sisy'),
      ('Fatima', 'Al Ammari', 'Fatima Al Ammari'),
      ('Aya', 'Lounes', 'Aya Lounes'),
      ('Alridah', 'Alnemar', 'Alridah Alnemar'),
      ('Ali', 'Alshowakh', 'Ali Alshowakh'),
      ('Abdoulaye', 'Kane', 'Abdoulaye Kane'),
      ('Badr', 'Medkouri', 'Badr Medkouri'),
      ('Karim', 'Henniene', 'Karim Henniene'),
      ('Raphael', 'Uchegbu', 'Raphael Uchegbu'),
      ('Shido Boris', 'Esperanca', 'Shido Boris Esperanca'),
      ('Peace', 'Nguphane', 'Peace Nguphane'),
      ('Patrick', 'Ocheme', 'Patrick Ocheme'),
      ('Cornel', 'Thompson', 'Cornel Thompson'),
      ('Rivaldo', 'Pereira', 'Rivaldo Pereira'),
      ('David', 'Samuel', 'David Samuel'),
      ('Demba', 'Seck', 'Demba Seck'),
      ('Hussain', 'Al Kurdi', 'Hussain Al Kurdi'),
      ('Dwight', 'Joseph', 'Dwight Joseph'),
      ('Boule', 'Godogo', 'Boule Godogo')
  ) as seed(first_name, last_name, full_name)
  where not exists (
    select 1 from public.fighters existing
    where lower(existing.full_name) = lower(seed.full_name)
  );

  insert into public.fights (
    event_id,
    fighter_a_id,
    fighter_b_id,
    weight_class_id,
    scheduled_rounds,
    fight_order,
    fight_status,
    winner_id,
    result_type,
    method,
    finish_round,
    finish_time_seconds,
    is_title_fight
  )
  select
    pfl_mena_event_id,
    fighter_a.fighter_id,
    fighter_b.fighter_id,
    weight_class.weight_class_id,
    3,
    matchup.fight_order,
    'completed',
    fighter_a.fighter_id,
    'win',
    matchup.method,
    matchup.finish_round,
    matchup.finish_time_seconds,
    false
  from (
    values
      ('Mostafa Rashed Nada', 'Osama ElSeady', 'Light Heavyweight', 'Men', 1, 'Submission (Guillotine Choke)', 2, 153),
      ('Badreddine Diani', 'Hazem Kayyali', 'Welterweight', 'Men', 2, 'Submission (Arm Triangle)', 2, 185),
      ('Ylies Djiroun', 'Assem Ghanem', 'Lightweight', 'Men', 3, 'KO/TKO (Punches)', 1, 186),
      ('Mehdi Saadi', 'Shadi Kabbani', 'Featherweight', 'Men', 4, 'Decision - Split', 3, 300),
      ('Abdelkrim Zouad', 'Omar Hussein', 'Welterweight', 'Men', 5, 'Decision - Unanimous', 3, 300),
      ('Mohammad Fahmi', 'Ahmed El Sisy', 'Lightweight', 'Men', 6, 'Decision - Unanimous', 3, 300),
      ('Fatima Al Ammari', 'Aya Lounes', null, 'Women', 7, 'KO/TKO (Knees and Punches)', 2, 65),
      ('Alridah Alnemar', 'Ali Alshowakh', 'Bantamweight', 'Men', 8, 'Decision - Unanimous', 3, 300)
  ) as matchup(
    fighter_a_name,
    fighter_b_name,
    weight_class_name,
    fighter_gender,
    fight_order,
    method,
    finish_round,
    finish_time_seconds
  )
  join public.fighters fighter_a
    on lower(fighter_a.full_name) = lower(matchup.fighter_a_name)
  join public.fighters fighter_b
    on lower(fighter_b.full_name) = lower(matchup.fighter_b_name)
  left join public.weight_classes weight_class
    on weight_class.name = matchup.weight_class_name
    and weight_class.gender = matchup.fighter_gender
  where not exists (
    select 1
    from public.fights existing
    where existing.event_id = pfl_mena_event_id
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
    pfl_africa_event_id,
    fighter_a.fighter_id,
    fighter_b.fighter_id,
    weight_class.weight_class_id,
    3,
    matchup.fight_order,
    'scheduled',
    false
  from (
    values
      ('Abdoulaye Kane', 'Badr Medkouri', 'Heavyweight', 'Men', 1),
      ('Karim Henniene', 'Raphael Uchegbu', 'Bantamweight', 'Men', 2),
      ('Shido Boris Esperanca', 'Peace Nguphane', 'Welterweight', 'Men', 3),
      ('Patrick Ocheme', 'Cornel Thompson', 'Lightweight', 'Men', 4),
      ('Rivaldo Pereira', 'David Samuel', 'Welterweight', 'Men', 5),
      ('Demba Seck', 'Hussain Al Kurdi', 'Lightweight', 'Men', 6),
      ('Dwight Joseph', 'Boule Godogo', 'Bantamweight', 'Men', 7)
  ) as matchup(
    fighter_a_name,
    fighter_b_name,
    weight_class_name,
    fighter_gender,
    fight_order
  )
  join public.fighters fighter_a
    on lower(fighter_a.full_name) = lower(matchup.fighter_a_name)
  join public.fighters fighter_b
    on lower(fighter_b.full_name) = lower(matchup.fighter_b_name)
  left join public.weight_classes weight_class
    on weight_class.name = matchup.weight_class_name
    and weight_class.gender = matchup.fighter_gender
  where not exists (
    select 1
    from public.fights existing
    where existing.event_id = pfl_africa_event_id
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

notify pgrst, 'reload schema';
