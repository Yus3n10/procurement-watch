from pw.evaluation import evaluate

KEYS = [
    "ABC TRADING INC",
    "A.B.C. TRADING, INC.",
    "ABC TRADING CORPORATION",
    "XYZ SUPPLY",
    "XYZ SUPPLIES",
    "LUCKY ME TRADING",
    "LUCKY MED TRADING",
]


def pair(band, key_a, key_b, label):
    return {"band": str(band), "key_a": key_a, "key_b": key_b, "label": label}


LABELS = [
    pair(1, "ABC TRADING INC", "A.B.C. TRADING, INC.", "same"),  # found at every level
    pair(1, "ABC TRADING INC", "ABC TRADING CORPORATION", "same"),  # found at level 3 only
    pair(0, "XYZ SUPPLY", "XYZ SUPPLIES", "same"),  # never found
    pair(0, "LUCKY ME TRADING", "LUCKY MED TRADING", "different"),
    pair(0, "XYZ SUPPLY", "LUCKY ME TRADING", "unsure"),
]


def test_counts_per_level_and_unsure_pairs_excluded():
    report = evaluate(KEYS, LABELS, pool_sizes=[300, 20])
    assert report["labelled_pairs"] == 5
    assert report["usable_pairs"] == 4
    assert report["unsure_pairs"] == 1
    level_1, level_3 = report["levels"]["1"], report["levels"]["3"]
    assert (level_1["true_positives"], level_1["false_positives"], level_1["false_negatives"]) == (1, 0, 2)
    assert (level_3["true_positives"], level_3["false_positives"], level_3["false_negatives"]) == (2, 0, 1)
    assert level_1["precision"] == 1.0
    assert level_1["recall"] == 1 / 3
    assert level_3["recall"] == 2 / 3


def test_pool_weighting_scales_each_band_by_its_population():
    # Band 0 has 3 sampled pairs standing for 300; band 1 has 2 standing for 20.
    report = evaluate(KEYS, LABELS, pool_sizes=[300, 20])
    # Level 3 finds both band-1 pairs (weight 10 each) and misses one band-0 pair (weight 100).
    assert report["levels"]["3"]["pool_weighted_recall"] == 20 / 120


def test_a_wrong_merge_counts_against_precision():
    labels = [
        pair(0, "ABC TRADING INC", "ABC TRADING CORPORATION", "different"),
        pair(0, "ABC TRADING INC", "A.B.C. TRADING, INC.", "same"),
    ]
    report = evaluate(KEYS, labels, pool_sizes=[2])
    assert report["levels"]["1"]["precision"] == 1.0
    assert report["levels"]["3"]["precision"] == 0.5
    assert report["levels"]["3"]["false_positives"] == 1


def test_no_predictions_gives_undefined_precision_not_a_crash():
    labels = [pair(0, "XYZ SUPPLY", "XYZ SUPPLIES", "same")]
    report = evaluate(KEYS, labels, pool_sizes=[1])
    assert report["levels"]["1"]["precision"] is None
    assert report["levels"]["1"]["recall"] == 0.0
