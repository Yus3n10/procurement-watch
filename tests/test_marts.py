import duckdb
import pytest

from pw import checks, pipeline

from conftest import award


def query(settings, sql):
    con = duckdb.connect(str(settings.warehouse), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def awards(specs):
    """Build distinct awards from (overrides) dicts, each with its own reference id."""
    return [award(i, **{"reference_id": str(i), "contract_no": str(i), **spec}) for i, spec in enumerate(specs, 1)]


def test_bunching_counts_under_at_and_over_an_amount(make_settings):
    settings = make_settings(
        awards(
            [
                {"contract_amount": 950_000.0},
                {"contract_amount": 1_000_000.0},  # exactly at the ceiling counts as under
                {"contract_amount": 1_000_000.01},
                {"contract_amount": 1_100_001.0},  # outside the band
                {"contract_amount": 899_999.0},  # outside the band
            ]
        )
    )
    report = pipeline.build(settings)
    assert report["publishable"]
    assert query(
        settings,
        "select award_year, awards_under, awards_over, under_over_ratio, amount_kind, in_force "
        "from mart_bunching_national where round_amount = 1000000",
    ) == [(2024, 2, 1, 2.0, "threshold", True)]


def test_bunching_marks_placebo_amounts_and_rules_not_yet_in_force(make_settings):
    settings = make_settings(
        awards(
            [
                {"contract_amount": 490_000.0},
                {"contract_amount": 510_000.0},
                {"contract_amount": 1_950_000.0},
                {"contract_amount": 2_050_000.0, "award_date": "2025-06-01"},
                {"contract_amount": 1_950_000.0, "award_date": "2025-06-01"},
                {"contract_amount": 195_000.0, "award_date": "2025-01-10"},
                {"contract_amount": 195_000.0, "award_date": "2026-01-02"},
            ]
        )
    )
    pipeline.build(settings)
    assert query(
        settings,
        "select award_year, round_amount, amount_kind, in_force from mart_bunching_national "
        "where round_amount in (200000, 500000, 2000000) order by 1, 2",
    ) == [
        (2024, 500000, "placebo", False),
        (2024, 2000000, "threshold", False),
        (2025, 200000, "threshold", True),
        (2025, 2000000, "threshold", True),
        (2026, 200000, "threshold", False),  # repealed during 2025
    ]


def test_excess_is_the_ratio_divided_by_the_median_placebo_ratio(make_settings):
    specs = []
    specs += [{"contract_amount": 95_000.0}] * 2 + [{"contract_amount": 105_000.0}]  # placebo ratio 2
    specs += [{"contract_amount": 290_000.0}] * 4 + [{"contract_amount": 310_000.0}]  # placebo ratio 4
    specs += [{"contract_amount": 480_000.0}] * 9 + [{"contract_amount": 520_000.0}]  # placebo ratio 9
    specs += [{"contract_amount": 990_000.0}] * 8 + [{"contract_amount": 1_010_000.0}]  # threshold ratio 8
    settings = make_settings(awards(specs))
    pipeline.build(settings)
    assert query(
        settings,
        "select under_over_ratio, placebo_ratio, excess_over_placebo "
        "from mart_bunching_national where round_amount = 1000000",
    ) == [(8.0, 4.0, 2.0)]  # median of 2, 4 and 9 is 4; their mean would be 5


def test_agency_bunching_needs_enough_awards_to_be_shown(make_settings):
    few = [{"organization_name": "CITY OF BACOLOD", "contract_amount": 990_000.0}] * 29
    many = [{"organization_name": "CITY OF TALISAY", "contract_amount": 990_000.0}] * 29
    many += [{"organization_name": "CITY OF TALISAY", "contract_amount": 1_010_000.0}]
    settings = make_settings(awards(few + many))
    pipeline.build(settings)
    assert query(
        settings,
        "select a.agency_name, b.awards_under, b.awards_over, b.enough_data "
        "from mart_bunching_agency b join core_agencies a using (agency_id) "
        "where round_amount = 1000000 order by 1",
    ) == [("CITY OF BACOLOD", 29, 0, False), ("CITY OF TALISAY", 29, 1, True)]


def test_rule_change_summary_compares_the_same_months_in_both_years(make_settings):
    settings = make_settings(
        awards(
            [
                {"award_date": "2022-04-10", "contract_amount": 990_000.0},  # too early for the monthly series
                {"award_date": "2023-04-10", "contract_amount": 990_000.0},  # in the series, not in the summary
                {"award_date": "2024-02-28", "contract_amount": 990_000.0},  # before the window
                {"award_date": "2024-03-01", "contract_amount": 990_000.0},
                {"award_date": "2024-08-31", "contract_amount": 1_050_000.0},
                {"award_date": "2024-09-01", "contract_amount": 990_000.0},  # after the window
                {"award_date": "2025-03-15", "contract_amount": 1_900_000.0},
                {"award_date": "2025-04-15", "contract_amount": 1_950_000.0},
                {"award_date": "2025-05-15", "contract_amount": 2_100_000.0},
                {"award_date": "2025-06-15", "contract_amount": 40_000.0},
            ]
        )
    )
    pipeline.build(settings)
    assert query(
        settings,
        "select award_year, awards, under_1m, over_1m, under_2m, over_2m, ratio_1m, ratio_2m "
        "from mart_rule_change_summary order by 1",
    ) == [(2024, 2, 1, 1, 0, 0, 1.0, None), (2025, 4, 0, 0, 2, 1, None, 2.0)]
    assert query(settings, "select count(*), sum(awards), min(award_month) from mart_rule_change_monthly") == [
        (9, 9, __import__("datetime").date(2023, 4, 1))
    ]


def same_day(settings):
    return query(
        settings,
        "select award_date, notices, total_value, largest_notice, ceiling from mart_same_day_groups",
    )


def test_same_day_group_is_three_notices_under_the_ceiling_summing_over_it(make_settings):
    settings = make_settings(awards([{"contract_amount": 400_000.0}] * 3))
    report = pipeline.build(settings)
    assert report["publishable"]
    assert [row[1:] for row in same_day(settings)] == [(3, 1_200_000.0, 400_000.0, 1_000_000.0)]
    assert query(settings, "select award_year, groups, notices, total_value from mart_same_day_agency") == [
        (2024, 1, 3, 1_200_000.0)
    ]


@pytest.mark.parametrize(
    "specs",
    [
        [{"contract_amount": 400_000.0}] * 2,  # only two notices
        [{"contract_amount": 300_000.0}] * 3,  # sum stays within the ceiling
        [{"contract_amount": amount} for amount in (400_000.0, 300_000.0, 300_000.0)],  # sum equals the ceiling
        [{"contract_amount": 80_000.0}] * 3,  # over the 200,000 shopping ceiling, which is a different rule
        [{"contract_amount": 1_200_000.0}, {"contract_amount": 10_000.0}, {"contract_amount": 20_000.0}],
        [{"contract_amount": 400_000.0, "awardee_name": name} for name in ("A SUPPLY", "B SUPPLY", "C SUPPLY")],
        [{"contract_amount": 400_000.0, "award_date": f"2024-03-0{day}"} for day in (1, 2, 3)],
        [{"contract_amount": 400_000.0, "organization_name": f"CITY OF {name}"} for name in ("X", "Y", "Z")],
        [{"contract_amount": 400_000.0, "award_date": "2015-03-01"}] * 3,  # before any ceiling on file
    ],
)
def test_same_day_group_is_not_raised(make_settings, specs):
    settings = make_settings(awards(specs))
    pipeline.build(settings)
    assert same_day(settings) == []


def test_lots_of_one_notice_count_once_and_rows_without_reference_are_ignored(make_settings):
    lots = [
        award(i, reference_id="77", contract_no="77", award_title=f"Lot {i}", contract_amount=200_000.0)
        for i in (1, 2, 3)
    ]
    unkeyed = [
        award(i, reference_id=None, contract_no=None, award_title=f"Item {i}", contract_amount=100_000.0)
        for i in (4, 5, 6)
    ]
    second_notice = [award(7, reference_id="78", contract_no="78", contract_amount=500_000.0)]
    settings = make_settings(lots + unkeyed + second_notice)
    pipeline.build(settings)
    # Two real notices. The unkeyed rows must not be counted as a third.
    assert same_day(settings) == []


def test_same_day_uses_the_ceiling_in_force_on_the_day(make_settings):
    settings = make_settings(
        awards(
            [{"contract_amount": 700_000.0, "award_date": "2025-02-24"}] * 3
            + [{"contract_amount": 700_000.0, "award_date": "2025-02-25"}] * 3
            + [{"contract_amount": 1_500_000.0, "award_date": "2025-03-10"}] * 3
        )
    )
    pipeline.build(settings)
    assert sorted(same_day(settings)) == sorted(
        [
            (__import__("datetime").date(2025, 2, 24), 3, 2_100_000.0, 700_000.0, 1_000_000.0),
            (__import__("datetime").date(2025, 2, 25), 3, 2_100_000.0, 700_000.0, 2_000_000.0),
            (__import__("datetime").date(2025, 3, 10), 3, 4_500_000.0, 1_500_000.0, 2_000_000.0),
        ]
    )


def test_supplier_concentration_shares(make_settings):
    specs = [{"awardee_name": "BIG SUPPLY", "contract_amount": 60_000.0}]
    specs += [{"awardee_name": "MID SUPPLY", "contract_amount": 15_000.0}] * 2
    specs += [{"awardee_name": "SMALL SUPPLY", "contract_amount": 10_000.0}]
    settings = make_settings(awards(specs))
    pipeline.build(settings)
    rows = query(
        settings,
        "select award_year, awards, suppliers, total_value, top_supplier_share, herfindahl, enough_data "
        "from mart_supplier_concentration",
    )
    assert rows == [(2024, 4, 3, 100_000.0, 0.6, pytest.approx(0.36 + 0.09 + 0.01), False)]


def test_concentration_is_per_agency_and_year(make_settings):
    settings = make_settings(
        awards(
            [{"organization_name": "CITY OF TALISAY"}] * 30
            + [{"organization_name": "CITY OF TALISAY", "award_date": "2023-05-05"}]
            + [{"organization_name": "CITY OF BACOLOD", "awardee_name": "OTHER SUPPLY"}]
        )
    )
    pipeline.build(settings)
    assert query(
        settings,
        "select a.agency_name, c.award_year, c.awards, c.top_supplier_share, c.enough_data "
        "from mart_supplier_concentration c join core_agencies a using (agency_id) order by 1, 2",
    ) == [
        ("CITY OF BACOLOD", 2024, 1, 1.0, False),
        ("CITY OF TALISAY", 2023, 1, 1.0, False),
        ("CITY OF TALISAY", 2024, 30, 1.0, True),
    ]


def test_rollups(make_settings):
    settings = make_settings(
        awards(
            [
                {"area_of_delivery": "Negros Occidental, Iloilo", "contract_amount": 100.0},
                {"area_of_delivery": "Negros Occidental", "contract_amount": 50.0, "reference_id": None},
                {"area_of_delivery": None, "contract_amount": 25.0, "award_date": "2023-01-01",
                 "organization_name": "CITY OF BACOLOD"},
            ]
        )
    )
    pipeline.build(settings)
    assert query(
        settings,
        "select award_year, awards, total_value, agencies, suppliers, share_with_reference_id "
        "from mart_yearly order by 1",
    ) == [(2023, 1, 25.0, 1, 1, 1.0), (2024, 2, 150.0, 1, 1, 0.5)]
    assert query(settings, "select area_name, award_year, awards, total_value from mart_area_year order by 1") == [
        ("Iloilo", 2024, 1, 100.0),
        ("Negros Occidental", 2024, 2, 150.0),
    ]
    assert query(
        settings,
        "select m.area_name, a.agency_name, m.awards, m.total_value "
        "from mart_area_agency m join core_agencies a using (agency_id) order by 1",
    ) == [("Iloilo", "CITY OF TALISAY", 1, 100.0), ("Negros Occidental", "CITY OF TALISAY", 2, 150.0)]
    assert query(settings, "select count(*), sum(awards), sum(total_value) from mart_agency_year") == [(2, 3, 175.0)]


def test_agency_types(make_settings):
    names = [
        "BARANGAY ZONE 12-A, TALISAY CITY",
        "MUNICIPALITY OF MURCIA, NEGROS OCCIDENTAL",
        "CITY OF TALISAY",
        "CITY GOVERNMENT OF BACOLOD",
        "PROVINCE OF NEGROS OCCIDENTAL",
        "DEPARTMENT OF EDUCATION - DIVISION OF LA CARLOTA CITY",
        "LIGA NG MGA BARANGAY - TALISAY CHAPTER",
    ]
    settings = make_settings(awards([{"organization_name": name} for name in names]))
    pipeline.build(settings)
    assert query(settings, "select agency_type, count(*) from core_agencies group by 1 order by 1") == [
        ("barangay", 1),
        ("city", 2),
        ("municipality", 1),
        ("national_or_other", 2),
        ("province", 1),
    ]


def test_amount_kinds_come_from_the_seed_and_unexplained_amounts_stay_out_of_the_baseline(make_settings):
    specs = []
    specs += [{"contract_amount": 95_000.0}] * 2 + [{"contract_amount": 105_000.0}]  # placebo ratio 2
    specs += [{"contract_amount": 290_000.0}] * 2 + [{"contract_amount": 310_000.0}]  # placebo ratio 2
    specs += [{"contract_amount": 4_900_000.0}] * 50 + [{"contract_amount": 5_100_000.0}]  # unexplained, ratio 50
    settings = make_settings(awards(specs))
    pipeline.build(settings)
    assert query(
        settings,
        "select round_amount, amount_kind, under_over_ratio, placebo_ratio from mart_bunching_national order by 1",
    ) == [
        (100000, "placebo", 2.0, 2.0),
        (300000, "placebo", 2.0, 2.0),
        (5000000, "unexplained", 50.0, 2.0),
    ]


def tampered(settings, sql) -> dict:
    con = duckdb.connect(str(settings.warehouse))
    try:
        pipeline._set_variables(con, settings)
        con.execute(sql)
        return {r["name"]: r for r in checks.run_checks(con)}
    finally:
        con.close()


CORRUPTIONS = [
    ("update mart_yearly set awards = awards + 1", "marts_reconcile_to_core"),
    ("update mart_agency_year set total_value = total_value * 2", "marts_reconcile_to_core"),
    ("update mart_supplier_concentration set awards = awards + 1", "marts_reconcile_to_core"),
    ("update mart_bunching_national set awards_under = 0 where round_amount = 1000000", "bunching_counts_match_core"),
    ("update mart_bunching_national set awards_over = 5 where round_amount = 1000000", "bunching_counts_match_core"),
    ("delete from mart_bunching_national where round_amount = 1000000", "bunching_counts_match_core"),
    ("update mart_supplier_concentration set herfindahl = 1.5", "concentration_shares_valid"),
    ("update mart_supplier_concentration set herfindahl = 0", "concentration_shares_valid"),
    ("update mart_supplier_concentration set top_supplier_share = 0", "concentration_shares_valid"),
    ("update mart_supplier_concentration set top_supplier_share = 1.5, herfindahl = 1", "concentration_shares_valid"),
    ("update analysis_amounts set amount_kind = 'placebo' where round_amount = 1000000", "analysis_amounts_consistent"),
    ("delete from analysis_amounts where amount_kind = 'placebo' and round_amount > 100000", "analysis_amounts_consistent"),
    ("update analysis_amounts set amount_kind = 'typo' where round_amount = 50000", "analysis_amounts_consistent"),
    ("update mart_same_day_groups set notices = 2", "same_day_groups_meet_definition"),
    ("update mart_same_day_groups set largest_notice = 1000001", "same_day_groups_meet_definition"),
    ("update mart_same_day_groups set total_value = 1000000", "same_day_groups_meet_definition"),
]


@pytest.mark.parametrize("corruption, check", CORRUPTIONS)
def test_mart_checks_catch_corrupted_marts(make_settings, corruption, check):
    settings = make_settings(
        awards(
            [{"contract_amount": 400_000.0}] * 3
            + [{"contract_amount": amount, "awardee_name": "OTHER SUPPLY"} for amount in (990_000.0, 1_050_000.0)]
        )
    )
    assert pipeline.build(settings)["publishable"]
    assert tampered(settings, corruption)[check]["violations"] == 1
