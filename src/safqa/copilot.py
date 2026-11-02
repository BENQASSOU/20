"""Safqa IA - built-in copilot that works without any API key.

* ``answer``   : answers a question about a contract from its own clauses
                 (with [A12] citations), the tracking data and the
                 regulatory defaults.
* ``insights`` : proactive, prioritised recommendations across the portfolio,
                 each with concrete one-tap actions.
* ``letter``   : drafts the usual letters of a works contract (payment
                 reminder with late-payment interest, release of guarantee,
                 provisional acceptance, extension of time, reservations on a
                 work order, restart order).

When a Claude API key is configured the assistant uses Claude; this module
is the always-available fallback and the source of the proactive features.
"""

from datetime import date

from . import erp
from . import regulation as reg
from . import tracking as tr
from .analysis import articles_of
from .segment import normalize_for_match

# Indicative yearly rate for late-payment interest: Bank Al-Maghrib policy
# rate + margin set by the payment-delay decree.  Editable in Paramètres.
DEFAULT_INTEREST_RATE_PCT = 5.25

STOP = set("les des une pour que qui quoi est sont dans sur par avec mon mes notre nos votre vos leur ce cette ces "
           "dit dire aux du de la le un et ou en au il elle on je tu nous vous ils elles quel quelle quels quelles comment "
           "combien quand faut dois doit peux peut sont etre avoir fait faire marche".split())


def _norm(text):
    t = normalize_for_match(text or "")
    for ch in "'’`\"«»?!.,;:()[]/":
        t = t.replace(ch, " ")
    return t


