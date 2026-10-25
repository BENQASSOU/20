"""Offline rule engine: extracts obligations, deadlines, penalties and
financial terms from a segmented contract, each with its article citation.

It works without network access.  The AI pass (ai.py) adds what rules
cannot catch, and both results are merged in analysis.py.
"""

import re

from . import regulation as reg
from .segment import sentences
from .textnum import (NUMBER_WORDS_RE, find_amounts, letters_amount_before,
                      parse_decimal, strip_accents, words_to_int)

# --------------------------------------------------------------------------
# Durations
# --------------------------------------------------------------------------

_UNIT = r"(?P<u>jours?|mois|semaines?|ans|années?|annee?s?|heures?)"
DUR_DIGITS_RE = re.compile(r"(?<![\d/])(?P<n>\d{1,4})\s*\)?\s*" + _UNIT +
                           r"(?P<q>\s+(?:calendaires?|ouvrables?|francs?|ouvrés?))?",
                           re.IGNORECASE)
DUR_WORDS_RE = re.compile(r"(?<!\w)(?P<w>" + NUMBER_WORDS_RE.pattern[2:] + r")\s*" + _UNIT +
                          r"(?P<q>\s+(?:calendaires?|ouvrables?|francs?|ouvrés?))?",
                          re.IGNORECASE)
TRIGGER_RE = re.compile(
    r"(?P<k>à compter d[eu']|a compter d[eu']|à partir d[eu']|a partir d[eu']|suivant|"
    r"qui suit|qui suivent|après|apres|avant|dès|des la|dès la|dès le|de la date d[eu'])\s*"
    r"(?P<ev>[^.;:]{3,110})", re.IGNORECASE)


def _unit_days(unit, n):
    u = strip_accents(unit.lower())
    if u.startswith("jour"):
        return n
    if u.startswith("semaine"):
        return 7 * n
    if u.startswith("mois"):
        return 30 * n
    if u.startswith("an"):
        return 365 * n
    if u.startswith("heure"):
        return max(1, round(n / 24.0))
    return n


def find_durations(sentence):
    """Return [{n, unit, days, months, qualifier, span}] for a sentence."""
    found = []
    for m in DUR_DIGITS_RE.finditer(sentence):
        n = int(m.group("n"))
        if n == 0:
            continue
        found.append((m.span(), n, m.group("u"), (m.group("q") or "").strip()))
    for m in DUR_WORDS_RE.finditer(sentence):
        if any(s <= m.start() < e or m.start() <= s < m.end() for (s, e), *_ in found):
            continue
        n = words_to_int(m.group("w"))
        if n:
            found.append((m.span(), n, m.group("u"), (m.group("q") or "").strip()))
    out = []
    for span, n, unit, q in sorted(found):
        u = strip_accents(unit.lower())
        months = n if u.startswith("mois") else (12 * n if u.startswith("an") else None)
        out.append({"n": n, "unit": unit.lower(), "days": _unit_days(unit, n),
                    "months": months, "qualifier": q.lower(), "span": span})
    return out


def find_trigger(sentence, after=0):
    m = TRIGGER_RE.search(sentence, after)
    if not m:
        m = TRIGGER_RE.search(sentence)
    if not m:
        return ""
    ev = m.group("ev").strip(" ,")
    return (m.group("k") + " " + ev).strip()


# --------------------------------------------------------------------------
# Percentages and rates
# --------------------------------------------------------------------------

PCT_RE = re.compile(r"(?P<n>\d{1,3}(?:[,.]\d{1,3})?)\s*(?:%|pour\s*cent|p\.?\s?100)", re.IGNORECASE)
PCT_WORDS_RE = re.compile(r"(?<!\w)(?P<w>" + NUMBER_WORDS_RE.pattern[2:] + r")\s*pour\s*cent", re.IGNORECASE)
PERMILLE_RE = re.compile(r"(?P<n>\d{1,3}(?:[,.]\d{1,3})?)\s*(?:‰|pour\s*mille|p\.?\s?1000)", re.IGNORECASE)
FRACTION_RE = re.compile(r"(?<![\d/])(?P<a>\d{1,3})\s*/\s*(?P<b>\d{2,5})(?![\d/])")
MILLIEME_RE = re.compile(r"\b(?P<w>un|une|deux|trois|quatre|cinq|dix)?\s*(?P<k>milli[eè]mes?|centi[eè]mes?|dix-milli[eè]mes?)\b",
                         re.IGNORECASE)
