-- Every figure here is a description of the published award records. A high
-- value marks a pattern worth a closer look. It is not evidence of wrongdoing.

-- ---------------------------------------------------------------------------
-- Pattern 1: bunching under round amounts
-- ---------------------------------------------------------------------------

-- An award is "under" an amount if it falls in [amount * (1 - w), amount] and
-- "over" if it falls in (amount, amount * (1 + w)]. An award exactly at the
-- amount counts as under, because every threshold reads "does not exceed".
create or replace temp table award_bands as
select
    a.award_id,
    a.agency_id,
    a.award_year,
    g.round_amount,
    a.contract_amount <= g.round_amount as is_under
from core_awards a
join analysis_amounts g
  on a.contract_amount >= g.round_amount * (1 - getvariable('band_width'))
 and a.contract_amount <= g.round_amount * (1 + getvariable('band_width'));

create or replace table mart_bunching_agency as
select
    agency_id,
    award_year,
    round_amount,
    count(*) filter (where is_under) as awards_under,
    count(*) filter (where not is_under) as awards_over,
    count(*) >= getvariable('min_band_awards') as enough_data
from award_bands
group by agency_id, award_year, round_amount;

create or replace table mart_bunching_national as
with counted as (
    select
        award_year,
        round_amount,
        sum(awards_under) as awards_under,
        sum(awards_over) as awards_over
    from mart_bunching_agency
    group by award_year, round_amount
),
labelled as (
    select
        c.*,
        c.awards_under / nullif(c.awards_over, 0) as under_over_ratio,
        g.amount_kind,
        -- Was a rule with this ceiling in force at any point in the year?
        exists (
            select 1 from core_thresholds t
            where t.amount = c.round_amount
              and year(t.effective_from) <= c.award_year
              and c.award_year <= year(coalesce(t.effective_to, cast(getvariable('snapshot_date') as date)))
        ) as in_force
    from counted c
    join analysis_amounts g using (round_amount)
),
baseline as (
    -- What bunching looks like under a round number with no rule attached.
    select award_year, median(under_over_ratio) as placebo_ratio
    from labelled
    where amount_kind = 'placebo'
    group by award_year
)
select
    l.*,
    b.placebo_ratio,
    l.under_over_ratio / b.placebo_ratio as excess_over_placebo
from labelled l
left join baseline b using (award_year);

-- ---------------------------------------------------------------------------
-- Pattern 2: the 2025 rule change
-- ---------------------------------------------------------------------------

create or replace table mart_rule_change_monthly as
select
    cast(date_trunc('month', a.award_date) as date) as award_month,
    count(*) as awards,
    count(*) filter (where b.round_amount = 1000000 and b.is_under) as under_1m,
    count(*) filter (where b.round_amount = 1000000 and not b.is_under) as over_1m,
    count(*) filter (where b.round_amount = 2000000 and b.is_under) as under_2m,
    count(*) filter (where b.round_amount = 2000000 and not b.is_under) as over_2m
from core_awards a
left join award_bands b
  on b.award_id = a.award_id and b.round_amount in (1000000, 2000000)
where a.award_year >= list_min(getvariable('rule_change_years')) - 1
group by 1;

-- The same calendar months in the year before and the year of the change, so
-- the comparison is not distorted by the yearly procurement cycle.
create or replace table mart_rule_change_summary as
select
    year(award_month) as award_year,
    sum(awards) as awards,
    sum(under_1m) as under_1m,
    sum(over_1m) as over_1m,
    sum(under_2m) as under_2m,
    sum(over_2m) as over_2m,
    sum(under_1m) / nullif(sum(over_1m), 0) as ratio_1m,
    sum(under_2m) / nullif(sum(over_2m), 0) as ratio_2m
from mart_rule_change_monthly
where list_contains(getvariable('rule_change_years'), year(award_month))
  and month(award_month) between getvariable('rule_change_first_month')
                             and getvariable('rule_change_last_month')
group by 1;

-- ---------------------------------------------------------------------------
-- Pattern 3: repeat same-day awards
-- ---------------------------------------------------------------------------

-- Same agency, same supplier, same day: several separate notices that each
-- stay within the small-value ceiling in force that day while their sum
-- exceeds it. Rows that share a reference id are lots of one notice and count
-- once. Rows without a reference id are left out, since separate notices
-- cannot be told apart from lots; that removes most of 2025.
create or replace table mart_same_day_groups as
with notices as (
    select
        agency_id,
        supplier_id,
        award_date,
        reference_id,
        sum(contract_amount) as notice_value
    from core_awards
    where reference_id is not null
    group by agency_id, supplier_id, award_date, reference_id
),
grouped as (
    select
        agency_id,
        supplier_id,
        award_date,
        count(*) as notices,
        sum(notice_value) as total_value,
        max(notice_value) as largest_notice
    from notices
    group by agency_id, supplier_id, award_date
)
select
    g.agency_id,
    g.supplier_id,
    g.award_date,
    year(g.award_date) as award_year,
    g.notices,
    g.total_value,
    g.largest_notice,
    t.amount as ceiling
from grouped g
join core_thresholds t
  on t.threshold = 'small_value_procurement'
 and g.award_date >= t.effective_from
 and g.award_date <= coalesce(t.effective_to, date '9999-12-31')
where g.notices >= getvariable('same_day_min_notices')
  and g.largest_notice <= t.amount
  and g.total_value > t.amount;

create or replace table mart_same_day_agency as
select
    agency_id,
    award_year,
    count(*) as groups,
    sum(notices) as notices,
    sum(total_value) as total_value
from mart_same_day_groups
group by agency_id, award_year;

-- ---------------------------------------------------------------------------
-- Pattern 4: supplier concentration
-- ---------------------------------------------------------------------------

create or replace table mart_supplier_concentration as
with by_supplier as (
    select agency_id, award_year, supplier_id, count(*) as awards, sum(contract_amount) as value
    from core_awards
    group by agency_id, award_year, supplier_id
),
shares as (
    select *, value / sum(value) over (partition by agency_id, award_year) as value_share
    from by_supplier
)
select
    agency_id,
    award_year,
    sum(awards) as awards,
    count(*) as suppliers,
    sum(value) as total_value,
    max(value_share) as top_supplier_share,
    -- Herfindahl index: 1 means a single supplier took everything.
    sum(value_share * value_share) as herfindahl,
    sum(awards) >= getvariable('min_agency_year_awards') as enough_data
from shares
group by agency_id, award_year;

-- ---------------------------------------------------------------------------
-- Rollups for the dashboard
-- ---------------------------------------------------------------------------

create or replace table mart_yearly as
select
    award_year,
    count(*) as awards,
    sum(contract_amount) as total_value,
    count(distinct agency_id) as agencies,
    count(distinct supplier_id) as suppliers,
    avg(cast(reference_id is not null as integer)) as share_with_reference_id
from core_awards
group by award_year;

create or replace table mart_agency_year as
select agency_id, award_year, count(*) as awards, sum(contract_amount) as total_value
from core_awards
group by agency_id, award_year;

-- An award delivered to several provinces is counted once in each, so these
-- rows do not add up to the national total.
create or replace table mart_area_year as
select ar.area_name, a.award_year, count(*) as awards, sum(a.contract_amount) as total_value
from core_awards a
join core_award_areas ar using (award_id)
group by ar.area_name, a.award_year;

create or replace table mart_area_agency as
select ar.area_name, a.agency_id, count(*) as awards, sum(a.contract_amount) as total_value
from core_awards a
join core_award_areas ar using (award_id)
group by ar.area_name, a.agency_id;