def _stem(t):
    if len(t) > 4 and t[-1] in "sx":
        t = t[:-1]
    for suf in ("ement", "ements", "ation", "ations"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[:-len(suf)]
    return t


def _tokens(text):
    return [_stem(t) for t in _norm(text).split() if len(t) > 2 and t not in STOP]


def pct(v):
    return ("%.2f" % v).rstrip("0").rstrip(".").replace(".", ",") + " %"


def money(v, dec=2):
    s = "{:,.{d}f}".format(v or 0, d=dec).replace(",", " ").replace(".", ",")
    return s + " DH"


def fmt_date(d):
    return tr.fmt_date(d) if d else "-"


def interest_rate(company=None):
    try:
        return float((company or {}).get("interest_rate_pct") or DEFAULT_INTEREST_RATE_PCT)
    except (TypeError, ValueError):
        return DEFAULT_INTEREST_RATE_PCT


def late_interest(amount, late_days, rate_pct=DEFAULT_INTEREST_RATE_PCT):
    """Simple interest on the overdue amount, Exact/365."""
    return max(0.0, (amount or 0) * rate_pct / 100.0 * max(0, late_days or 0) / 365.0)


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------

def all_articles(s):
    out = []
    for d in s.get("documents", []):
        for a in articles_of(d):
            out.append((d, a))
    return out


def search_articles(s, query, limit=3, extra_terms=()):
    """Rank clauses: words of the question weigh twice the intent's vocabulary."""
    q = set(_tokens(query))
    ex = set(extra_terms) - q
    if not q and not ex:
        return []
    scored = []
    for d, a in all_articles(s):
        body = _tokens(a.text)
        title = set(_tokens(a.title or ""))
        if not body and not title:
            continue
        hit = 0.0
        for t in body:
            hit += 2 if t in q else (1 if t in ex else 0)
        for t in title:
            hit += 8 if t in q else (4 if t in ex else 0)
        if hit:
            scored.append((hit / (len(body) + 20) ** 0.5, a, d))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return []
    top = scored[0][0]
    return [(a, d) for sc, a, d in scored[:limit] if sc >= top * 0.45]


def excerpt(text, query_terms, size=320):
    norm = _norm(text)
    pos = -1
    for t in query_terms:
        pos = norm.find(t)
        if pos >= 0:
            break
    start = max(0, pos - 80) if pos >= 0 else 0
    chunk = text[start:start + size].strip().replace("\n", " ")
    return ("…" if start else "") + chunk + ("…" if start + size < len(text) else "")


def cite_term(s, key):
    t = (s.get("terms") or {}).get(key)
    if isinstance(t, dict) and t.get("article_key"):
        return " [%s]" % t["article_key"]
    return ""


def term_source(s, key):
    t = (s.get("terms") or {}).get(key)
    if isinstance(t, dict) and t.get("article_key"):
        return "selon le CPS%s" % cite_term(s, key)
    return "valeur réglementaire par défaut (%s)" % reg.DEFAULT_SOURCES.get(key, "réglementation")


# --------------------------------------------------------------------------
# Question answering
# --------------------------------------------------------------------------

INTENTS = [
    ("paiement", ("paie", "paye", "paiement", "retard de paiement", "interet", "moratoire", "encaiss", "impaye",
                  "creance", "relance", "decompte", "facture")),
    ("penalites", ("penalit", "amende", "retenue pour retard")),
    ("delai", ("delai", "date de fin", "fin des travaux", "planning", "retard", "prolongation", "arret", "reprise",
               "ordre de service", " os ")),
    ("cautions", ("caution", "garantie", "mainlevee", "retenue", "banque")),
    ("reception", ("reception", "reserve", "recolement", "pv ")),
    ("documents", ("document", "piece", "dossier", "manquant", "fournir", "attestation", "assurance")),
    ("finance", ("marge", "budget", "cout", "depense", "rentab", "benefice", "derap", "tresorerie")),
    ("demarrage", ("demarrage", "commencement", "avant le debut", "installation", "obligation")),
]


INTENT_TERMS = {
    "paiement": ("paiement", "decompte", "interet", "moratoire", "acompte"),
    "penalites": ("penalite", "retard", "plafond"),
    "delai": ("delai", "execution", "ordre", "service", "commencement"),
    "cautions": ("cautionnement", "caution", "retenue", "garantie", "mainlevee"),
    "reception": ("reception", "provisoire", "definitive", "reserve"),
    "documents": ("piece", "assurance", "attestation"),
    "finance": (),
    "demarrage": ("commencement", "cautionnement", "assurance", "programme"),
}


def detect_intents(question):
    q = " " + _norm(question) + " "
    found = [name for name, keys in INTENTS if any(k in q for k in keys)]
    # "payé en retard" is about payment, not about the works schedule.
    if "paiement" in found and "delai" in found and not any(
            k in q for k in ("delai", "fin des travaux", "prolong", "arret", "planning", "execution")):
        found.remove("delai")
    return found


def answer(s, question, company=None, today=None):
    """Markdown answer. s = erp.project_state(...)."""
    today = today or date.today()
    p = s["project_full"]
    intents = detect_intents(question)
    parts = []
    for name in intents[:3]:
        fn = HANDLERS.get(name)
        if fn:
            block = fn(s, company, today)
            if block:
                parts.append(block)
    qterms = _tokens(question)
    extra = [_stem(t) for i in intents[:2] for t in INTENT_TERMS.get(i, ())]
    hits = search_articles(s, question, limit=3, extra_terms=extra)
    if hits:
        lines = ["**Ce que dit votre marché**"]
        for a, d in hits:
            lines.append("- *%s* [%s] : « %s »" % (a.label(), a.key, excerpt(a.text, qterms)))
        parts.append("\n".join(lines))
    flags = [f for f in s.get("flags", []) if f["severity"] in ("critique", "élevé")
             and (not intents or any(_flag_matches(f, i) for i in intents))]
    if flags:
        lines = ["**Actions recommandées**" if intents or hits else "**Points d'attention sur ce marché**"]
        for f in flags[:4]:
            lines.append("- %s — %s" % (f["title"], f.get("action") or f.get("detail") or ""))
        parts.append("\n".join(lines))
    if not intents and not hits:
        parts.insert(0, "Je n'ai pas trouvé d'élément précis sur ce point dans les pièces du marché « %s ». "
                     "Reformulez avec un mot-clé (délai, pénalités, paiement, caution, réception, documents, marge) "
                     "ou chargez le CPS dans l'onglet Pièces." % (p.get("title") or ""))
    parts.append("_Safqa IA hors-ligne · %s_" % reg.DISCLAIMER)
    return "\n\n".join(parts)


def _flag_matches(f, intent):
    cat = f.get("category") or ""
    return {"paiement": cat == "Paiement", "penalites": cat in ("Pénalités", "Délais"),
            "delai": cat in ("Délais", "Pénalités"), "cautions": cat == "Garanties",
            "reception": cat == "Réception", "documents": cat in ("Documents", "Assurances") or cat.startswith("Contrat"),
            "finance": cat in ("Budget", "Rentabilité", "Fournisseurs"),
            "demarrage": cat in ("Documents", "Délais")}.get(intent, False)


def _h_paiement(s, company, today):
    limit = tr.term(s["terms"], "payment_delay_days") or 60
    rate = interest_rate(company)
    lines = ["**Paiements** — délai de paiement : **%s jours** (%s)." % (limit, term_source(s, "payment_delay_days"))]
    total_int = 0.0
    for d in sorted(s["decomptes"], key=lambda x: x.get("number") or 0):
        st = tr.payment_status(d, s["terms"], today)
        if st["paid"] and not st.get("late_days"):
            continue
        if st["days"] is None:
            lines.append("- Décompte n° %s : date de constatation à renseigner pour suivre le délai." % d.get("number"))
            continue
        it = late_interest(d.get("net_ttc"), st.get("late_days"), rate)
        total_int += it
        state = "payé" if st["paid"] else "non payé"
        lines.append("- Décompte n° %s (%s) : %s, %d jours écoulés%s." % (
            d.get("number"), money(d.get("net_ttc")), state, st["days"],
            (" — **%d jours de retard, intérêts moratoires ≈ %s**" % (st["late_days"], money(it))) if st["late"] else ""))
    if total_int:
        lines.append("Total des intérêts moratoires estimés : **%s** (taux indicatif %s l'an, %s). "
                     "Vous pouvez générer la lettre de réclamation depuis *Courriers*." % (
                         money(total_int), pct(rate), reg.TEXTS["DELAIS_PAIEMENT"]))
    if len(lines) == 1:
        lines.append("Aucun décompte en attente de paiement.")
    return "\n".join(lines)


def _h_penalites(s, company, today):
    pen = tr.penalty_estimate(s["project_full"], s["schedule"])
    rate = pen["rate"]
    lines = ["**Pénalités de retard** — taux : **%s du montant par jour** (%s), plafond : **%s** (%s)." % (
        ("1/%d" % round(1 / rate)) if rate else "non fixé", term_source(s, "penalty_rate_per_day"),
        pct(tr.term(s["terms"], "penalty_cap_pct") or 0), term_source(s, "penalty_cap_pct"))]
    if pen["late_days"]:
        lines.append("Retard actuel : **%d jours** → pénalités estimées **%s**%s." % (
            pen["late_days"], money(pen["amount"]), " (plafond atteint : risque de résiliation)" if pen["capped"] else ""))
    else:
        lines.append("Aucun retard constaté à ce jour.")
    if pen["days_to_cap"]:
        lines.append("Le plafond serait atteint après %d jours de retard." % pen["days_to_cap"])
    lines.append("Pour les neutraliser : faites constater par OS les arrêts imputables au maître d'ouvrage "
                 "et demandez une prolongation écrite avant l'échéance.")
    return "\n".join(lines)


def _h_delai(s, company, today):
    sc = s["schedule"]
    p = s["project_full"]
    if not sc.get("start"):
        return ("**Délais** — l'ordre de service de commencement n'est pas enregistré : le délai de %s jours "
                "ne court pas encore (%s)." % (p.get("delay_days") or "-", term_source(s, "execution_delay_days")))
    lines = ["**Délais** — délai contractuel : %s jours%s, démarrage le %s, fin contractuelle le **%s**." % (
        p.get("delay_days") or "-", cite_term(s, "execution_delay_days"), fmt_date(sc["start"]), fmt_date(sc["end"]))]
    if sc["suspended_days"]:
        lines.append("Arrêts de chantier (OS) : %d jours ajoutés au délai." % sc["suspended_days"])
    if sc["extension_days"]:
        lines.append("Prolongations : %d jours." % sc["extension_days"])
    if sc["stopped"]:
        lines.append("Le chantier est **à l'arrêt** : pensez à demander l'OS de reprise par écrit.")
    if sc["late_days"]:
        lines.append("⚠ Retard : **%d jours** au-delà de la fin contractuelle." % sc["late_days"])
    elif sc.get("remaining") is not None:
        lines.append("Il reste **%d jours** ; avancement financier %d %%." % (
            sc["remaining"], s["finance"]["progress"] * 100))
    return "\n".join(lines)


def _h_cautions(s, company, today):
    rate_def = tr.term(s["terms"], "caution_definitive_pct")
    lines = ["**Cautions et retenue** — cautionnement définitif : **%s** (%s) ; retenue de garantie : %s "
             "plafonnée à %s (%s)." % (pct(rate_def or 0), term_source(s, "caution_definitive_pct"),
                                      pct(tr.term(s["terms"], "retenue_rate_pct") or 0),
                                      pct(tr.term(s["terms"], "retenue_cap_pct") or 0),
                                         term_source(s, "retenue_rate_pct"))]
    for g in s["guarantees"]:
        gi = erp.guarantee_info(g, today)
        state = "libérée" if not gi["active"] else ("**expirée**" if gi["expired"] else (
            "expire dans %d j" % gi["days_to_expiry"] if gi["days_to_expiry"] is not None else "active"))
        lines.append("- %s %s : %s, %s." % (erp.label("guarantee_kind", g.get("kind")), g.get("ref") or "",
                                             money(g.get("amount"), 0), state))
    if s["finance"]["retenue"]:
        lines.append("Retenue de garantie cumulée : %s (restituée après réception définitive ou remplacée par "
                     "une caution)." % money(s["finance"]["retenue"]))
    return "\n".join(lines)


def _h_reception(s, company, today):
    rs = tr.reception_status(s["project_full"], s["receptions"], today)
    lines = ["**Réceptions** — délai de garantie : %s mois (%s)." % (rs["warranty_months"],
                                                                  term_source(s, "warranty_months"))]
    if rs["provisional"]:
        lines.append("Réception provisoire le %s%s ; réception définitive prévue le **%s**." % (
            fmt_date(rs["provisional"].get("date")), " avec réserves" if rs["reserves_open"] else "",
            fmt_date(rs["warranty_end"])))
    else:
        lines.append("Réception provisoire non prononcée : demandez-la par écrit dès l'achèvement (lettre dans *Courriers*).")
    missing = _missing_docs(s, "Réception")
    if missing:
        lines.append("Pièces à préparer : " + ", ".join(missing) + ".")
    return "\n".join(lines)


def _missing_docs(s, phase=None):
    present = {c["code"] for c in s.get("checklist", []) if c.get("present")}
    return [label for code, label, ph, mand in reg.DOCUMENT_CHECKLIST
            if mand and code not in present and (phase is None or ph == phase)]


def _h_documents(s, company, today):
    missing = _missing_docs(s)
    if not missing:
        return "**Documents** — toutes les pièces obligatoires sont cochées dans la liste de contrôle."
    return "**Documents obligatoires manquants (%d)** :\n%s" % (len(missing), "\n".join("- " + m for m in missing[:12]))


def _h_finance(s, company, today):
    f = s["finance"]
    lines = ["**Rentabilité** — facturé HT : %s, dépenses HT : %s, marge actuelle **%s** (%s) ; "
             "marge prévisionnelle à terminaison **%s** (%s)." % (
                 money(f["invoiced_ht"], 0), money(f["costs_ht"], 0), money(f["margin_ht"], 0), pct(f["margin_pct"]),
                 money(f["forecast_margin"], 0), pct(f["forecast_margin_pct"]))]
    over = [c for c in f["by_category"] if c["overrun"]]
    for c in over:
        lines.append("- ⚠ Poste **%s** en dépassement : %s réalisés pour %s budgétés (+%d %%)." % (
            c["label"], money(c["actual"], 0), money(c["budget"], 0), (c["ratio"] - 1) * 100))
    if f["costs_unpaid_ttc"]:
        lines.append("Dettes fournisseurs non réglées : %s TTC." % money(f["costs_unpaid_ttc"], 0))
    return "\n".join(lines)


def _h_demarrage(s, company, today):
    missing = _missing_docs(s, "Démarrage")
    lines = ["**Démarrage** — cautionnement définitif à constituer dans les %s jours (%s)." % (
        tr.term(s["terms"], "caution_definitive_delay_days"), term_source(s, "caution_definitive_delay_days"))]
    if missing:
        lines.append("À fournir : " + ", ".join(missing) + ".")
    return "\n".join(lines)


HANDLERS = {"paiement": _h_paiement, "penalites": _h_penalites, "delai": _h_delai, "cautions": _h_cautions,
            "reception": _h_reception, "documents": _h_documents, "finance": _h_finance, "demarrage": _h_demarrage}


SUGGESTIONS = [
    "Le maître d'ouvrage paie en retard : combien puis-je réclamer ?",
    "Comment sont calculées les pénalités de retard ?",
    "Quand se termine mon délai d'exécution ?",
    "Quels documents me manquent ?",
    "Quelle est ma marge prévisionnelle et quels postes dérapent ?",
    "Quand puis-je récupérer ma caution et la retenue de garantie ?",
]


# --------------------------------------------------------------------------
# Proactive recommendations
# --------------------------------------------------------------------------

def insights(store, company=None, today=None, limit=8, pid=None):
    """[{severity, title, detail, pid, actions:[(label, kind, arg)]}]
    kind: 'route' (arg = route), 'letter' (arg = letter kind)."""
    today = today or date.today()
    rate = interest_rate(company)
    out = []
    for p in store.projects():
        if pid is not None and p["id"] != pid:
            continue
        if (p.get("status") or "en_cours") not in ("en_cours", "suspendu", "receptionne"):
            continue
        s = erp.project_state(store, p["id"], today)
        if not s:
            continue
        ref = p.get("ref") or p.get("title") or ""
        pid_ = p["id"]
        # late payments
        for d in s["decomptes"]:
            st = tr.payment_status(d, s["terms"], today)
            if st["late"] and not st["paid"]:
                it = late_interest(d.get("net_ttc"), st["late_days"], rate)
                out.append({"severity": "critique" if st["late_days"] > 30 else "élevé", "pid": pid_,
                            "title": "Réclamer %s d'intérêts moratoires" % money(it, 0),
                            "detail": "%s · décompte n° %s impayé depuis %d jours (%s)." % (
                                ref, d.get("number"), st["days"], money(d.get("net_ttc"), 0)),
                            "score": 100 + st["late_days"],
                            "actions": [("Rédiger la relance", "letter", "relance_paiement"),
                                        ("Marquer encaissé", "paid", d["id"])]})
        sc = s["schedule"]
        pen = tr.penalty_estimate(s["project_full"], sc)
        if sc.get("late_days"):
            out.append({"severity": "critique", "pid": pid_, "score": 90 + sc["late_days"],
                        "title": "Retard de %d jours : %s de pénalités" % (sc["late_days"], money(pen["amount"], 0)),
                        "detail": "%s · fin contractuelle dépassée le %s." % (ref, fmt_date(sc["end"])),
                        "actions": [("Demander une prolongation", "letter", "prolongation"),
                                    ("Voir les OS", "route", "/marche/%s?tab=os" % pid_)]})
        elif sc.get("remaining") is not None and 0 <= sc["remaining"] <= 30 and s["finance"]["progress"] < 0.85:
            out.append({"severity": "élevé", "pid": pid_, "score": 80,
                        "title": "Fin du délai dans %d jours, avancement %d %%" % (
                            sc["remaining"], s["finance"]["progress"] * 100),
                        "detail": "%s · anticipez une demande de prolongation justifiée." % ref,
                        "actions": [("Demander une prolongation", "letter", "prolongation"),
                                    ("Planning", "route", "/marche/%s?tab=planning" % pid_)]})
        if sc.get("stopped"):
            out.append({"severity": "élevé", "pid": pid_, "score": 75,
                        "title": "Chantier à l'arrêt", "detail": "%s · le délai est suspendu ; demandez l'OS de reprise." % ref,
                        "actions": [("Demander l'OS de reprise", "letter", "reprise")]})
        rs = tr.reception_status(s["project_full"], s["receptions"], today)
        if rs["provisional"] and not rs["final"] and rs["days_to_final"] is not None and rs["days_to_final"] <= 30:
            out.append({"severity": "moyen", "pid": pid_, "score": 60,
                        "title": "Récupérer caution et retenue de garantie",
                        "detail": "%s · fin du délai de garantie le %s." % (ref, fmt_date(rs["warranty_end"])),
                        "actions": [("Demander la mainlevée", "letter", "mainlevee")]})
        if not rs["provisional"] and s["finance"]["progress"] >= 0.95:
            out.append({"severity": "moyen", "pid": pid_, "score": 55,
                        "title": "Travaux achevés : demandez la réception provisoire",
                        "detail": "%s · avancement %d %%." % (ref, s["finance"]["progress"] * 100),
                        "actions": [("Rédiger la demande", "letter", "reception")]})
        for g in s["guarantees"]:
            gi = erp.guarantee_info(g, today)
            if gi["expiring"] or gi["expired"]:
                out.append({"severity": "élevé" if gi["expired"] else "moyen", "pid": pid_, "score": 70,
                            "title": "%s %s" % (erp.label("guarantee_kind", g.get("kind")),
                                                        "expirée" if gi["expired"] else "expire dans %d j" % gi["days_to_expiry"]),
                            "detail": "%s · %s ; prolongez-la ou demandez sa mainlevée." % (ref, money(g.get("amount"), 0)),
                            "actions": [("Demander la mainlevée", "letter", "mainlevee"),
                                        ("Cautions", "route", "/marche/%s?tab=cautions" % pid_)]})
        if not s["documents"]:
            out.append({"severity": "info", "pid": pid_, "score": 40,
                        "title": "Chargez le CPS pour activer l'analyse",
                        "detail": "%s · Safqa IA extraira délais, pénalités, cautions et obligations avec les "
                                  "articles cités." % ref,
                        "actions": [("Charger une pièce", "route", "/marche/%s?tab=pieces" % pid_)]})
        if not sc.get("start") and (p.get("status") or "en_cours") == "en_cours":
            out.append({"severity": "info", "pid": pid_, "score": 35,
                        "title": "Enregistrez l'ordre de service de commencement",
                        "detail": "%s · le planning, les pénalités et l'échéancier en dépendent." % ref,
                        "actions": [("Ordres de service", "route", "/marche/%s?tab=os" % pid_)]})
        f = s["finance"]
        if f["contract_ht"] and f["forecast_margin_pct"] < 5:
            over = [c["label"] for c in f["by_category"] if c["overrun"]]
            out.append({"severity": "élevé" if f["forecast_margin"] < 0 else "moyen", "pid": pid_, "score": 65,
                        "title": "Marge prévisionnelle faible : %.1f %%" % f["forecast_margin_pct"],
                        "detail": "%s · %s" % (ref, ("postes en dépassement : " + ", ".join(over)) if over else
                                               "vérifiez le budget et les achats à venir."),
                        "actions": [("Analyser les coûts", "route", "/marche/%s?tab=couts" % pid_)]})
        if f["progress"] > 0.05 and f["invoiced_ratio"] + 0.15 < f["progress"]:
            out.append({"severity": "moyen", "pid": pid_, "score": 58,
                        "title": "Travaux exécutés non facturés",
                        "detail": "%s · avancement %d %% mais seulement %d %% facturé." % (
                            ref, f["progress"] * 100, f["invoiced_ratio"] * 100),
                        "actions": [("Préparer le décompte", "route", "/marche/%s?tab=decomptes&new=1" % pid_)]})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


# --------------------------------------------------------------------------
# Letters
# --------------------------------------------------------------------------

LETTERS = [
    ("relance_paiement", "Relance de paiement et intérêts moratoires"),
    ("prolongation", "Demande de prolongation du délai"),
    ("reception", "Demande de réception provisoire"),
    ("mainlevee", "Demande de mainlevée de caution et restitution de la retenue"),
    ("reserve_os", "Réserves sur un ordre de service"),
    ("reprise", "Demande d'ordre de service de reprise"),
]
LETTER_LABELS = dict(LETTERS)


def letter(kind, s, company=None, today=None, note=""):
    """Returns (subject, body) for a letter to the contracting authority."""
    today = today or date.today()
    company = company or {}
    p = s["project_full"]
    ref = "Marché n° %s — %s" % (p.get("ref") or "…", p.get("title") or "")
    sender = company.get("name") or "[Raison sociale]"
    head = [sender]
    for k in ("address", "city"):
        if company.get(k):
            head.append(company[k])
    if company.get("ice"):
        head.append("ICE : %s" % company["ice"])
    head += ["", "%s, le %s" % (company.get("city") or "", today.strftime("%d/%m/%Y")), "",
             "À Monsieur le Représentant du Maître d'Ouvrage", p.get("owner") or "[Maître d'ouvrage]", ""]
    body = []
    if kind == "relance_paiement":
        subject = "Réclamation de paiement et d'intérêts moratoires"
        rate = interest_rate(company)
        rows, total, total_int = [], 0.0, 0.0
        for d in sorted(s["decomptes"], key=lambda x: x.get("number") or 0):
            st = tr.payment_status(d, s["terms"], today)
            if st["paid"] or not st["late"]:
                continue
            it = late_interest(d.get("net_ttc"), st["late_days"], rate)
            total += d.get("net_ttc") or 0
            total_int += it
            rows.append("- Décompte n° %s du %s : %s TTC, constaté le %s, %d jours de retard, intérêts : %s" % (
                d.get("number"), fmt_date(d.get("date")), money(d.get("net_ttc")), fmt_date(d.get("submitted_date")),
                st["late_days"], money(it)))
        if not rows:
            rows = ["- Décompte n° … : … DH TTC, constaté le …"]
        body = ["Nous avons l'honneur de vous rappeler que les décomptes suivants, relatifs au marché cité en "
                "objet, demeurent impayés au-delà du délai réglementaire de %s jours :" % (
                    tr.term(s["terms"], "payment_delay_days") or 60), ""] + rows + [
            "",
            "Le montant principal restant dû s'élève à %s TTC. Conformément au %s, ce retard ouvre droit, de plein "
            "droit et sans formalité, au paiement d'intérêts moratoires, que nous évaluons à %s à la date de ce "
            "courrier (taux de %s l'an, à parfaire jusqu'au paiement effectif)." % (
                money(total), reg.TEXTS["DELAIS_PAIEMENT"], money(total_int), pct(rate)),
            "",
            "Nous vous prions de bien vouloir procéder au règlement des sommes dues dans les meilleurs délais et "
            "de liquider les intérêts moratoires correspondants."]
    elif kind == "prolongation":
        sc = s["schedule"]
        subject = "Demande de prolongation du délai d'exécution"
        body = ["Le délai d'exécution du marché cité en objet expire le %s." % fmt_date(sc.get("end")),
                "",
                "Nous avons l'honneur de solliciter une prolongation de ce délai de … jours, en raison des "
                "circonstances suivantes, qui ne nous sont pas imputables :",
                "- " + (note or "[décrire : intempéries, retard de remise du site, modification du projet, "
                                "attente de plans ou de décisions du maître d'ouvrage…]"),
                "",
                "Ces faits ont été consignés au journal de chantier. Nous vous prions de bien vouloir notifier "
                "l'ordre de service correspondant afin de préserver l'exécution du marché dans les meilleures "
                "conditions et d'écarter l'application de pénalités de retard."]
        if sc.get("suspended_days"):
            body.insert(1, "Nous rappelons que %d jours d'arrêt ont déjà été constatés par ordre de service." %
                        sc["suspended_days"])
    elif kind == "reception":
        subject = "Demande de réception provisoire des travaux"
        body = ["Nous avons l'honneur de vous informer de l'achèvement des travaux objet du marché cité en "
                "référence.",
                "",
                "Nous vous prions de bien vouloir fixer la date des opérations préalables à la réception "
                "provisoire, conformément aux stipulations du CPS et du CCAG-T. Le dossier de récolement et les "
                "résultats des essais sont tenus à votre disposition.",
                "",
                "Nous restons à votre disposition pour toute visite contradictoire."]
    elif kind == "mainlevee":
        rs = tr.reception_status(p, s["receptions"], today)
        subject = "Demande de mainlevée du cautionnement et de restitution de la retenue de garantie"
        gl = [g for g in s["guarantees"] if (g.get("status") or "active") != "liberee"]
        lst = ["- %s n° %s de %s" % (erp.label("guarantee_kind", g.get("kind")), g.get("ref") or "…",
                                     money(g.get("amount"))) for g in gl] or ["- Caution n° … de … DH"]
        body = ["La réception %s des travaux objet du marché cité en référence a été prononcée le %s." % (
            "définitive" if rs["final"] else "provisoire",
            fmt_date((rs["final"] or rs["provisional"] or {}).get("date"))),
            "",
            "Le délai de garantie ayant expiré%s, nous avons l'honneur de solliciter la mainlevée des "
            "cautions suivantes :" % ((" le %s" % fmt_date(rs["warranty_end"])) if rs["warranty_end"] else ""),
            ""] + lst + ([
                "",
                "ainsi que la restitution de la retenue de garantie d'un montant de %s." % money(s["finance"]["retenue"])]
                if s["finance"]["retenue"] else []) + [
            "", "Nous vous prions de bien vouloir nous délivrer les mainlevées correspondantes."]
    elif kind == "reserve_os":
        last = sorted(s["orders"], key=lambda o: o.get("date") or "")[-1:] or [{}]
        o = last[0]
        subject = "Réserves sur l'ordre de service n° %s" % (o.get("number") or "…")
        body = ["Nous accusons réception de l'ordre de service n° %s du %s." % (o.get("number") or "…",
                                                                               fmt_date(o.get("date"))),
                "",
                "Tout en nous y conformant, nous formulons expressément les réserves suivantes, dans le délai "
                "prévu par le CCAG-T :",
                "- " + (note or "[incidence sur les délais, sur les prix, travaux non prévus au bordereau…]"),
                "",
                "Ces réserves visent à préserver nos droits à indemnisation et à prolongation du délai. "
                "Un mémoire chiffré vous sera adressé."]
    elif kind == "reprise":
        subject = "Demande d'ordre de service de reprise des travaux"
        stops = s["schedule"].get("stops") or []
        since = stops[-1][0] if stops else None
        body = ["Les travaux objet du marché cité en référence sont arrêtés depuis le %s par ordre de service." %
                fmt_date(since),
                "",
                "Les causes de cet arrêt nous paraissant levées, nous avons l'honneur de vous demander de bien "
                "vouloir notifier l'ordre de service de reprise des travaux. Nous rappelons que la durée de "
                "l'arrêt prolonge d'autant le délai d'exécution et que nous réservons nos droits à "
                "indemnisation des frais d'immobilisation du chantier."]
    else:
        raise ValueError(kind)
    text = "\n".join(head + ["Objet : " + subject, "Référence : " + ref, "", "Monsieur,", ""] + body + [
        "", "Veuillez agréer, Monsieur, l'expression de nos salutations distinguées.", "",
        company.get("manager") or "Le Gérant", sender])
    return subject, text


def letter_pdf(subject, text, company=None):
    from .pdf import PDF
    company = company or {}
    pdf = PDF("Courrier", subject, company.get("name") or "")
    for para in text.split("\n"):
        if para.strip():
            pdf.para(para, 10, "B" if para.startswith("Objet") else "R")
        else:
            pdf.spacer(6)
    return pdf.output()
