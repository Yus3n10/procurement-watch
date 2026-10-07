import argparse
import csv
import json
import sys

import duckdb

from . import config, evaluation, export, pipeline, raw


def _print_report(report: dict) -> None:
    summary = report["summary"]
    print(f"raw rows          {summary['raw_rows']:>12,}")
    print(f"staged rows       {summary['staged_rows']:>12,}")
    print(f"quarantined rows  {summary['quarantined_rows']:>12,}")
    for rule, count in summary["quarantine_by_rule"].items():
        print(f"  {rule:<32}{count:>10,}")
    print(f"agency names      {summary['agency_names_raw']:>12,} -> {summary['agency_keys']:,} keys")
    print(f"supplier names    {summary['supplier_names_raw']:>12,} -> {summary['supplier_keys']:,} keys")
    print()
    for check in report["checks"]:
        status = "PASS" if check["passed"] else ("WARN" if check["severity"] == "warn" else "FAIL")
        print(f"{status}  {check['name']:<32}{check['violations']:>8,}")
    print()
    print("publishable" if report["publishable"] else "NOT publishable: a blocking check failed")


def _sample_pairs(settings: config.Settings) -> int:
    """Draw candidate pairs for labelling. Never overwrites existing labels."""
    con = duckdb.connect(str(settings.warehouse), read_only=True)
    try:
        pairs, pool = evaluation.sample_pairs(con)
    finally:
        con.close()
    target = settings.build_dir / "supplier_pair_candidates.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["band", "similarity", "key_a", "key_b", "label", "review_status"])
        for pair in pairs:
            writer.writerow([pair["band"], pair["similarity"], pair["key_a"], pair["key_b"], "", "unreviewed"])
    evaluation.write_json(settings.build_dir / "supplier_pair_pool.json", pool)
    print(f"{len(pairs)} candidate pairs written to {target}")
    return 0


def _matching_report(con, settings: config.Settings) -> dict:
    labels = evaluation.read_labels(settings.seed_dir / "supplier_pair_labels.csv")
    pool = json.loads((settings.seed_dir / "supplier_pair_pool.json").read_text(encoding="utf-8"))
    keys = [row[0] for row in con.execute("select distinct supplier_key from stg_supplier_names").fetchall()]
    report = evaluation.evaluate(keys, labels, pool["pool_sizes"])
    report["level_in_use"] = config.MATCH_LEVEL
    report["pool"] = pool
    return report


def _export(settings: config.Settings) -> int:
    """Write the site data files. Refuses if a blocking check failed."""
    report = json.loads((settings.build_dir / "dq_report.json").read_text(encoding="utf-8"))
    if not report["publishable"]:
        print("not exporting: a blocking check failed in the last build", file=sys.stderr)
        return 1
    con = duckdb.connect(str(settings.warehouse), read_only=True)
    try:
        manifest = export.export(con, report, _matching_report(con, settings), settings.site_data)
    finally:
        con.close()
    for name, size in manifest.items():
        print(f"{size:>10,}  {name}")
    print(f"{sum(manifest.values()):>10,}  total, in {settings.site_data}")
    return 0


def _eval_matching(settings: config.Settings) -> int:
    con = duckdb.connect(str(settings.warehouse), read_only=True)
    try:
        report = _matching_report(con, settings)
    finally:
        con.close()
    evaluation.write_json(settings.build_dir / "matching_report.json", report)
    print(f"{report['usable_pairs']} usable pairs, {report['unsure_pairs']} unsure and excluded")
    print("level  tp  fp  fn  precision  recall  pool-weighted precision / recall")
    fmt = lambda value: "   n/a" if value is None else f"{value:6.3f}"
    for level, row in report["levels"].items():
        marker = "  <- in use" if int(level) == config.MATCH_LEVEL else ""
        print(
            f"{level:>5} {row['true_positives']:>3} {row['false_positives']:>3} {row['false_negatives']:>3}"
            f"     {fmt(row['precision'])}  {fmt(row['recall'])}"
            f"          {fmt(row['pool_weighted_precision'])} / {fmt(row['pool_weighted_recall'])}{marker}"
        )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pw")
    parser.add_argument("command", choices=["fetch", "verify", "build", "sample-pairs", "eval-matching", "export"])
    args = parser.parse_args(argv)
    settings = config.default_settings()

    if args.command == "fetch":
        raw.fetch(settings.raw_dir)
        print(f"raw snapshot ready in {settings.raw_dir}")
        return 0

    if args.command == "sample-pairs":
        return _sample_pairs(settings)
    if args.command == "eval-matching":
        return _eval_matching(settings)
    if args.command == "export":
        return _export(settings)

    problems = raw.verify(settings.raw_dir)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    if args.command == "verify":
        print("raw snapshot matches the manifest")
        return 0

    report = pipeline.build(settings)
    _print_report(report)
    return 0 if report["publishable"] else 1


if __name__ == "__main__":
    sys.exit(main())