CAP_RE = re.compile(
    r"(?:plafonn\w*|ne\s+(?:peut|pourra|doit|saurait)\s+(?:pas\s+)?(?:dépasser|depasser|excéder|exceder|être supérieur)|"
    r"limité\w*|limite\w*|maximum|dans la limite|n'excédant pas|sans dépasser|sans depasser|"
    r"cesse de cro\w+|atteint|à concurrence de|a concurrence de)"
    r"[^.%]{0,90}?(?P<n>\d{1,3}(?:[,.]\d{1,2})?)\s*(?:%|pour\s*cent)", re.IGNORECASE)


def percentages(sentence):
    vals = []
    for m in PCT_RE.finditer(sentence):
        v = parse_decimal(m.group("n"))
        if v is not None and 0 < v <= 100:
            vals.append((v, m.span()))
    for m in PCT_WORDS_RE.finditer(sentence):
        v = words_to_int(m.group("w"))
        if any(abs(pv - (v or -1)) < 1e-9 and abs(s - m.end()) < 12 for pv, (s, e) in vals):
            continue
        if v and 0 < v <= 100:
            vals.append((float(v), m.span()))
    return sorted(vals, key=lambda x: x[1])


def daily_rate(sentence):
    """Penalty rate expressed as a fraction of the base per day."""
    m = FRACTION_RE.search(sentence)
    if m:
        a, b = int(m.group("a")), int(m.group("b"))
        if b in (100, 1000, 2000, 500, 10000) and 0 < a < b:
            return a / float(b)
    m = PERMILLE_RE.search(sentence)
    if m:
        v = parse_decimal(m.group("n"))
        if v:
            return v / 1000.0
    m = MILLIEME_RE.search(sentence)
    if m:
        n = words_to_int(m.group("w") or "un") or 1
        k = strip_accents(m.group("k").lower())
        base = 10000.0 if k.startswith("dix") else (1000.0 if k.startswith("mill") else 100.0)
        return n / base
    for v, _ in percentages(sentence):
        if v <= 2 and re.search(r"par\s+jour|journali", sentence, re.IGNORECASE):
            return v / 100.0
    return None


def cap_pct(sentence):
    m = CAP_RE.search(sentence)
    if m:
        return parse_decimal(m.group("n"))
    return None


# --------------------------------------------------------------------------
# Parties
# --------------------------------------------------------------------------

PARTY_PATTERNS = [
    ("Titulaire", r"\b(?:l'entrepreneur|l’entrepreneur|le titulaire|l'entreprise|l’entreprise|le prestataire|"
                  r"le cocontractant|l'attributaire|le soumissionnaire|le concurrent|le groupement|le mandataire)\b"),
    ("Maître d'ouvrage", r"\b(?:le maître d'ouvrage|le maitre d'ouvrage|le maître d’ouvrage|l'administration|"
                         r"l’administration|le maître d'ouvrage délégué|l'autorité compétente|le sous-ordonnateur|"
                         r"l'ordonnateur|la commune|le ministère|l'office)\b"),
    ("Maître d'œuvre", r"\b(?:le maître d'œuvre|le maître d'oeuvre|le maitre d'oeuvre|le bureau d'études|"
                       r"le bureau d'études|le BET|le bureau de contrôle|le laboratoire|l'architecte)\b"),
]
_PARTY_RES = [(name, re.compile(p, re.IGNORECASE)) for name, p in PARTY_PATTERNS]

OBLIGATION_RE = re.compile(
    r"\b(?:doit|doivent|devra|devront|est tenu|sont tenus|est tenue|sera tenu|seront tenus|"
    r"s'engage|s’engage|s'oblige|il incombe|incombe|est chargé|sera chargé|a l'obligation|"
    r"est astreint|sont à la charge|est à la charge|demeure responsable|reste responsable|"
    r"est responsable|sont dus|fournira|remettra|soumettra|établira|procédera|veillera)\b",
    re.IGNORECASE)
