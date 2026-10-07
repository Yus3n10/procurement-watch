"""Data-quality checks. Each query returns the number of violating rows."""

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Check:
    name: str
    severity: str  # "error" blocks publishing, "warn" is reported
    description: str
    sql: str


CHECKS = [
    Check(
        "row_counts_reconcile",
        "error",
        "Every raw row is either in staging or in quarantine, per year.",
        """
        with raw as (select year(cast(award_date as date)) y, count(*) n from raw_awards group by 1),
             kept as (select year(award_date) y, count(*) n from stg_awards group by 1),
             held as (select year(award_date) y, count(*) n from quarantine_awards group by 1)
        select count(*) from raw
        left join kept on raw.y is not distinct from kept.y
        left join held on raw.y is not distinct from held.y
        where raw.n <> coalesce(kept.n, 0) + coalesce(held.n, 0)
        """,
    ),
    Check(
        "award_id_unique",
        "error",
        "No award id appears twice in staging.",
        "select count(*) from (select award_id from stg_awards group by 1 having count(*) > 1)",
    ),
    Check(
        "no_exact_duplicates",
        "error",
        "No two staged awards are identical in every business column.",
        "select count(*) from (select content_hash from stg_awards group by 1 having count(*) > 1)",
    ),
    Check(
        "award_date_in_range",
        "error",
        "Award dates fall between 2006-01-01 and the snapshot date.",
        """
        select count(*) from stg_awards
        where award_date is null
           or award_date < cast(getvariable('earliest_award_date') as date)
           or award_date > cast(getvariable('snapshot_date') as date)
        """,
    ),
    Check(
        "amount_in_range",
        "error",
        "Amounts are at least 1 peso, and above 10 billion only if reviewed.",
        """
        select count(*) from stg_awards
        where contract_amount < getvariable('min_amount')
           or (contract_amount > getvariable('large_amount')
               and award_id not in (select award_id from large_amount_allowlist))
        """,
    ),
    Check(
        "name_keys_are_ascii",
        "error",
        "Agency and supplier keys contain only ASCII characters.",
        r"""
        select
            (select count(*) from stg_agency_names where regexp_matches(agency_key, '[^\x20-\x7E]'))
          + (select count(*) from stg_supplier_names where regexp_matches(supplier_key, '[^\x20-\x7E]'))
        """,
    ),
    Check(
        "name_keys_are_lossless",
        "error",
        "No name lost a letter that the fold could not map to ASCII.",
        """
        select
            (select count(*) from stg_agency_names where letters_dropped > 0)
          + (select count(*) from stg_supplier_names where letters_dropped > 0)
        """,
    ),
    Check(
        "names_present",
        "error",
        "Every staged award has a non-empty agency key and supplier key.",
        """
        select count(*) from stg_awards
        where agency_key is null or agency_key = '' or supplier_key is null or supplier_key = ''
        """,
    ),
    Check(
        "area_tokens_known",
        "error",
        "Every delivery-area token is listed in seeds/areas.csv.",
        "select count(distinct token) from stg_award_areas where not is_known",
    ),
    Check(
        "yearly_value_within_tolerance",
        "error",
        f"From {config.YOY_FIRST_YEAR}, each complete year's total value is "
        f"{config.YOY_MIN_RATIO} to {config.YOY_MAX_RATIO} times the previous year's.",
        f"""
        with yearly as (
            select year(award_date) y, sum(contract_amount) v from stg_awards group by 1
        ), compared as (
            select y, v / lag(v) over (order by y) as ratio from yearly
        )
        select count(*) from compared
        where y >= {config.YOY_FIRST_YEAR}
          and y < year(cast(getvariable('snapshot_date') as date))
          and (ratio < {config.YOY_MIN_RATIO} or ratio > {config.YOY_MAX_RATIO})
        """,
    ),
    Check(
        "core_awards_complete",
        "error",
        "Every staged award appears once in core with an agency and a supplier.",
        """
        select abs((select count(*) from stg_awards) - (select count(*) from core_awards))
             + (select count(*) from core_awards where agency_id is null or supplier_id is null)
             + (select count(*) from (select award_id from core_awards group by 1 having count(*) > 1))
        """,
    ),
    Check(
        "entity_ids_unique",
        "error",
        "No two agency keys or supplier match keys share an id.",
        """
        select
            (select count(*) from (select agency_id from core_agencies group by 1 having count(*) > 1))
          + (select count(*) from (
                select supplier_id from core_supplier_aliases group by 1 having count(distinct match_key) > 1))
        """,
    ),
    Check(
        "alias_maps_to_one_supplier",
        "error",
        "Each raw supplier spelling belongs to exactly one supplier.",
        "select count(*) from (select supplier_raw from core_supplier_aliases group by 1 having count(*) > 1)",
    ),
    Check(
        "core_value_matches_staging",
        "error",
        "Total awarded value is unchanged between staging and core.",
        """
        with totals as (
            select
                (select coalesce(fsum(contract_amount), 0) from stg_awards) as staged,
                (select coalesce(fsum(contract_amount), 0) from core_awards) as core
        )
        select cast(abs(staged - core) > 1e-9 * greatest(staged, 1) as integer) from totals
        """,
    ),
    Check(
        "thresholds_do_not_overlap",
        "error",
        "No threshold has two amounts in force on the same day.",
        """
        select count(*) from core_thresholds a
        join core_thresholds b
          on a.threshold = b.threshold and a.effective_from < b.effective_from
         and coalesce(a.effective_to, date '9999-12-31') >= b.effective_from
        """,
    ),
    Check(
        "marts_reconcile_to_core",
        "error",
        "Yearly and agency-year rollups add up to the core award count and value.",
        """
        with core as (select count(*) n, coalesce(fsum(contract_amount), 0) v from core_awards),
             rollups as (
                 select 'yearly' src, sum(awards) n, coalesce(fsum(total_value), 0) v from mart_yearly
                 union all
                 select 'agency_year', sum(awards), coalesce(fsum(total_value), 0) from mart_agency_year
                 union all
                 select 'concentration', sum(awards), coalesce(fsum(total_value), 0)
                 from mart_supplier_concentration
             )
        select count(*) from rollups, core
        where rollups.n is distinct from core.n
           or abs(rollups.v - core.v) > 1e-9 * greatest(core.v, 1)
        """,
    ),
    Check(
        "bunching_counts_match_core",
        "error",
        "Bunching band counts equal a direct count of core awards in each band.",
        """
        with direct as (
            select a.award_year, g.round_amount,
                   count(*) filter (where a.contract_amount <= g.round_amount) under_n,
                   count(*) filter (where a.contract_amount > g.round_amount) over_n
            from core_awards a
            join analysis_amounts g
              on a.contract_amount >= g.round_amount * (1 - getvariable('band_width'))
             and a.contract_amount <= g.round_amount * (1 + getvariable('band_width'))
            group by 1, 2
        )
        select count(*) from direct d
        full join mart_bunching_national m using (award_year, round_amount)
        where d.under_n is distinct from m.awards_under or d.over_n is distinct from m.awards_over
        """,
    ),
    Check(
        "concentration_shares_valid",
        "error",
        "Top-supplier share and Herfindahl index lie between 0 and 1, and the index never exceeds the share.",
        """
        select count(*) from mart_supplier_concentration
        where top_supplier_share <= 0 or top_supplier_share > 1 + 1e-9
           or herfindahl <= 0 or herfindahl > top_supplier_share + 1e-9
        """,
    ),
    Check(
        "same_day_groups_meet_definition",
        "error",
        "Every same-day group has enough notices, each within the ceiling, summing above it.",
        """
        select count(*) from mart_same_day_groups
        where notices < getvariable('same_day_min_notices')
           or largest_notice > ceiling
           or total_value <= ceiling
        """,
    ),
    Check(
        "analysis_amounts_consistent",
        "error",
        "Every ceiling on file is analysed as a threshold, and at least three placebo amounts exist.",
        """
        select
            (select count(*) from core_thresholds t
             where not exists (
                 select 1 from analysis_amounts g
                 where g.round_amount = t.amount and g.amount_kind = 'threshold'))
          + cast((select count(*) from analysis_amounts where amount_kind = 'placebo') < 3 as integer)
          + (select count(*) from analysis_amounts
             where amount_kind not in ('threshold', 'placebo', 'other_rule'))
        """,
    ),
    Check(
        "raw_duplicate_value_share",
        "warn",
        f"No raw year has more than {config.DUPLICATE_VALUE_SHARE_WARN:.0%} of its value in duplicates.",
        f"""
        select count(*) from profile_duplicates_by_year
        where award_year is not null and raw_value > 0
          and duplicate_value / raw_value > {config.DUPLICATE_VALUE_SHARE_WARN}
        """,
    ),
]


def run_checks(con) -> list[dict]:
    results = []
    for check in CHECKS:
        violations = con.execute(check.sql).fetchone()[0]
        results.append(
            {
                "name": check.name,
                "severity": check.severity,
                "description": check.description,
                "violations": int(violations),
                "passed": violations == 0,
            }
        )
    return results


def blocking_failures(results: list[dict]) -> list[dict]:
    return [r for r in results if r["severity"] == "error" and not r["passed"]]
