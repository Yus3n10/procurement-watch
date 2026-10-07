"""Rule-based supplier name matching.

Every rule is deterministic and named, so each merge in the alias table can
be traced to the rule that caused it. Rules are grouped into levels of
increasing risk; the level in use is chosen from measured precision.

    level 1  punctuation, initials, and legal-form abbreviations
    level 2  level 1, plus a branch suffix folded into its parent company
    level 3  level 2, plus the legal form dropped entirely
"""

import re

LEGAL_ABBREVIATIONS = {
    "INCORPORATED": "INC",
    "CORPORATION": "CORP",
    "COMPANY": "CO",
    "LIMITED": "LTD",
}
LEGAL_FORMS = {"INC", "CORP", "CO", "LTD", "OPC"}

_JOINT_VENTURE = re.compile(r"\bJV\b|\bJOINT VENTURE\b|\bCONSORTIUM\b")
# "COMPANY INC - BRANCH". The hyphen may be unspaced only when it directly
# follows the legal form ("INC.-NAGA"), so "UP-TOWN SALES INC" is not split.
_BRANCH = re.compile(
    r"^(?P<head>.*\b(?:INC|INCORPORATED|CORP|CORPORATION|COMPANY|LTD|LIMITED|OPC)\b[.,]?)"
    r"\s*-\s*(?P<tail>\S.*)$"
)


def clean(key: str) -> str:
    """Level 1: remove punctuation noise without changing which words are present."""
    text = key.replace("&", " AND ").replace("'", "")
    tokens = re.sub(r"[^A-Z0-9 ]", " ", text).split()

    # "A.B.C. TRADING", "A. B. C. TRADING" and "ABC TRADING" all become "ABC TRADING".
    merged: list[str] = []
    run = ""
    for token in tokens:
        if len(token) == 1 and token.isalpha():
            run += token
            continue
        if run:
            merged.append(run)
            run = ""
        merged.append(token)
    if run:
        merged.append(run)
    return " ".join(LEGAL_ABBREVIATIONS.get(token, token) for token in merged)


def branch_head(key: str) -> str | None:
    """Return the cleaned parent name if key looks like 'COMPANY INC - BRANCH'.

    Only a head that ends in a legal form qualifies. Schools, barangays and
    government offices use the same dash for their town, and their names
    repeat across towns, so folding those would merge unrelated entities.
    """
    if _JOINT_VENTURE.search(key):
        return None
    match = _BRANCH.match(key)
    if not match or len(match.group("head").split()) < 2:
        return None
    return clean(match.group("head"))


def drop_legal_form(cleaned: str) -> str:
    tokens = cleaned.split()
    while len(tokens) > 1 and tokens[-1] in LEGAL_FORMS:
        tokens.pop()
    return " ".join(tokens)


def resolve(keys: list[str], level: int) -> dict[str, tuple[str, str, str]]:
    """Map each folded name key to (clean_key, match_key, rule)."""
    cleaned = {key: clean(key) for key in keys}
    heads = {key: branch_head(key) for key in keys} if level >= 2 else {}
    # A branch is only folded into a parent that appears under its own name.
    parents = set(cleaned.values())

    resolved = {}
    for key in keys:
        match_key = cleaned[key]
        rules = []
        if match_key != key:
            rules.append("punctuation")
        head = heads.get(key)
        if head and head in parents:
            match_key = head
            rules.append("branch_suffix")
        if level >= 3:
            dropped = drop_legal_form(match_key)
            if dropped != match_key:
                match_key = dropped
                rules.append("legal_form_dropped")
        resolved[key] = (cleaned[key], match_key, "+".join(rules) or "identical")
    return resolved
