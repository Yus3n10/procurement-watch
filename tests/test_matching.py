from pw.matching import branch_head, clean, drop_legal_form, resolve


def test_clean_merges_spaced_and_dotted_initials():
    assert clean("A.B.C. TRADING") == "ABC TRADING"
    assert clean("A. B. C. TRADING") == "ABC TRADING"
    assert clean("ABC TRADING") == "ABC TRADING"


def test_clean_keeps_single_letters_separated_by_words():
    assert clean("A AND B TRADING") == "A AND B TRADING"


def test_clean_unifies_ampersand_and_apostrophe():
    assert clean("R & J MARICEL'S CATERING") == "R AND J MARICELS CATERING"


def test_clean_abbreviates_legal_forms_without_dropping_them():
    assert clean("ZUELLIG PHARMA CORPORATION") == "ZUELLIG PHARMA CORP"
    assert clean("BEROVAN MARKETING, INC.") == "BEROVAN MARKETING INC"
    assert clean("DEARBORN MOTORS COMPANY, INCORPORATED") == "DEARBORN MOTORS CO INC"


def test_clean_keeps_digits():
    assert clean("3M PHILIPPINES, INC.") == "3M PHILIPPINES INC"


def test_branch_head_requires_a_legal_form_before_the_dash():
    assert branch_head("MERCURY DRUG CORPORATION - MAKATI") == "MERCURY DRUG CORP"
    assert branch_head("MANGAN ELEMENTARY SCHOOL - BANGA, AKLAN") is None
    assert branch_head("MERCURY DRUG CORPORATION") is None


def test_branch_head_ignores_joint_ventures():
    assert branch_head("THREE W BUILDERS INC - ALFREGO BUILDERS JV") is None


def test_branch_head_ignores_hyphens_inside_the_name():
    assert branch_head("UP-TOWN INDUSTRIAL SALES INC") is None
    assert branch_head("TRI-J TRADING") is None


def test_branch_head_accepts_an_unspaced_hyphen_after_the_legal_form():
    assert branch_head("BEROVAN MARKETING, INC.-NAGA") == "BEROVAN MARKETING INC"
    assert branch_head("COPYLANDIA OFFICE SYSTEMS CORPORATION-DAVAO CITY") == "COPYLANDIA OFFICE SYSTEMS CORP"


def test_branch_head_needs_a_name_before_the_legal_form():
    assert branch_head("INC - MAKATI") is None


def test_drop_legal_form_strips_stacked_forms_but_never_everything():
    assert drop_legal_form("DEARBORN MOTORS CO INC") == "DEARBORN MOTORS"
    assert drop_legal_form("INC") == "INC"
    assert drop_legal_form("ABC TRADING") == "ABC TRADING"


def test_level_1_merges_punctuation_variants_only():
    keys = ["A.B.C. TRADING, INC.", "ABC TRADING INC", "ABC TRADING CORPORATION", "ABC TRADING"]
    resolved = resolve(keys, level=1)
    assert resolved["A.B.C. TRADING, INC."] == ("ABC TRADING INC", "ABC TRADING INC", "punctuation")
    assert resolved["ABC TRADING INC"] == ("ABC TRADING INC", "ABC TRADING INC", "identical")
    assert len({match for _, match, _ in resolved.values()}) == 3


def test_level_2_folds_a_branch_into_an_existing_parent():
    keys = ["MERCURY DRUG CORPORATION", "MERCURY DRUG CORPORATION - MAKATI"]
    assert resolve(keys, level=1)["MERCURY DRUG CORPORATION - MAKATI"][1] == "MERCURY DRUG CORP MAKATI"
    resolved = resolve(keys, level=2)
    assert resolved["MERCURY DRUG CORPORATION - MAKATI"] == (
        "MERCURY DRUG CORP MAKATI",
        "MERCURY DRUG CORP",
        "punctuation+branch_suffix",
    )


def test_level_2_leaves_a_branch_alone_when_the_parent_never_appears():
    keys = ["ORPHAN TRADING INC - CEBU", "ORPHAN TRADING INC - DAVAO"]
    resolved = resolve(keys, level=2)
    assert resolved["ORPHAN TRADING INC - CEBU"][1] == "ORPHAN TRADING INC CEBU"
    assert resolved["ORPHAN TRADING INC - DAVAO"][1] == "ORPHAN TRADING INC DAVAO"


def test_level_3_merges_across_legal_forms():
    keys = ["ABC TRADING INC", "ABC TRADING CORPORATION", "ABC TRADING"]
    resolved = resolve(keys, level=3)
    assert {match for _, match, _ in resolved.values()} == {"ABC TRADING"}
    assert resolved["ABC TRADING CORPORATION"][2] == "punctuation+legal_form_dropped"
    assert resolved["ABC TRADING"][2] == "identical"
