from pw.normalize import fold, name_key


def test_plain_ascii_is_uppercased_and_collapsed():
    assert name_key("  Province  of Negros   Occidental ") == "PROVINCE OF NEGROS OCCIDENTAL"


def test_greek_rho_folds_to_latin_p():
    key, confusables, dropped = fold("ΡROVINCE OF NEGROS OCCIDENTAL")
    assert key == "PROVINCE OF NEGROS OCCIDENTAL"
    assert confusables == 1
    assert dropped == 0


def test_cyrillic_and_accents_fold_to_the_same_key():
    assert name_key("РRÒVINCE OF NÈGROS OCCÏDENTAL") == "PROVINCE OF NEGROS OCCIDENTAL"


def test_enye_folds_to_n():
    assert name_key("Parañaque City") == "PARANAQUE CITY"


def test_mathematical_bold_folds_to_ascii():
    assert name_key("\U0001d411\U0001d408\U0001d402\U0001d404") == "RICE"


def test_typographic_quotes_become_spaces_not_letters():
    key, _, dropped = fold("“K” LINE LOGISTICS")
    assert key == "K LINE LOGISTICS"
    assert dropped == 0


def test_unmappable_letter_is_counted_as_dropped():
    key, _, dropped = fold("中 ABC")
    assert key == "ABC"
    assert dropped == 1


def test_ascii_punctuation_is_preserved():
    assert name_key("A.B.C. Trading, Inc.") == "A.B.C. TRADING, INC."


def test_html_entities_are_decoded():
    assert name_key("POWER SIGNS &AMP; ADS") == name_key("POWER SIGNS & ADS") == "POWER SIGNS & ADS"
    assert name_key("ABC&nbsp;TRADING") == "ABC TRADING"


def test_text_that_only_resembles_an_entity_is_left_alone():
    assert name_key("PRINT&COPY CENTER") == "PRINT&COPY CENTER"
