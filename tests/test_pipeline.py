import duckdb

from pw import checks, pipeline

from conftest import award


def rules(settings) -> dict:
    con = duckdb.connect(str(settings.warehouse), read_only=True)
    try:
        return dict(con.execute("select award_id, rule from quarantine_awards").fetchall())
    finally:
        con.close()


def query(settings, sql):
    con = duckdb.connect(str(settings.warehouse), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def check(report, name) -> dict:
    return next(c for c in report["checks"] if c["name"] == name)


def uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def test_clean_rows_pass_every_check(make_settings):
    settings = make_settings([award(1), award(2, reference_id="101", contract_no="101")])
    report = pipeline.build(settings)
    assert report["publishable"]
    assert report["summary"]["staged_rows"] == 2
    assert report["summary"]["quarantined_rows"] == 0


def test_each_rule_quarantines_its_row(make_settings):
    settings = make_settings(
        [
            award(1),
            award(2, award_date=None),
            award(3, award_date="1920-01-08"),
            award(4, award_date="2034-10-04"),
            award(5, contract_amount=0.01),
            award(6, contract_amount=2e10),
        ]
    )
    report = pipeline.build(settings)
    assert rules(settings) == {
        uid(2): "missing_award_date",
        uid(3): "award_date_before_2006",
        uid(4): "award_date_after_snapshot",
        uid(5): "amount_below_one_peso",
        uid(6): "amount_above_10bn_unreviewed",
    }
    assert report["summary"]["staged_rows"] == 1
    assert check(report, "row_counts_reconcile")["passed"]


def test_boundary_values_are_kept(make_settings):
    settings = make_settings(
        [
            award(1, award_date="2006-01-01"),
            award(2, award_date="2026-01-06"),
            award(3, contract_amount=1.0),
            award(4, contract_amount=1e10),
        ]
    )
    report = pipeline.build(settings)
    assert report["summary"]["quarantined_rows"] == 0


def test_exact_duplicates_keep_one_row(make_settings):
    settings = make_settings([award(3), award(1), award(2)])
    report = pipeline.build(settings)
    assert rules(settings) == {uid(2): "exact_duplicate", uid(3): "exact_duplicate"}
    assert query(settings, "select award_id from stg_awards") == [(uid(1),)]
    assert check(report, "no_exact_duplicates")["passed"]


def test_rows_differing_in_one_column_are_not_duplicates(make_settings):
    settings = make_settings([award(1), award(2, contract_amount=50000.01)])
    report = pipeline.build(settings)
    assert report["summary"]["quarantined_rows"] == 0


def test_duplicate_of_a_bad_row_is_reported_as_duplicate_first(make_settings):
    settings = make_settings([award(1, award_date=None), award(2, award_date=None)])
    pipeline.build(settings)
    assert rules(settings) == {uid(1): "missing_award_date", uid(2): "exact_duplicate"}


def test_allowlisted_large_amount_is_kept(make_settings):
    settings = make_settings([award(1, contract_amount=2e10)], allowlist=[uid(1)])
    report = pipeline.build(settings)
    assert report["summary"]["quarantined_rows"] == 0
    assert check(report, "amount_in_range")["passed"]


def test_lookalike_agency_names_share_one_key(make_settings):
    settings = make_settings(
        [
            award(1, organization_name="PROVINCE OF NEGROS OCCIDENTAL"),
            award(2, organization_name="ΡROVINCE OF NEGROS OCCIDENTAL"),
            award(3, organization_name="РRÒVINCE OF NÈGROS OCCÏDENTAL"),
        ]
    )
    report = pipeline.build(settings)
    assert report["summary"]["agency_names_raw"] == 3
    assert report["summary"]["agency_keys"] == 1
    assert query(settings, "select count(distinct agency_key) from stg_awards") == [(1,)]
    assert check(report, "name_keys_are_ascii")["passed"]


def test_unmappable_name_blocks_publishing(make_settings):
    settings = make_settings([award(1, awardee_name="中文 TRADING")])
    report = pipeline.build(settings)
    assert not check(report, "name_keys_are_lossless")["passed"]
    assert not report["publishable"]


def test_areas_are_split_and_aliased(make_settings):
    settings = make_settings(
        [award(1, area_of_delivery="Negros Occidental, Compostela Valley, sample province")]
    )
    report = pipeline.build(settings)
    assert query(
        settings, "select token, area_name, kind from stg_award_areas order by token"
    ) == [
        ("Compostela Valley", "Davao de Oro", "province"),
        ("Negros Occidental", "Negros Occidental", "province"),
        ("sample province", None, "invalid"),
    ]
    assert check(report, "area_tokens_known")["passed"]


def test_unknown_area_token_blocks_publishing(make_settings):
    settings = make_settings([award(1, area_of_delivery="Atlantis")])
    report = pipeline.build(settings)
    assert check(report, "area_tokens_known")["violations"] == 1
    assert not report["publishable"]


def test_yearly_value_tripwire_fires_on_a_gross_jump(make_settings):
    settings = make_settings(
        [
            award(1, award_date="2020-05-01", contract_amount=100.0),
            award(2, award_date="2021-05-01", contract_amount=1000.0),
        ]
    )
    report = pipeline.build(settings)
    assert check(report, "yearly_value_within_tolerance")["violations"] == 1


def test_duplicate_value_share_warns_without_blocking(make_settings):
    settings = make_settings([award(1), award(2), award(3)])
    report = pipeline.build(settings)
    assert not check(report, "raw_duplicate_value_share")["passed"]
    assert report["publishable"]


def test_duplicate_profile_counts_rows_and_value(make_settings):
    settings = make_settings([award(1), award(2), award(3), award(4, reference_id="9")])
    pipeline.build(settings)
    assert query(
        settings,
        "select award_year, raw_rows, duplicate_rows, raw_value, duplicate_value "
        "from profile_duplicates_by_year",
    ) == [(2024, 4, 2, 200000.0, 100000.0)]


def tampered_checks(settings, tamper_sql) -> dict:
    """Corrupt a finished warehouse, then rerun the checks against it."""
    con = duckdb.connect(str(settings.warehouse))
    try:
        pipeline._set_variables(con, settings)
        con.execute(tamper_sql)
        return {r["name"]: r for r in checks.run_checks(con)}
    finally:
        con.close()


def test_reconciliation_catches_a_lost_row(make_settings):
    settings = make_settings([award(1), award(2, reference_id="101")])
    pipeline.build(settings)
    results = tampered_checks(settings, f"delete from awards_ruled where award_id = '{uid(2)}'")
    assert results["row_counts_reconcile"]["violations"] == 1


def test_duplicate_checks_catch_a_row_staged_twice(make_settings):
    settings = make_settings([award(1), award(2, reference_id="101")])
    pipeline.build(settings)
    results = tampered_checks(
        settings, f"insert into awards_ruled select * from awards_ruled where award_id = '{uid(1)}'"
    )
    assert results["award_id_unique"]["violations"] == 1
    assert results["no_exact_duplicates"]["violations"] == 1


def test_rebuild_is_deterministic(make_settings):
    rows = [award(1), award(2), award(3, award_date=None), award(4, reference_id="7")]
    settings = make_settings(rows)
    first = pipeline.build(settings)
    snapshot = query(settings, "select * from stg_awards order by award_id")
    second = pipeline.build(settings)
    assert first == second
    assert query(settings, "select * from stg_awards order by award_id") == snapshot


def test_supplier_spellings_resolve_to_one_entity(make_settings):
    settings = make_settings(
        [
            award(1, awardee_name="MERCURY DRUG CORPORATION", reference_id="1"),
            award(2, awardee_name="MERCURY DRUG CORP.", reference_id="2"),
            award(3, awardee_name="MERCURY DRUG CORPORATION - MAKATI", reference_id="3"),
            award(4, awardee_name="MERCURY DRUG CORPORATION - MAKATI", reference_id="4"),
            award(5, awardee_name="MERCURY DRUG CORPORATION - MAKATI", reference_id="5"),
            award(6, awardee_name="MERCURIAL TRADING", reference_id="6"),
        ]
    )
    report = pipeline.build(settings)
    assert report["publishable"]
    assert query(
        settings,
        "select supplier_name, match_key, alias_count, award_count, total_value "
        "from core_suppliers order by supplier_name",
    ) == [
        ("MERCURIAL TRADING", "MERCURIAL TRADING", 1, 1, 50000.0),
        ("MERCURY DRUG CORP.", "MERCURY DRUG", 3, 5, 250000.0),
    ]
    assert query(
        settings,
        "select supplier_raw, rule from core_supplier_aliases order by supplier_raw",
    ) == [
        ("MERCURIAL TRADING", "identical"),
        ("MERCURY DRUG CORP.", "punctuation+legal_form_dropped"),
        ("MERCURY DRUG CORPORATION", "punctuation+legal_form_dropped"),
        ("MERCURY DRUG CORPORATION - MAKATI", "punctuation+branch_suffix+legal_form_dropped"),
    ]
    assert query(settings, "select count(distinct supplier_id), count(*) from core_awards") == [(2, 6)]


def test_agency_display_name_is_the_most_common_spelling(make_settings):
    settings = make_settings(
        [
            award(1, organization_name="CITY OF  TALISAY", reference_id="1"),
            award(2, organization_name="CITY OF TALISAY", reference_id="2"),
            award(3, organization_name="CITY OF TALISAY", reference_id="3"),
            award(4, organization_name="CITY OF BACOLOD", reference_id="4", contract_amount=10.0),
        ]
    )
    pipeline.build(settings)
    assert query(
        settings,
        "select agency_name, name_variants, award_count, total_value, first_award_date = last_award_date "
        "from core_agencies order by agency_name",
    ) == [("CITY OF BACOLOD", 1, 1, 10.0, True), ("CITY OF TALISAY", 2, 3, 150000.0, True)]


def test_core_awards_carry_year_and_valid_areas_only(make_settings):
    settings = make_settings(
        [award(1, award_date="2023-12-31", area_of_delivery="Compostela Valley, Davao de Oro (Compos. Valley), Philippines")]
    )
    pipeline.build(settings)
    assert query(settings, "select award_year, contract_amount from core_awards") == [(2023, 50000.0)]
    assert query(settings, "select area_name, kind from core_award_areas") == [("Davao de Oro", "province")]


def test_core_checks_catch_a_dropped_award_and_an_overlapping_threshold(make_settings):
    settings = make_settings([award(1), award(2, reference_id="101", contract_amount=70000.0)])
    pipeline.build(settings)
    results = tampered_checks(
        settings,
        f"delete from core_awards where award_id = '{uid(2)}';"
        "insert into core_thresholds select threshold, 5, effective_from + 1, effective_to, applies_to, "
        "legal_basis, source from core_thresholds where threshold = 'shopping_unforeseen'",
    )
    assert results["core_awards_complete"]["violations"] == 1
    assert results["core_value_matches_staging"]["violations"] == 1
    assert results["thresholds_do_not_overlap"]["violations"] == 1


def test_core_checks_catch_duplicate_ids_and_double_mapped_aliases(make_settings):
    settings = make_settings([award(1), award(2, reference_id="101", awardee_name="XYZ SUPPLY")])
    pipeline.build(settings)
    results = tampered_checks(
        settings,
        "insert into core_agencies select * from core_agencies;"
        "insert into core_supplier_aliases select supplier_raw, supplier_key, clean_key, 'OTHER', supplier_id, "
        "rule, award_count, total_value from core_supplier_aliases where supplier_raw = 'XYZ SUPPLY'",
    )
    assert results["entity_ids_unique"]["violations"] == 2
    assert results["alias_maps_to_one_supplier"]["violations"] == 1


def test_core_check_catches_an_award_without_a_supplier(make_settings):
    settings = make_settings([award(1), award(2, reference_id="101")])
    pipeline.build(settings)
    results = tampered_checks(
        settings, f"update core_awards set supplier_id = null where award_id = '{uid(1)}'"
    )
    assert results["core_awards_complete"]["violations"] == 1
