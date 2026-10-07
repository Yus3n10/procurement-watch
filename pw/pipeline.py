import json

import duckdb

from . import checks, config, matching, normalize

STAGING_STEPS = ["20_staging.sql", "30_quarantine.sql"]
CORE_STEPS = ["40_core.sql", "50_marts.sql"]
SEED_TABLES = {
    "seed_areas": "areas.csv",
    "large_amount_allowlist": "large_amount_allowlist.csv",
    "seed_thresholds": "thresholds.csv",
    "seed_analysis_amounts": "analysis_amounts.csv",
}


def _sql_path(path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def connect(settings: config.Settings) -> duckdb.DuckDBPyConnection:
    settings.build_dir.mkdir(parents=True, exist_ok=True)
    for stale in (settings.warehouse, settings.warehouse.with_suffix(".duckdb.wal")):
        stale.unlink(missing_ok=True)
    return duckdb.connect(str(settings.warehouse))


def _set_variables(con, settings: config.Settings) -> None:
    con.execute(f"set variable snapshot_date = '{settings.snapshot_date}'")
    con.execute(f"set variable earliest_award_date = '{config.EARLIEST_AWARD_DATE}'")
    con.execute(f"set variable min_amount = {config.MIN_AMOUNT}")
    con.execute(f"set variable large_amount = {config.LARGE_AMOUNT}")
    con.execute(f"set variable band_width = {config.BAND_WIDTH}")
    con.execute(f"set variable min_band_awards = {config.MIN_BAND_AWARDS}")
    con.execute(f"set variable min_agency_year_awards = {config.MIN_AGENCY_YEAR_AWARDS}")
    con.execute(f"set variable same_day_min_notices = {config.SAME_DAY_MIN_NOTICES}")
    con.execute(f"set variable rule_change_first_month = {config.RULE_CHANGE_MONTHS[0]}")
    con.execute(f"set variable rule_change_last_month = {config.RULE_CHANGE_MONTHS[1]}")
    con.execute(f"set variable rule_change_years = {list(config.RULE_CHANGE_YEARS)}")


def _load_sources(con, settings: config.Settings) -> None:
    raw = _sql_path(settings.raw_dir / "philgeps.parquet")
    con.execute(f"create or replace view raw_awards as select * from read_parquet('{raw}')")
    for table, filename in SEED_TABLES.items():
        path = _sql_path(settings.seed_dir / filename)
        con.execute(
            f"create or replace table {table} as "
            f"select * from read_csv('{path}', header = true, all_varchar = true)"
        )


def _load_jsonl(con, settings: config.Settings, table: str, columns: dict, records) -> None:
    """Load Python-computed rows into a table.

    Names are folded and matched in plain Python and loaded back, because a
    DuckDB Python function did the same work about 100 times slower.
    """
    path = settings.build_dir / f"{table}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    spec = ", ".join(f"{name}: '{kind}'" for name, kind in columns.items())
    con.execute(
        f"create or replace table {table} as select * from read_json('{_sql_path(path)}', "
        f"format = 'newline_delimited', columns = {{{spec}}})"
    )
    path.unlink()


def _build_name_table(con, settings: config.Settings, table: str, raw_column: str, prefix: str) -> None:
    """Fold each distinct raw name once: ~150k names instead of 5.4 million rows."""
    names = [row[0] for row in con.execute(f"select distinct {raw_column} from raw_awards order by 1").fetchall()]
    records = []
    for name in names:
        key, confusables, dropped = normalize.fold(name)
        records.append(
            {
                f"{prefix}_raw": name,
                f"{prefix}_key": key,
                "confusables_replaced": confusables,
                "letters_dropped": dropped,
            }
        )
    columns = {
        f"{prefix}_raw": "VARCHAR",
        f"{prefix}_key": "VARCHAR",
        "confusables_replaced": "INTEGER",
        "letters_dropped": "INTEGER",
    }
    _load_jsonl(con, settings, table, columns, records)


def _build_supplier_matches(con, settings: config.Settings) -> None:
    keys = [row[0] for row in con.execute("select distinct supplier_key from stg_supplier_names order by 1").fetchall()]
    resolved = matching.resolve(keys, config.MATCH_LEVEL)
    columns = {"supplier_key": "VARCHAR", "clean_key": "VARCHAR", "match_key": "VARCHAR", "rule": "VARCHAR"}
    records = (
        {"supplier_key": key, "clean_key": clean, "match_key": match, "rule": rule}
        for key, (clean, match, rule) in resolved.items()
    )
    _load_jsonl(con, settings, "stg_supplier_matches", columns, records)


def summarise(con) -> dict:
    one = lambda sql: con.execute(sql).fetchone()[0]
    pairs = lambda sql: dict(con.execute(sql).fetchall())
    return {
        "raw_rows": one("select count(*) from raw_awards"),
        "staged_rows": one("select count(*) from stg_awards"),
        "quarantined_rows": one("select count(*) from quarantine_awards"),
        "quarantine_by_rule": pairs(
            "select rule, count(*) from quarantine_awards group by 1 order by 2 desc, 1"
        ),
        "agency_names_raw": one("select count(*) from stg_agency_names"),
        "agency_keys": one("select count(distinct agency_key) from stg_agency_names"),
        "supplier_names_raw": one("select count(*) from stg_supplier_names"),
        "supplier_keys": one("select count(distinct supplier_key) from stg_supplier_names"),
        "names_with_confusables": one(
            "select (select count(*) from stg_agency_names where confusables_replaced > 0)"
            " + (select count(*) from stg_supplier_names where confusables_replaced > 0)"
        ),
        "staged_value": one("select sum(contract_amount) from stg_awards"),
        "agencies": one("select count(*) from core_agencies"),
        "suppliers": one("select count(*) from core_suppliers"),
        "supplier_aliases": one("select count(*) from core_supplier_aliases"),
        "aliases_by_rule": pairs(
            "select rule, count(*) from core_supplier_aliases group by 1 order by 2 desc, 1"
        ),
        "match_level": config.MATCH_LEVEL,
    }


def build(settings: config.Settings) -> dict:
    """Rebuild the warehouse from raw files and return the run report."""
    con = connect(settings)
    try:
        _set_variables(con, settings)
        _load_sources(con, settings)
        _build_name_table(con, settings, "stg_agency_names", "organization_name", "agency")
        _build_name_table(con, settings, "stg_supplier_names", "awardee_name", "supplier")
        for step in STAGING_STEPS:
            con.execute((config.SQL_DIR / step).read_text(encoding="utf-8"))
        _build_supplier_matches(con, settings)
        for step in CORE_STEPS:
            con.execute((config.SQL_DIR / step).read_text(encoding="utf-8"))
        results = checks.run_checks(con)
        report = {
            "snapshot_date": settings.snapshot_date,
            "summary": summarise(con),
            "checks": results,
            "publishable": not checks.blocking_failures(results),
        }
    finally:
        con.close()
    (settings.build_dir / "dq_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
