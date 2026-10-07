"""Write the small pre-aggregated files the static site reads.

Nothing here identifies a supplier. Patterns are published per agency only:
agencies are public bodies, suppliers are often small businesses.
"""

import json
from pathlib import Path

from . import config

MIN_AGENCY_AWARDS = 100
TOP_AGENCIES_PER_PATTERN = 50
PATTERN_YEARS = 8
FOCUS_AREA = "Negros Occidental"
# The overview histogram: awards in 1% steps from 20% below to 20% above an
# amount, for the ceiling and for a placebo amount beside it.
CLIFF_AMOUNTS = (1_000_000, 1_500_000)
CLIFF_SPAN = 20

CLIFF_SQL = """
select
    cast(ceil((contract_amount - ?) / (? / 100.0)) as integer) - 1 as step,
    count(*) as awards
from core_awards
where award_year = ?
  and contract_amount > ? * (1 - {span} / 100.0)
  and contract_amount <= ? * (1 + {span} / 100.0)
group by 1
order by 1
"""


def _rows(con, sql: str, params=None) -> list[dict]:
    cursor = con.execute(sql, params or [])
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _columnar(con, sql: str) -> dict:
    """Column arrays instead of row objects: about a third of the size."""
    cursor = con.execute(sql)
    columns = [column[0] for column in cursor.description]
    data = cursor.fetchall()
    return {column: [row[index] for row in data] for index, column in enumerate(columns)}


def _write(site_data: Path, name: str, payload) -> None:
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    (site_data / name).write_text(text + "\n", encoding="utf-8")


def _cliff(con, year: int) -> dict:
    """Awards per 1% step. Each step is open below and closed above, so step -1
    ends exactly at the amount: a ceiling reads "does not exceed"."""
    cliffs = {}
    for amount in CLIFF_AMOUNTS:
        counts = dict(con.execute(CLIFF_SQL.format(span=CLIFF_SPAN), [amount, amount, year, amount, amount]).fetchall())
        cliffs[str(amount)] = [
            {"step": step, "awards": counts.get(step, 0)} for step in range(-CLIFF_SPAN, CLIFF_SPAN)
        ]
    return {"year": year, "span": CLIFF_SPAN, "amounts": cliffs}


AGENCY_YEAR_SQL = """
select
    y.agency_id,
    y.award_year,
    y.awards,
    round(y.total_value) as total_value,
    round(c.top_supplier_share, 4) as top_supplier_share,
    round(c.herfindahl, 4) as herfindahl,
    c.suppliers,
    coalesce(b.awards_under, 0) as under_1m,
    coalesce(b.awards_over, 0) as over_1m,
    coalesce(s.groups, 0) as same_day_groups,
    round(coalesce(s.total_value, 0)) as same_day_value
from mart_agency_year y
join core_agencies a using (agency_id)
join mart_supplier_concentration c using (agency_id, award_year)
left join mart_bunching_agency b
  on b.agency_id = y.agency_id and b.award_year = y.award_year and b.round_amount = 1000000
left join mart_same_day_agency s
  on s.agency_id = y.agency_id and s.award_year = y.award_year
where a.award_count >= {min_awards}
order by y.agency_id, y.award_year
"""

PATTERN_RANKINGS = {
    # pattern name -> (measure expression, filter)
    "bunching_1m": ("b.awards_under", "b.enough_data"),
    "same_day": ("s.groups", "s.groups > 0"),
    "concentration": ("c.top_supplier_share", "c.enough_data"),
}

PATTERN_SQL = """
select
    a.agency_id,
    a.agency_name,
    a.agency_type,
    c.awards,
    round(c.total_value) as total_value,
    coalesce(b.awards_under, 0) as under_1m,
    coalesce(b.awards_over, 0) as over_1m,
    coalesce(s.groups, 0) as same_day_groups,
    round(coalesce(s.total_value, 0)) as same_day_value,
    round(c.top_supplier_share, 4) as top_supplier_share,
    c.suppliers
from mart_supplier_concentration c
join core_agencies a using (agency_id)
left join mart_bunching_agency b
  on b.agency_id = c.agency_id and b.award_year = c.award_year and b.round_amount = 1000000
left join mart_same_day_agency s
  on s.agency_id = c.agency_id and s.award_year = c.award_year
where c.award_year = ? and {where}
order by {measure} desc, a.agency_name
limit {limit}
"""