NEG_OBLIGATION_RE = re.compile(r"\b(?:ne\s+(?:doit|peut|pourra|devra)|il est interdit|est interdit|interdit)\b",
                               re.IGNORECASE)


def party_of(sentence):
    """Return the party bearing the obligation: the first one named before
    the modal verb, else the first one named."""
    mod = OBLIGATION_RE.search(sentence) or NEG_OBLIGATION_RE.search(sentence)
    cut = mod.start() if mod else len(sentence)
    best = None
    for name, rx in _PARTY_RES:
        for m in rx.finditer(sentence):
            if m.start() <= cut and (best is None or m.start() > best[0]):
                best = (m.start(), name)
            break
    if best:
        return best[1]
    for name, rx in _PARTY_RES:
        if rx.search(sentence):
            return name
    return "Non précisé"


# --------------------------------------------------------------------------
# Categorisation
# --------------------------------------------------------------------------

CATEGORIES = [
    ("Pénalités", ("pénalit", "penalit", "amende", "retenue journali")),
    ("Cautionnement", ("cautionnement", "caution ")),
    ("Retenue de garantie", ("retenue de garantie",)),
    ("Assurances", ("assurance", "assuré", "police")),
    ("Délais", ("délai", "delai", "planning", "calendrier")),
    ("Paiement", ("paiement", "décompte", "decompte", "acompte", "avance", "facture", "règlement des sommes")),
    ("Prix", ("révision des prix", "prix révisables", "prix fermes", "actualisation", "bordereau des prix")),
    ("Réception", ("réception", "reception", "réserves", "recolement", "récolement")),
    ("Personnel & chantier", ("personnel", "chantier", "hygiène", "sécurité", "signalisation", "installation")),
    ("Qualité & essais", ("essai", "laboratoire", "contrôle", "conformité", "matériaux", "agrément")),
    ("Documents", ("plans d'exécution", "dossier", "attestation", "remettre", "fournir", "présenter")),
    ("Sous-traitance", ("sous-trait",)),
    ("Résiliation", ("résiliation", "resiliation", "mise en demeure", "coercitive")),
    ("Litiges", ("litige", "différend", "tribunal", "contestation")),
]


def categorize(text, title=""):
    blob = (title + " " + text).lower()
    tl = title.lower()
    for name, keys in CATEGORIES:
        if any(k in tl for k in keys):
            return name
    for name, keys in CATEGORIES:
        if any(k in blob for k in keys):
            return name
    return "Général"


DEADLINE_KINDS = [
    ("execution", "Délai d'exécution", ("délai d'exécution", "delai d'execution", "délai global", "délai contractuel")),
    ("garantie", "Délai de garantie", ("délai de garantie", "delai de garantie", "période de garantie")),
    ("caution_def", "Constitution du cautionnement définitif", ("cautionnement définitif", "cautionnement definitif",
                                                                "doit être constitué", "et définitif")),
    ("paiement", "Délai de paiement", ("paiement", "mandatement", "ordonnancement", "intérêts moratoires")),
    ("os_commencement", "Ordre de service de commencement", ("ordre de service de commencement", "commencement des travaux")),
    ("assurance", "Remise des attestations d'assurance", ("assurance",)),
    ("programme", "Remise du programme d'exécution", ("programme", "planning", "calendrier d'exécution")),
    ("plans", "Remise des plans / études d'exécution", ("plans d'exécution", "études d'exécution", "notes de calcul")),
    ("reclamation", "Réclamations / contestations", ("réclamation", "reclamation", "réserves", "contestation", "observations")),
    ("reception", "Réception", ("réception", "reception")),
    ("decompte", "Décompte", ("décompte", "decompte", "attachement")),
    ("preavis", "Préavis / mise en demeure", ("mise en demeure", "préavis", "preavis")),
]


def deadline_kind(sentence, title="", upto=None):
    """Classify a deadline: first on the words before the duration (its
    subject), then the whole sentence, then the article title."""
    scopes = [sentence[:upto] if upto else sentence, sentence, title]
    for scope in scopes:
        sc = strip_accents(scope.lower())
        for code, label, keys in DEADLINE_KINDS:
            if any(strip_accents(k) in sc for k in keys):
                return code, label
    return "autre", "Délai"


