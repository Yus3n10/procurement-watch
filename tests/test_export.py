import json

import duckdb

from pw import export, pipeline

from conftest import award

SUPPLIERS = ["ACME SECRET SUPPLY", "BRAVO HIDDEN TRADING", "CHARLIE PRIVATE ENTERPRISES"]


def build_and_export(make_settings, tmp_path, rows):
    settings = make_settings(rows)
    report = pipeline.build(settings)
    site_data = tmp_path / "site" / "data"
    con = duckdb.connect(str(settings.warehouse), read_only=True)
    try:
        manifest = export.export(con, report, None, site_data)
    finally:
        con.close()
    return site_data, manifest


def rows_for_one_agency(count=120):
    return [
        award(
            i,
            reference_id=str(i),
            contract_no=str(i),
            awardee_name=SUPPLIERS[i % 3],
            contract_amount=990_000.0 if i % 2 else 400_000.0,
            award_date="2024-03-01" if i % 4 else "2023-03-01",
        )
        for i in range(1, count + 1)
    ]


def load(site_data, name):
    return json.loads((site_data / name).read_text(encoding="utf-8"))


def test_export_writes_every_file_as_valid_json(make_settings, tmp_path):
    site_data, manifest = build_and_export(make_settings, tmp_path, rows_for_one_agency())
    assert sorted(manifest) == [
        "agencies.json",
        "agency_years.json",
        "bunching.json",
        "bunching_by_type.json",
        "cliff.json",
        "concentration.json",
        "focus_area.json",
        "patterns.json",
        "rule_change.json",
        "same_day.json",
        "summary.json",
        "yearly.json",
    ]
    for name in manifest:
        load(site_data, name)


def test_export_never_names_a_supplier(make_settings, tmp_path):
    site_data, manifest = build_and_export(make_settings, tmp_path, rows_for_one_agency())
    for name in manifest:
        text = (site_data / name).read_text(encoding="utf-8").upper()
        for word in ("ACME", "BRAVO", "CHARLIE", "SUPPLIER_ID", "MATCH_KEY"):
            assert word not in text, (name, word)


def test_agency_listing_needs_a_minimum_number_of_awards(make_settings, tmp_path):
    small = [
        award(1000 + i, reference_id=f"s{i}", organization_name="CITY OF BACOLOD", awardee_name=SUPPLIERS[0])
        for i in range(99)
    ]
    site_data, _ = build_and_export(make_settings, tmp_path, rows_for_one_agency(100) + small)
    agencies = load(site_data, "agencies.json")
    assert agencies["agency_name"] == ["CITY OF TALISAY"]
    assert agencies["awards"] == [100]
    assert agencies["main_area"] == ["Negros Occidental"]
    assert set(load(site_data, "agency_years.json")["agency_id"]) == set(agencies["agency_id"])


def test_agency_years_carry_each_pattern(make_settings, tmp_path):
    site_data, _ = build_and_export(make_settings, tmp_path, rows_for_one_agency())
    years = load(site_data, "agency_years.json")
    by_year = {
        year: {column: values[index] for column, values in years.items()}
        for index, year in enumerate(years["award_year"])
    }
    assert sorted(by_year) == [2023, 2024]
    assert by_year[2024]["awards"] == 90
    assert by_year[2024]["under_1m"] == 60
    assert by_year[2024]["over_1m"] == 0
    assert by_year[2024]["suppliers"] == 3
    assert by_year[2024]["same_day_groups"] == 3  # one group per supplier on the shared day
    assert 0 < by_year[2024]["top_supplier_share"] <= 1


def test_summary_and_rankings(make_settings, tmp_path):
    site_data, _ = build_and_export(make_settings, tmp_path, rows_for_one_agency())
    summary = load(site_data, "summary.json")
    assert isinstance(summary["publishable"], bool)
    assert summary["counts"]["staged_rows"] == 120
    assert {row["round_amount"] for row in summary["amounts"]} >= {1_000_000, 5_000_000}
    patterns = load(site_data, "patterns.json")
    assert sorted(patterns) == ["2023", "2024"]
    assert [row["agency_name"] for row in patterns["2024"]["bunching_1m"]] == ["CITY OF TALISAY"]
    assert patterns["2024"]["same_day"][0]["same_day_groups"] == 3
    focus = load(site_data, "focus_area.json")
    assert focus["area"] == "Negros Occidental"
    assert [row["award_year"] for row in focus["yearly"]] == [2023, 2024]
    assert focus["agencies"][0]["agency_name"] == "CITY OF TALISAY"


def test_cliff_counts_awards_at_the_ceiling_as_under_it(make_settings, tmp_path):
    amounts = [999_000.0, 1_000_000.0, 1_000_000.0, 1_000_001.0, 1_015_000.0, 800_000.0, 800_001.0, 1_200_000.0, 1_200_001.0]
    rows = [award(i, reference_id=str(i), contract_amount=amount) for i, amount in enumerate(amounts, 1)]
    rows.append(award(99, reference_id="99", contract_amount=995_000.0, award_date="2025-06-01"))
    site_data, _ = build_and_export(make_settings, tmp_path, rows)
    cliff = load(site_data, "cliff.json")
    assert cliff["year"] == 2024  # 2025 is the partial year before the snapshot
    steps = {row["step"]: row["awards"] for row in cliff["amounts"]["1000000"]}
    assert len(steps) == 40
    assert steps[-1] == 3  # 999,000 and both awards at exactly 1,000,000
    assert steps[0] == 1  # 1,000,001
    assert steps[1] == 1  # 1,015,000
    assert steps[-20] == 1  # 800,001; 800,000 itself is outside
    assert steps[19] == 1  # 1,200,000; 1,200,001 is outside
    assert sum(steps.values()) == 7


def test_export_is_deterministic_and_clears_stale_files(make_settings, tmp_path):
    site_data, first = build_and_export(make_settings, tmp_path, rows_for_one_agency())
    contents = {name: (site_data / name).read_bytes() for name in first}
    (site_data / "leftover.json").write_text("{}", encoding="utf-8")
    site_data, second = build_and_export(make_settings, tmp_path, rows_for_one_agency())
    assert first == second
    assert {name: (site_data / name).read_bytes() for name in second} == contents
