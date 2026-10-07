"""Sample supplier name pairs for labelling, and score the matcher against the labels."""

import csv
import json
from pathlib import Path

from . import matching

# Candidate pool: pairs of distinct supplier names that share a first word and
# have Jaro-Winkler similarity of at least POOL_FLOOR on their cleaned names.
POOL_FLOOR = 0.80
BANDS = [(0.80, 0.90), (0.90, 0.95), (0.95, 0.99), (0.99, 1.0001)]
PAIRS_PER_BAND = 75
LEVELS = (1, 2, 3)

POOL_SQL = f"""
create or replace temp table pair_pool as
with names as (
    select
        supplier_key,
        any_value(clean_key) as clean_key,
        split_part(any_value(clean_key), ' ', 1) as block,
        sum(award_count) as award_count
    from core_supplier_aliases
    group by supplier_key
),
scored as (
    select
        a.supplier_key as key_a,
        b.supplier_key as key_b,
        jaro_winkler_similarity(a.clean_key, b.clean_key) as similarity
    from names a
    join names b on a.block = b.block and a.supplier_key < b.supplier_key
    where length(a.block) >= 3
)
select * from scored where similarity >= {POOL_FLOOR}
"""


def _band(similarity: float) -> int:
    for index, (low, high) in enumerate(BANDS):
        if low <= similarity < high:
            return index
    raise ValueError(similarity)


def sample_pairs(con) -> tuple[list[dict], dict]:
    """Return (pairs, pool) with a fixed, order-independent sample per band."""
    con.execute(POOL_SQL)
    pairs = []
    pool_sizes = []
    for index, (low, high) in enumerate(BANDS):
        in_band = f"similarity >= {low} and similarity < {high}"
        pool_sizes.append(con.execute(f"select count(*) from pair_pool where {in_band}").fetchone()[0])
        rows = con.execute(
            f"""
            select key_a, key_b, round(similarity, 4)
            from pair_pool where {in_band}
            order by md5(key_a || chr(31) || key_b)
            limit {PAIRS_PER_BAND}
            """
        ).fetchall()
        pairs += [{"band": index, "key_a": a, "key_b": b, "similarity": s} for a, b, s in rows]
    pool = {"floor": POOL_FLOOR, "bands": BANDS, "pool_sizes": pool_sizes, "pairs_per_band": PAIRS_PER_BAND}
    return pairs, pool


def read_labels(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def evaluate(keys: list[str], labels: list[dict], pool_sizes: list[int]) -> dict:
    """Score each matching level on the labelled pairs.

    Reported twice: raw counts on the sample, and estimates weighted back to
    the candidate pool, since the sample takes the same number of pairs from
    bands of very different sizes. Pairs labelled 'unsure' are excluded.
    """
    usable = [row for row in labels if row["label"] in ("same", "different")]
    sampled = [0] * len(pool_sizes)
    for row in labels:
        sampled[int(row["band"])] += 1
    weights = [pool / n if n else 0.0 for pool, n in zip(pool_sizes, sampled)]

    report = {
        "labelled_pairs": len(labels),
        "usable_pairs": len(usable),
        "unsure_pairs": len(labels) - len(usable),
        "levels": {},
    }
    for level in LEVELS:
        resolved = matching.resolve(keys, level)
        tp = fp = fn = 0
        wtp = wfp = wfn = 0.0
        for row in usable:
            predicted = resolved[row["key_a"]][1] == resolved[row["key_b"]][1]
            actual = row["label"] == "same"
            weight = weights[int(row["band"])]
            if predicted and actual:
                tp, wtp = tp + 1, wtp + weight
            elif predicted:
                fp, wfp = fp + 1, wfp + weight
            elif actual:
                fn, wfn = fn + 1, wfn + weight
        report["levels"][str(level)] = {
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "pool_weighted_precision": wtp / (wtp + wfp) if wtp + wfp else None,
            "pool_weighted_recall": wtp / (wtp + wfn) if wtp + wfn else None,
        }
    return report


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