RISKY_CLAUSES = [
    ("à ses frais", "Coût à la charge du titulaire"),
    ("a ses frais", "Coût à la charge du titulaire"),
    ("à sa charge", "Coût à la charge du titulaire"),
    ("à ses risques et périls", "Transfert de risque au titulaire"),
    ("sans indemnité", "Aucune indemnisation prévue"),
    ("sans indemnite", "Aucune indemnisation prévue"),
    ("ne pourra prétendre", "Renonciation à réclamation / indemnité"),
    ("ne peut prétendre", "Renonciation à réclamation / indemnité"),
    ("aucune réclamation", "Renonciation à réclamation"),
    ("aucune indemnité", "Aucune indemnisation prévue"),
    ("sans mise en demeure", "Sanction sans mise en demeure préalable"),
    ("de plein droit", "Application automatique (de plein droit)"),
    ("solidairement", "Responsabilité solidaire"),
    ("forfaitaire", "Prix ou pénalité forfaitaire"),
    ("réputé avoir pris connaissance", "Présomption de connaissance des lieux/sujétions"),
    ("toutes sujétions", "Sujétions incluses dans les prix"),
]

DEROGATION_RE = re.compile(r"(?:par\s+)?dérogation|derogation|contrairement\s+(?:aux|à)\s+(?:dispositions|l'article)",
                           re.IGNORECASE)
CCAG_REF_RE = re.compile(r"article\s+(?P<n>\d{1,3})\s+(?:du|de\s+l[a'])?\s*(?:CCAG[\s\-]?T|CCAGT|cahier des clauses administratives générales)",
                         re.IGNORECASE)

DOC_KEYWORDS = [
    "attestation d'assurance", "police d'assurance", "cautionnement définitif", "caution personnelle",
    "programme d'exécution", "planning", "plans d'exécution", "notes de calcul", "dossier de récolement",
    "plans de récolement", "journal de chantier", "cahier de chantier", "attachement", "métré",
    "procès-verbal", "pv de réception", "fiches techniques", "échantillons", "rapport", "attestation",
    "certificat", "plan d'installation de chantier", "plan hygiène", "plan de sécurité", "décompte",
]

# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def _finding(kind, article, sentence, summary, category=None, party=None, value=None, severity=None):
    return {
        "kind": kind,
        "category": category or categorize(sentence, article.title),
        "party": party or party_of(sentence),
        "summary": summary,
        "text": sentence,
        "article_key": article.key,
        "article_label": article.label(),
        "page": article.page,
        "value": value or {},
        "severity": severity,
        "source": "règles",
        "verified": True,
    }


def _short(sentence, n=160):
    s = sentence.strip()
    return s if len(s) <= n else s[:n - 1].rsplit(" ", 1)[0] + "…"


def _term(terms, key, value, article, sentence):
    terms.setdefault(key, []).append({
        "value": value, "article_key": article.key, "article_label": article.label(),
        "page": article.page, "text": sentence})


