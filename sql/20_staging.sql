-- Typed rows, one per raw row, each tagged with the first rule it fails.
-- Nothing is filtered here, so raw = staged + quarantined always reconciles.
-- Rule order is part of the contract: duplicates are identified before any
-- value rule is applied.
create or replace table awards_ruled as
with typed as (
    select
        cast(id as varchar) as award_id,
        nullif(trim(reference_id), '') as reference_id,
        nullif(trim(contract_no), '') as contract_no,
        nullif(trim(award_title), '') as award_title,
        nullif(trim(notice_title), '') as notice_title,
        organization_name as agency_raw,
        awardee_name as supplier_raw,
        nullif(trim(area_of_delivery), '') as area_raw,
        business_category,
        contract_amount,
        cast(award_date as date) as award_date
    from raw_awards
),
hashed as not materialized (
    -- Every business column, so only byte-identical records share a hash.
    select
        *,
        md5(concat_ws(
            chr(31),
            coalesce(reference_id, ''),
            coalesce(contract_no, ''),
            coalesce(award_title, ''),
            coalesce(notice_title, ''),
            agency_raw,
            supplier_raw,
            coalesce(area_raw, ''),
            coalesce(business_category, ''),
            coalesce(cast(contract_amount as varchar), ''),
            coalesce(cast(award_date as varchar), '')
        )) as content_hash
    from typed
),
keepers as (
    -- The lowest id in each group of identical records is the one kept.
    select content_hash, min(award_id) as keep_id
    from hashed
    group by content_hash
),
flagged as (
    select
        h.*,
        a.agency_key,
        s.supplier_key,
        h.award_id <> k.keep_id as is_duplicate
    from hashed h
    join keepers k using (content_hash)
    join stg_agency_names a using (agency_raw)
    join stg_supplier_names s using (supplier_raw)
)
select
    f.*,
    case
        when is_duplicate then 'exact_duplicate'
        when award_date is null then 'missing_award_date'
        when award_date < cast(getvariable('earliest_award_date') as date)
            then 'award_date_before_2006'
        when award_date > cast(getvariable('snapshot_date') as date)
            then 'award_date_after_snapshot'
        when contract_amount is null or contract_amount < getvariable('min_amount')
            then 'amount_below_one_peso'
        when contract_amount > getvariable('large_amount')
             and not exists (
                 select 1 from large_amount_allowlist l where l.award_id = f.award_id
             )
            then 'amount_above_10bn_unreviewed'
        when agency_key = '' or supplier_key = ''
            then 'empty_name_after_normalisation'
    end as rule
from flagged f;
