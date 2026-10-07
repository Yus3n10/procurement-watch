-- Agencies are resolved by the folded key only. Display name is the most
-- frequent raw spelling, ties broken alphabetically so rebuilds are stable.
create or replace table core_agencies as
with variants as (
    select
        agency_key,
        agency_raw,
        count(*) as award_count,
        sum(contract_amount) as total_value,
        min(award_date) as first_award_date,
        max(award_date) as last_award_date
    from stg_awards
    group by agency_key, agency_raw
)
select
    substr(md5(agency_key), 1, 16) as agency_id,
    agency_key,
    first(agency_raw order by award_count desc, agency_raw) as agency_name,
    -- Local government units name themselves by level. Everything else is a
    -- national agency, school, hospital, corporation or water district.
    case
        when agency_key like 'BARANGAY %' then 'barangay'
        when agency_key like 'MUNICIPALITY %' or agency_key like 'MUNICIPAL GOVERNMENT %' then 'municipality'
        when agency_key like 'CITY OF %' or agency_key like 'CITY GOVERNMENT %' then 'city'
        when agency_key like 'PROVINCE OF %' or agency_key like 'PROVINCIAL GOVERNMENT %' then 'province'
        else 'national_or_other'
    end as agency_type,
    count(*) as name_variants,
    sum(award_count) as award_count,
    sum(total_value) as total_value,
    min(first_award_date) as first_award_date,
    max(last_award_date) as last_award_date
from variants
group by agency_key;

-- One row per raw supplier spelling, with the rule that decided its entity.
create or replace table core_supplier_aliases as
with variants as (
    select
        supplier_raw,
        supplier_key,
        count(*) as award_count,
        sum(contract_amount) as total_value
    from stg_awards
    group by supplier_raw, supplier_key
)
select
    v.supplier_raw,
    v.supplier_key,
    m.clean_key,
    m.match_key,
    substr(md5(m.match_key), 1, 16) as supplier_id,
    m.rule,
    v.award_count,
    v.total_value
from variants v
join stg_supplier_matches m using (supplier_key);

create or replace table core_suppliers as
select
    supplier_id,
    any_value(match_key) as match_key,
    -- Prefer the company's own spelling over one of its branches.
    first(supplier_raw order by contains(rule, 'branch_suffix'), award_count desc, supplier_raw)
        as supplier_name,
    count(*) as alias_count,
    sum(award_count) as award_count,
    sum(total_value) as total_value
from core_supplier_aliases
group by supplier_id;

create or replace table core_awards as
select
    s.award_id,
    a.agency_id,
    al.supplier_id,
    s.award_date,
    year(s.award_date) as award_year,
    s.contract_amount,
    s.business_category,
    s.reference_id
from stg_awards s
join core_agencies a using (agency_key)
join core_supplier_aliases al using (supplier_raw);

create or replace table core_award_areas as
select distinct award_id, area_name, kind
from stg_award_areas
where area_name is not null;

create or replace table analysis_amounts as
select cast(round_amount as bigint) as round_amount, amount_kind, note
from seed_analysis_amounts;

create or replace table core_thresholds as
select
    threshold,
    cast(amount as double) as amount,
    cast(effective_from as date) as effective_from,
    cast(effective_to as date) as effective_to,
    applies_to,
    legal_basis,
    source
from seed_thresholds;