def extract(articles):
    """Run every rule on every sentence.

    Returns dict(findings=[...], terms={key: [occurrences]}).
    """
    findings = []
    terms = {}
    for art in articles:
        title_l = (art.title or "").lower()
        for sent in sentences(art.text):
            low = sent.lower()
            lowa = strip_accents(low)

            durations = find_durations(sent)
            is_penalty = bool(re.search(r"pénalit|penalit|amende|retenue journali", low))

            # ---- penalties
            if is_penalty:
                rate = daily_rate(sent)
                cap = cap_pct(sent)
                amounts = find_amounts(sent)
                per_day_amount = None
                if amounts and re.search(r"par\s+jour|journali", low):
                    per_day_amount = amounts[0][0]
                base = ""
                for b in ("montant initial", "montant du marché", "montant global", "montant des travaux",
                          "montant de la tranche", "montant du lot", "montant de l'avenant"):
                    if b in low:
                        base = b
                        break
                pkind = "retard" if ("retard" in low or "délai" in low or "retard" in title_l) else "autre"
                per_unit = re.search(r"(\d[\d .,]*)\s*(?:DH|dirhams?)\s+par\s+(\w+)", sent, re.IGNORECASE)
                if per_unit and not per_day_amount:
                    pkind = "autre" if "jour" not in per_unit.group(2).lower() else pkind
                parts = []
                if rate:
                    parts.append("taux %s/jour" % _fmt_rate(rate))
                if per_day_amount:
                    parts.append("%s DH/jour" % _fmt_num(per_day_amount))
                if cap is not None:
                    parts.append("plafond %s %%" % _fmt_num(cap))
                if per_unit and not per_day_amount:
                    parts.append("%s DH par %s" % (_fmt_num(parse_decimal(per_unit.group(1))), per_unit.group(2)))
                summary = "Pénalité %s%s" % ("de retard" if pkind == "retard" else "",
                                             (" : " + ", ".join(parts)) if parts else "")
                if parts:
                    findings.append(_finding(
                        "penalty", art, sent, summary.replace("  ", " "),
                        category="Pénalités", party="Titulaire",
                        value={"rate_per_day": rate, "cap_pct": cap, "base": base,
                               "amount_per_day": per_day_amount, "type": pkind}))
                if pkind == "retard" and rate:
                    _term(terms, "penalty_rate_per_day", rate, art, sent)
                if cap is not None and pkind == "retard":
                    _term(terms, "penalty_cap_pct", cap, art, sent)
                elif cap is not None:
                    _term(terms, "penalty_other_cap_pct", cap, art, sent)

            # ---- deadlines
            if durations and not is_penalty:
                for d in durations:
                    code, label = deadline_kind(sent, art.title, d["span"][0])
                    if strip_accents(d["unit"]).startswith("heure") and d["n"] > 72:
                        continue
                    trig = find_trigger(sent, d["span"][1])
                    summary = "%s : %d %s%s" % (label, d["n"], d["unit"],
                                                (" " + d["qualifier"]) if d["qualifier"] else "")
                    if trig:
                        summary += " (" + trig + ")"
                    findings.append(_finding("deadline", art, sent, summary, category="Délais",
                                             value={"kind": code, "n": d["n"], "unit": d["unit"],
                                                    "days": d["days"], "months": d["months"],
                                                    "trigger": trig}))
                    if code == "execution" and ("exécution" in low or "execution" in lowa or "exécution" in title_l):
                        _term(terms, "execution_delay_days", d["days"], art, sent)
                        if d["months"]:
                            _term(terms, "execution_delay_months", d["months"], art, sent)
                    elif code == "garantie":
                        months = d["months"] or round(d["days"] / 30.0)
                        _term(terms, "warranty_months", months, art, sent)
                    elif code == "paiement" and d["days"] <= 180:
                        _term(terms, "payment_delay_days", d["days"], art, sent)
                    elif code == "caution_def":
                        _term(terms, "caution_definitive_delay_days", d["days"], art, sent)
                    break  # one finding per sentence keeps lists readable

            # ---- financial terms
            pcts = percentages(sent)
            topic_src = low if re.search(r"retenue de garantie|cautionnement|avance", low) else strip_accents(title_l)
            topic_src = strip_accents(topic_src)
            if "retenue de garantie" in topic_src and pcts:
                cap = cap_pct(sent)
                for v, _ in pcts:
                    if cap is not None and abs(v - cap) < 1e-9:
                        continue
                    _term(terms, "retenue_rate_pct", v, art, sent)
                    break
                if cap is not None:
                    _term(terms, "retenue_cap_pct", cap, art, sent)
                rates = sorted(set(v for v, _ in pcts if cap is None or abs(v - cap) > 1e-9))
                label = ", ".join("%s %%" % _fmt_num(v) for v in rates)
                if cap is not None:
                    label = (label + ", " if label else "") + "plafond %s %%" % _fmt_num(cap)
                findings.append(_finding("financial", art, sent, "Retenue de garantie : " + label,
                    category="Retenue de garantie",
                    party="Titulaire", value={"pcts": [v for v, _ in pcts], "cap_pct": cap}))
            elif re.search(r"cautionnement\s+definitif", topic_src) and pcts and "provisoire" not in low:
                _term(terms, "caution_definitive_pct", pcts[0][0], art, sent)
                findings.append(_finding("financial", art, sent, "Cautionnement définitif : %s %%" %
                                         _fmt_num(pcts[0][0]), category="Cautionnement", party="Titulaire",
                                         value={"pct": pcts[0][0]}))
            elif re.search(r"cautionnement\s+provisoire", low):
                amts = find_amounts(sent)
                if amts:
                    _term(terms, "caution_provisoire_dh", amts[0][0], art, sent)
                    findings.append(_finding("financial", art, sent, "Cautionnement provisoire : %s DH" %
                                             _fmt_num(amts[0][0]), category="Cautionnement",
                                             party="Titulaire", value={"amount": amts[0][0]}))
            if re.search(r"\bavance\b", low) and pcts and "retenue" not in low:
                _term(terms, "advance_pct", pcts[0][0], art, sent)
                findings.append(_finding("financial", art, sent, "Avance : %s %%" % _fmt_num(pcts[0][0]),
                                         category="Paiement", party="Maître d'ouvrage",
                                         value={"pct": pcts[0][0]}))

            _pp = r"prix\b(?:[^.;]{0,50}?\b(?:sont|seront|est)\s+)?\s*"
            if re.search(_pp + r"(?:fermes?|non\s+revisables?)\b", lowa):
                _term(terms, "price_type", "ferme", art, sent)
            elif re.search(_pp + r"revisables?\b|revision\s+des\s+prix\s+(?:est|sera)\s+(?:applicable|appliqu)", lowa):
                _term(terms, "price_type", "révisable", art, sent)
            elif re.search(_pp + r"actualisables?\b", lowa):
                _term(terms, "price_type", "actualisable", art, sent)

            # contract amount (+ letters/digits consistency)
            if re.search(r"montant|arrêté|arrete|somme", lowa):
                for val, tax, (s, e) in find_amounts(sent):
                    if val < 1000:
                        continue
                    letters = letters_amount_before(sent, s)
                    if tax == "TTC" and re.search(r"montant (?:total |global )?(?:du (?:présent )?marché|de l'offre|des travaux)|arrêté", lowa + " " + low):
                        _term(terms, "contract_amount_ttc", val, art, sent)
                    if letters and letters >= 1000 and abs(letters - int(val)) > 1:
                        findings.append(_finding(
                            "inconsistency", art, sent,
                            "Montant en lettres (%s DH) différent du montant en chiffres (%s DH)" % (
                                _fmt_num(letters), _fmt_num(val)),
                            category="Paiement", party="Non précisé", severity="élevé",
                            value={"letters": letters, "digits": val}))

            # ---- derogations to the CCAG-T
            if DEROGATION_RE.search(sent):
                refs = [m.group("n") for m in CCAG_REF_RE.finditer(sent)]
                findings.append(_finding(
                    "derogation", art, sent,
                    "Dérogation" + (" à l'article %s du CCAG-T" % ", ".join(refs) if refs else " au cadre général"),
                    category="Dérogations", party="Non précisé", severity="moyen",
                    value={"ccag_articles": refs}))

            # ---- risky clauses
            for key, label in RISKY_CLAUSES:
                if key in low:
                    findings.append(_finding("risky_clause", art, sent, label, party="Titulaire",
                                             severity="moyen", value={"keyword": key}))
                    break

            # ---- obligations
            if OBLIGATION_RE.search(sent) or NEG_OBLIGATION_RE.search(sent):
                neg = bool(NEG_OBLIGATION_RE.search(sent)) and not OBLIGATION_RE.search(sent)
                party = party_of(sent)
                if party == "Non précisé" and re.search(r"paiement|mandatement|ordonnancement|se libérera", low):
                    party = "Maître d'ouvrage"
                findings.append(_finding("obligation" if not neg else "prohibition", art, sent,
                                         _short(sent), party=party,
                                         value={"has_deadline": bool(durations)}))

            # ---- documents to deliver
            if re.search(r"\b(?:remettre|fournir|présenter|presenter|soumettre|produire|transmettre|déposer|"
                         r"remettra|fournira|présentera|soumettra|produira|transmettra)\b", low):
                docs = [k for k in DOC_KEYWORDS if k in low]
                if docs:
                    findings.append(_finding("document", art, sent, "À fournir : " + ", ".join(docs[:4]),
                                             category="Documents", value={"documents": docs,
                                                                          "has_deadline": bool(durations)}))
    for i, f in enumerate(findings):
        f["id"] = "R%d" % (i + 1)
    return {"findings": findings, "terms": terms}


