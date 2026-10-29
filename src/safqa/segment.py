"""Split contract text into articles so every finding can be cited.

Moroccan CPS / CCAG-T documents are organised as "ARTICLE 12 : DELAI
D'EXECUTION", "Article premier - Objet du marché", "Art. 3." ...  Text
before the first article becomes a "Préambule" pseudo-article.
"""

import re

from .textnum import strip_accents, words_to_int

_ORDINALS = {"premier": 1, "premiere": 1, "unique": 1}

ARTICLE_RE = re.compile(
    r"^[ \t]*(?:ARTICLE|Article|ART\.?|Art\.?)[ \t]+"
    r"(?P<num>\d{1,3}(?:[.\-]\d{1,2})?(?:\s?bis)?|premier|première|PREMIER|PREMIERE|PREMIÈRE|unique|UNIQUE)"
    r"[ \t]*(?:[:.\-–—)]+)?[ \t]*(?P<title>[^\n]{0,160})$",
    re.MULTILINE)

SENTENCE_RE = re.compile(r"(?<=[.;:!?])\s+(?=[A-ZÀ-Ý0-9«\-•])|\n\s*[-•*]\s+|\n{2,}")


class Article:
    __slots__ = ("key", "number", "title", "text", "start", "page")

    def __init__(self, key, number, title, text, start, page):
        self.key = key          # stable id used in citations: "A12"
        self.number = number    # displayed number: "12", "1", "Préambule"
        self.title = title
        self.text = text
        self.start = start      # char offset in the full document
        self.page = page

    def label(self):
        if self.number == "Préambule":
            return "Préambule"
        t = (" - " + self.title) if self.title else ""
        return "Article %s%s" % (self.number, t)

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k) for k in cls.__slots__})


def _norm_num(raw):
    raw = raw.strip()
    key = strip_accents(raw.lower())
    if key in _ORDINALS:
        return "1"
    w = words_to_int(key)
    if w is not None:
        return str(w)
    return raw.replace(" ", "").replace("-", ".")


def _looks_like_reference(line_title):
    """'Article 65 du CCAG-T ...' inside a sentence is not a heading."""
    t = line_title.strip().lower()
    return t.startswith(("du ", "de l", "des ", "de la ", "ci-dessus", "ci-dessous",
                         "et ", "à ", "au ", "alinéa", "paragraphe", ","))


def split_articles(doc):
    """Return a list of Article objects for an ExtractedDoc."""
    text = doc.text
    heads = []
    for m in ARTICLE_RE.finditer(text):
        title = m.group("title").strip()
        if _looks_like_reference(title):
            continue
        # Skip table-of-contents lines: "Article 5 ...... 12"
        if re.search(r"\.{4,}\s*\d+\s*$", title):
            continue
        heads.append((m.start(), m.end(), _norm_num(m.group("num")), title.strip(" :-–—.")))

    articles = []
    used = {}

    def add(number, title, start, body_start, end):
        body = text[body_start:end].replace("\f", "\n").strip()
        if not body:
            body = title
        if not body:
            return
        key = "A" + re.sub(r"[^0-9A-Za-z]", "_", number)
        if key in used:
            used[key] += 1
            key = "%s_%d" % (key, used[key])
        else:
            used[key] = 1
        articles.append(Article(key, number, title, body, start, doc.page_of(start)))

    if not heads:
        # No article structure: chunk by page so citations still point somewhere.
        for i, page in enumerate(doc.pages):
            if page.strip():
                start = doc._starts[i]
                body = page.strip()
                articles.append(Article("P%d" % (i + 1), "Page %d" % (i + 1), "",
                                        body, start, i + 1))
        return articles

    if heads[0][0] > 40:
        pre = text[:heads[0][0]].strip()
        if len(pre) > 40:
            articles.append(Article("A0", "Préambule", "", pre.replace("\f", "\n"), 0, 1))
    for i, (s, e, num, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        add(num, title, s, e, end)
    return articles


def sentences(text):
    parts = SENTENCE_RE.split(text)
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p or "").strip()
        if len(p) > 3:
            out.append(p)
    return out


def normalize_for_match(text):
    t = strip_accents(text.lower())
    t = re.sub(r"[’'`]", "'", t)
    return re.sub(r"[^a-z0-9%']+", " ", t).strip()


def quote_in_text(quote, text):
    """True if `quote` appears (modulo spacing/accents/punctuation) in text."""
    q = normalize_for_match(quote)
    if not q:
        return False
    return q in normalize_for_match(text)
