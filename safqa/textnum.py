"""Parsing of French numbers and amounts as written in Moroccan contracts.

Contracts usually state figures twice: "trente (30) jours", or an amount in
letters followed by the amount in digits.  These helpers convert both forms
so the rule engine can compare them.
"""

import re
import unicodedata

_UNITS = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
    "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
    "seize": 16, "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40,
    "cinquante": 50, "soixante": 60, "septante": 70, "huitante": 80,
    "octante": 80, "nonante": 90, "cent": 100, "cents": 100,
}
_SCALES = {"mille": 1000, "milles": 1000, "million": 10**6, "millions": 10**6,
           "milliard": 10**9, "milliards": 10**9}
_IGNORED = {"et", "virgule"}


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def words_to_int(text):
    """Convert French number words to an int ("cent vingt" -> 120).

    Returns None when the text contains no number word.
    """
    tokens = re.split(r"[\s\-]+", strip_accents(text.lower()).strip())
    total, current, seen = 0, 0, False
    for tok in tokens:
        if not tok:
            continue
        if tok in _IGNORED:
            continue
        if tok in _UNITS:
            val = _UNITS[tok]
            seen = True
            if val == 100:
                current = (current or 1) * 100
            elif current and current % 100 == 4 and val == 20:
                # quatre-vingt(s)
                current = current - 4 + 80
            else:
                current += val
        elif tok in _SCALES:
            seen = True
            total += (current or 1) * _SCALES[tok]
            current = 0
        else:
            return None
    if not seen:
        return None
    return total + current


_WORD_ALT = "|".join(sorted(set(list(_UNITS) + list(_SCALES) + ["et"]),
                            key=len, reverse=True))
NUMBER_WORDS_RE = re.compile(
    r"\b(?:(?:%s)(?:[\s\-]+|$))+" % _WORD_ALT, re.IGNORECASE)


def parse_decimal(text):
    """Parse '1 234 567,89' / '1.234.567,89' / '1234567.89' into a float."""
    s = text.strip().replace(" ", " ").replace(" ", " ")
    s = s.replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s and len(s.split(".")[1]) == 3:
        # 1.250 -> thousands separator
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


AMOUNT_RE = re.compile(
    r"(?P<num>\d{1,3}(?:[ .  ]\d{3})+(?:,\d{1,2})?|\d+(?:[,.]\d{1,2})?)"
    r"\s*(?P<cur>DH|MAD|dirhams?)\b(?:\s*(?P<tax>TTC|HT|hors\s+taxes?|toutes\s+taxes\s+comprises))?",
    re.IGNORECASE)


def find_amounts(text):
    """Return [(value, tax_flag, span)] for amounts expressed in dirhams."""
    out = []
    for m in AMOUNT_RE.finditer(text):
        val = parse_decimal(m.group("num"))
        if val is None:
            continue
        tax = (m.group("tax") or "").upper()
        if tax.startswith("TOUTES"):
            tax = "TTC"
        elif tax.startswith("HORS"):
            tax = "HT"
        out.append((val, tax, m.span()))
    return out


def letters_amount_before(text, end):
    """Find an amount written in letters just before position `end`."""
    window = text[max(0, end - 260):end]
    best = None
    for m in NUMBER_WORDS_RE.finditer(window):
        best = m
    if not best:
        return None
    return words_to_int(best.group(0))


def fmt_dh(value, decimals=2):
    """Format a number the Moroccan way: 1 234 567,89 DH."""
    if value is None:
        return "-"
    neg = value < 0
    s = ("%." + str(decimals) + "f") % abs(value)
    if "." in s:
        ent, dec = s.split(".")
    else:
        ent, dec = s, ""
    groups = []
    while len(ent) > 3:
        groups.insert(0, ent[-3:])
        ent = ent[:-3]
    groups.insert(0, ent)
    out = " ".join(groups) + ("," + dec if dec else "")
    return ("-" if neg else "") + out + " DH"