def _fmt_num(v):
    if v is None:
        return "-"
    if float(v).is_integer():
        v = int(v)
        s = "{:,}".format(v).replace(",", " ")
        return s
    return ("%.2f" % v).rstrip("0").rstrip(".").replace(".", ",")


def _fmt_rate(rate):
    if rate is None:
        return "-"
    inv = 1.0 / rate if rate else 0
    if inv and abs(inv - round(inv)) < 1e-6:
        return "1/%d" % round(inv)
    return "%s %%" % _fmt_num(rate * 100)


fmt_rate = _fmt_rate
fmt_num = _fmt_num

# --------------------------------------------------------------------------
# Document-level checks
# --------------------------------------------------------------------------


def resolve_terms(terms):
    """Pick one value per term, remember its citation and detect conflicts.

    Returns (resolved, conflicts): resolved[key] = {value, source, citation}
    """
    resolved = {}
    conflicts = []
    for key, occ in terms.items():
        values = []
        for o in occ:
            if o["value"] not in values:
                values.append(o["value"])
        first = occ[0]
        resolved[key] = {"value": first["value"], "source": "CPS",
                         "article_key": first["article_key"], "article_label": first["article_label"],
                         "page": first["page"], "text": first["text"]}
        numeric = all(isinstance(v, (int, float)) for v in values)
        if len(values) > 1 and key not in ("contract_amount_ttc", "caution_provisoire_dh"):
            if numeric and max(values) - min(values) < 1e-9:
                continue
            conflicts.append({"key": key, "values": values, "occurrences": occ})
        if key == "contract_amount_ttc" and len(values) > 1:
            # the largest TTC amount is the contract total; others are often partial
            best = max(occ, key=lambda o: o["value"])
            resolved[key].update(value=best["value"], article_key=best["article_key"],
                                 article_label=best["article_label"], page=best["page"], text=best["text"])
    for key, default in reg.DEFAULTS.items():
        if key not in resolved:
            resolved[key] = {"value": default, "source": "défaut", "article_key": None,
                             "article_label": reg.DEFAULT_SOURCES.get(key, "Valeur usuelle"),
                             "page": None, "text": ""}
    if "execution_delay_days" not in terms:
        resolved.pop("execution_delay_days", None)
    return resolved, conflicts


