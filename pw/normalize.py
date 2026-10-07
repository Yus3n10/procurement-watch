"""Fold agency and supplier names to a comparable ASCII key.

The source contains names typed with Greek or Cyrillic letters that render
identically to Latin ones, mathematical bold alphabets, and stray accents.
A plain GROUP BY treats each of those as a different entity.
"""

import re
import unicodedata

# Greek and Cyrillic letters that are visually identical to a Latin letter.
_CONFUSABLES = {
    # Greek capitals
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    # Greek lowercase
    "ο": "o", "ι": "i", "κ": "k", "ν": "v", "ρ": "p", "α": "a",
    # Cyrillic capitals
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J",
    "Ѕ": "S",
    # Cyrillic lowercase
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "і": "i", "ј": "j", "ѕ": "s",
}

# Latin letters that NFKD does not decompose to ASCII.
_LATIN_EXTRAS = {
    "Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe",
    "ß": "ss", "Đ": "D", "đ": "d", "Ł": "L", "ł": "l", "ı": "i",
}


# HTML entities left in the source by an upstream export. Listed explicitly:
# a general unescape would also rewrite real text such as "PRINT&COPY".
_ENTITIES = {"&amp;": "&", "&nbsp;": " ", "&gt;": ">", "&lt;": "<", "&quot;": '"', "&#39;": "'"}
_ENTITY = re.compile("|".join(re.escape(entity) for entity in _ENTITIES), re.IGNORECASE)


def fold(name: str) -> tuple[str, int, int]:
    """Return (key, confusables_replaced, letters_dropped).

    letters_dropped counts letters with no ASCII equivalent in the maps above.
    A non-zero value means the key is lossy and the maps need extending.
    """
    text = _ENTITY.sub(lambda match: _ENTITIES[match.group(0).lower()], name)
    text = unicodedata.normalize("NFKC", text)
    confusables = 0
    mapped = []
    for ch in text:
        if ch in _CONFUSABLES:
            mapped.append(_CONFUSABLES[ch])
            confusables += 1
        else:
            mapped.append(_LATIN_EXTRAS.get(ch, ch))
    text = unicodedata.normalize("NFKD", "".join(mapped))

    dropped = 0
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
            continue
        category = unicodedata.category(ch)
        if category.startswith("M"):
            continue
        if category.startswith("L"):
            dropped += 1
        out.append(" ")
    key = " ".join("".join(out).upper().split())
    return key, confusables, dropped


def name_key(name: str) -> str:
    return fold(name)[0]