def export(con, report: dict, matching_report: dict | None, site_data: Path) -> dict:
    """Write every site data file and return a manifest of names and sizes."""
    site_data.mkdir(parents=True, exist_ok=True)
    for stale in site_data.glob("*.json"):
        stale.unlink()

    years = [row[0] for row in con.execute("select award_year from mart_yearly order by 1").fetchall()]

    _write(
        site_data,
        "summary.json",
        {
            "snapshot_date": report["snapshot_date"],
            "source": config.load_manifest()["source"],
            "revision": config.load_manifest()["revision"],
            "counts": report["summary"],
            "checks": report["checks"],
            "publishable": report["publishable"],
            "matching": matching_report,
            "settings": {
                "band_width": config.BAND_WIDTH,
                "min_band_awards": config.MIN_BAND_AWARDS,
                "min_agency_year_awards": config.MIN_AGENCY_YEAR_AWARDS,
                "same_day_min_notices": config.SAME_DAY_MIN_NOTICES,
                "min_agency_awards_listed": MIN_AGENCY_AWARDS,
                "focus_area": FOCUS_AREA,
            },
            "duplicates_by_year": _rows(
                con,
                "select award_year, raw_rows, duplicate_rows, round(raw_value) as raw_value, "
                "round(duplicate_value) as duplicate_value from profile_duplicates_by_year "
                "where award_year is not null order by 1",
            ),
            "thresholds": _rows(con, "select * from core_thresholds order by threshold, effective_from"),
            "amounts": _rows(con, "select * from analysis_amounts order by round_amount"),
        },
    )
    _write(
        site_data,
        "yearly.json",
        _rows(
            con,
            "select award_year, awards, round(total_value) as total_value, agencies, suppliers, "
            "round(share_with_reference_id, 4) as share_with_reference_id from mart_yearly order by 1",
        ),
    )
    _write(
        site_data,
        "bunching.json",
        _rows(
            con,
            "select award_year, round_amount, amount_kind, in_force, awards_under, awards_over, "
            "round(under_over_ratio, 3) as ratio, round(placebo_ratio, 3) as placebo_ratio, "
            "round(excess_over_placebo, 3) as excess from mart_bunching_national order by 1, 2",
        ),
    )
    snapshot_year = int(report["snapshot_date"][:4])
    complete_years = [year for year in years if year < snapshot_year - 1] or years
    _write(site_data, "cliff.json", _cliff(con, complete_years[-1]))
    _write(
        site_data,
        "bunching_by_type.json",
        _rows(
            con,
            "select b.award_year, a.agency_type, sum(b.awards_under) as awards_under, "
            "sum(b.awards_over) as awards_over from mart_bunching_agency b "
            "join core_agencies a using (agency_id) where b.round_amount = 1000000 "
            "group by 1, 2 order by 1, 2",
        ),
    )
    _write(
        site_data,
        "rule_change.json",
        {
            "monthly": _rows(con, "select * from mart_rule_change_monthly order by award_month"),
            "summary": _rows(con, "select * from mart_rule_change_summary order by award_year"),
        },
    )
    _write(
        site_data,
        "same_day.json",
        _rows(
            con,
            "select award_year, count(*) as groups, sum(notices) as notices, "
            "round(sum(total_value)) as total_value, count(distinct agency_id) as agencies "
            "from mart_same_day_groups group by 1 order by 1",
        ),
    )
    _write(
        site_data,
        "concentration.json",
        _rows(
            con,
            "select award_year, count(*) as agencies, "
            "round(quantile_cont(top_supplier_share, 0.25), 4) as p25, "
            "round(median(top_supplier_share), 4) as median, "
            "round(quantile_cont(top_supplier_share, 0.75), 4) as p75, "
            "round(quantile_cont(top_supplier_share, 0.9), 4) as p90, "
            "count(*) filter (where top_supplier_share > 0.5) as above_half "
            "from mart_supplier_concentration where enough_data group by 1 order by 1",
        ),
    )

    _write(
        site_data,
        "agencies.json",
        _columnar(
            con,
            f"""
            select a.agency_id, a.agency_name, a.agency_type, a.award_count as awards,
                   round(a.total_value) as total_value, year(a.first_award_date) as first_year,
                   year(a.last_award_date) as last_year,
                   (select first(m.area_name order by m.awards desc, m.area_name)
                    from mart_area_agency m where m.agency_id = a.agency_id) as main_area
            from core_agencies a
            where a.award_count >= {MIN_AGENCY_AWARDS}
            order by a.award_count desc, a.agency_name
            """,
        ),
    )
    _write(site_data, "agency_years.json", _columnar(con, AGENCY_YEAR_SQL.format(min_awards=MIN_AGENCY_AWARDS)))

    patterns = {}
    for year in years[-PATTERN_YEARS:]:
        patterns[str(year)] = {
            name: _rows(
                con,
                PATTERN_SQL.format(measure=measure, where=where, limit=TOP_AGENCIES_PER_PATTERN),
                [year],
            )
            for name, (measure, where) in PATTERN_RANKINGS.items()
        }
    _write(site_data, "patterns.json", patterns)

    _write(
        site_data,
        "focus_area.json",
        {
            "area": FOCUS_AREA,
            "yearly": _rows(
                con,
                "select award_year, awards, round(total_value) as total_value from mart_area_year "
                "where area_name = ? order by 1",
                [FOCUS_AREA],
            ),
            "agencies": _rows(
                con,
                "select a.agency_id, a.agency_name, a.agency_type, m.awards, "
                "round(m.total_value) as total_value from mart_area_agency m "
                "join core_agencies a using (agency_id) where m.area_name = ? "
                "order by m.total_value desc, a.agency_name limit 50",
                [FOCUS_AREA],
            ),
            "by_type": _rows(
                con,
                "select a.agency_type, sum(m.awards) as awards, round(sum(m.total_value)) as total_value "
                "from mart_area_agency m join core_agencies a using (agency_id) "
                "where m.area_name = ? group by 1 order by 3 desc",
                [FOCUS_AREA],
            ),
        },
    )

    manifest = {path.name: path.stat().st_size for path in sorted(site_data.glob("*.json"))}
    return manifest