TERM_LABELS = {
    "execution_delay_days": "Délai d'exécution (jours)",
    "execution_delay_months": "Délai d'exécution (mois)",
    "penalty_rate_per_day": "Pénalité de retard par jour",
    "penalty_cap_pct": "Plafond des pénalités (%)",
    "retenue_rate_pct": "Retenue de garantie (% par acompte)",
    "retenue_cap_pct": "Plafond retenue de garantie (%)",
    "caution_definitive_pct": "Cautionnement définitif (%)",
    "caution_definitive_delay_days": "Délai de constitution caution définitive (jours)",
    "caution_provisoire_dh": "Cautionnement provisoire (DH)",
    "warranty_months": "Délai de garantie (mois)",
    "payment_delay_days": "Délai de paiement (jours)",
    "advance_pct": "Avance (%)",
    "price_type": "Nature des prix",
    "contract_amount_ttc": "Montant du marché TTC (DH)",
    "tva_pct": "TVA (%)",
    "os_start_max_days": "Délai max. OS de commencement (jours)",
    "mass_increase_pct": "Seuil augmentation dans la masse (%)",
    "mass_decrease_pct": "Seuil diminution dans la masse (%)",
    "penalty_other_cap_pct": "Plafond autres pénalités (%)",
}


def format_term(key, value):
    if value is None:
        return "-"
    if key == "penalty_rate_per_day":
        return _fmt_rate(value) + " par jour"
    if key.endswith("_pct"):
        return _fmt_num(value) + " %"
    if key.endswith("_dh") or key == "contract_amount_ttc":
        return _fmt_num(value) + " DH"
    if isinstance(value, float):
        return _fmt_num(value)
    return str(value)


