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


# --------------------------------------------------------------------------
# Numbers to French words (amounts "en toutes lettres")
# --------------------------------------------------------------------------

_W_UNITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
            "onze", "douze", "treize", "quatorze", "quinze", "seize"]
_W_TENS = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante"}


def _below_100(n, final=True):
    if n < 17:
        return _W_UNITS[n]
    if n < 20:
        return "dix-" + _W_UNITS[n - 10]
    if n < 70:
        tens, unit = n // 10 * 10, n % 10
        if unit == 0:
            return _W_TENS[tens]
        if unit == 1:
            return _W_TENS[tens] + " et un"
        return _W_TENS[tens] + "-" + _W_UNITS[unit]
    if n < 80:
        if n == 71:
            return "soixante et onze"
        return "soixante-" + _below_100(n - 60)
    if n == 80:
        return "quatre-vingts" if final else "quatre-vingt"
    return "quatre-vingt-" + _below_100(n - 80)


def _below_1000(n, final=True):
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _below_100(rest, final)
    head = "cent" if hundreds == 1 else _W_UNITS[hundreds] + " cent"
    if rest == 0:
        return head + ("s" if hundreds > 1 and final else "")
    return head + " " + _below_100(rest, final)


def int_to_words(n):
    """French cardinal for an integer >= 0 ("deux cent quarante-cinq mille")."""
    n = int(n)
    if n == 0:
        return "zéro"
    parts = []
    for scale, singular, plural in ((10**9, "milliard", "milliards"), (10**6, "million", "millions")):
        q, n = divmod(n, scale)
        if q:
            parts.append("un " + singular if q == 1 else _below_1000(q) + " " + plural)
    q, n = divmod(n, 1000)
    if q:
        parts.append("mille" if q == 1 else _below_1000(q, final=False) + " mille")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def amount_in_words(value, currency="dirham", cents_name="centime"):
    """'2 450 000,50' -> 'deux millions quatre cent cinquante mille dirhams et cinquante centimes'."""
    value = round(float(value or 0), 2)
    neg = value < 0
    value = abs(value)
    whole = int(value)
    cents = int(round((value - whole) * 100))
    if cents == 100:
        whole, cents = whole + 1, 0
    text = int_to_words(whole) + " " + currency + ("s" if whole > 1 else "")
    if cents:
        text += " et " + int_to_words(cents) + " " + cents_name + ("s" if cents > 1 else "")
    return ("moins " if neg else "") + text
