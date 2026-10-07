create or replace table quarantine_awards as
select * exclude (is_duplicate)
from awards_ruled
where rule is not null;

-- A view, so the 5 million staged rows are stored once.
create or replace view stg_awards as
select * exclude (is_duplicate, rule)
from awards_ruled
where rule is null;

-- One row per award and delivery area. The source packs several provinces
-- into one comma-separated string.
create or replace table stg_award_areas as
with tokens as (
    select award_id, trim(unnest(string_split(area_raw, ','))) as token
    from stg_awards
    where area_raw is not null
)
select distinct
    t.award_id,
    t.token,
    nullif(s.canonical, '') as area_name,
    s.kind,
    s.token is not null as is_known
from tokens t
left join seed_areas s using (token);

-- Kept for the data-quality page: how much of each raw year is duplication.
create or replace table profile_duplicates_by_year as
select
    year(award_date) as award_year,
    count(*) as raw_rows,
    count(*) filter (where is_duplicate) as duplicate_rows,
    sum(contract_amount) as raw_value,
    coalesce(sum(contract_amount) filter (where is_duplicate), 0) as duplicate_value
from awards_ruled
group by 1;