def document_issues(articles, findings, resolved, conflicts, doc_type="CPS"):
    """Inconsistencies and gaps at document level, each with a citation."""
    issues = []

    def add(severity, title, detail, cite=None, action=""):
        issues.append({"severity": severity, "title": title, "detail": detail,
                       "article_key": cite.get("article_key") if cite else None,
                       "article_label": cite.get("article_label") if cite else None,
                       "page": cite.get("page") if cite else None,
                       "text": cite.get("text") if cite else "", "action": action})

    for c in conflicts:
        label = TERM_LABELS.get(c["key"], c["key"])
        vals = " / ".join(format_term(c["key"], v) for v in c["values"])
        where = "; ".join("%s (p.%s)" % (o["article_label"], o["page"]) for o in c["occurrences"][:4])
        add("élevé", "Valeurs contradictoires : " + label,
            "Le document mentionne %s. Emplacements : %s." % (vals, where), c["occurrences"][0],
            "Demander une clarification écrite au maître d'ouvrage avant signature / démarrage.")

    cap = resolved.get("penalty_cap_pct", {})
    if cap.get("source") == "CPS" and cap["value"] > reg.DEFAULTS["penalty_cap_pct"] + 1e-9:
        add("élevé", "Plafond des pénalités supérieur à l'usage",
            "Plafond fixé à %s %% du montant (référence CCAG-T : %s %%)." % (
                _fmt_num(cap["value"]), _fmt_num(reg.DEFAULTS["penalty_cap_pct"])), cap,
            "Vérifier la conformité au CCAG-T et provisionner le risque.")
    has_penalty = any(f["kind"] == "penalty" and f["value"].get("type") == "retard" for f in findings)
    if doc_type in ("CPS", "MARCHE") and has_penalty and cap.get("source") != "CPS":
        add("moyen", "Plafond des pénalités non précisé",
            "Aucun plafond explicite n'a été trouvé ; le plafond du CCAG-T (%s %%) s'appliquerait." %
            _fmt_num(reg.DEFAULTS["penalty_cap_pct"]), None, "Confirmer le plafond applicable.")
    rate = resolved.get("penalty_rate_per_day", {})
    if rate.get("source") == "CPS" and rate["value"] > 0.002:
        add("élevé", "Taux de pénalité élevé",
            "Taux de %s par jour : le plafond peut être atteint en %d jours de retard." % (
                _fmt_rate(rate["value"]), int(cap.get("value", 8) / 100.0 / rate["value"])), rate,
            "Négocier ou sécuriser le planning (marge, ressources).")
    ret = resolved.get("retenue_cap_pct", {})
    if ret.get("source") == "CPS" and ret["value"] > reg.DEFAULTS["retenue_cap_pct"] + 1e-9:
        add("moyen", "Plafond de retenue de garantie supérieur à 7 %",
            "Plafond de %s %%." % _fmt_num(ret["value"]), ret, "Vérifier la base réglementaire.")
    cd = resolved.get("caution_definitive_pct", {})
    if cd.get("source") == "CPS" and abs(cd["value"] - reg.DEFAULTS["caution_definitive_pct"]) > 1e-9:
        add("info", "Cautionnement définitif différent de 3 %",
            "Taux fixé à %s %%." % _fmt_num(cd["value"]), cd, "Prévoir la ligne de caution bancaire correspondante.")

    if doc_type in ("CPS", "MARCHE"):
        full = strip_accents(" ".join((a.title or "") + " " + a.text for a in articles).lower())
        for code, label, keys in reg.EXPECTED_CLAUSES:
            if not any(strip_accents(k) in full for k in keys):
                add("moyen", "Clause absente : " + label,
                    "Aucune mention trouvée dans le document.", None,
                    "Vérifier si la clause figure dans une autre pièce du marché (CCAG-T, RC, avenant).")
        if "execution_delay_days" not in resolved:
            add("élevé", "Délai d'exécution introuvable",
                "Le délai d'exécution n'a pas pu être identifié automatiquement.", None,
                "Saisir le délai manuellement dans la fiche du marché.")

    for f in findings:
        if f["kind"] == "inconsistency":
            add(f.get("severity") or "élevé", f["summary"], "", f,
                "Faire corriger la pièce : en cas de discordance, l'acte d'engagement / les lettres prévalent généralement.")
    der = [f for f in findings if f["kind"] == "derogation"]
    for f in der[:15]:
        add("moyen", f["summary"], _short(f["text"], 220), f,
            "Analyser l'impact de la dérogation par rapport au régime du CCAG-T.")
    return issues
