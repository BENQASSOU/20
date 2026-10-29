"""Risk engine: turns contract analysis + execution data into flags.

Each flag: severity (critique / élevé / moyen / info), category, title,
detail, action, and an optional citation to the contract article.
"""

from datetime import date

from . import regulation as reg
from . import tracking as tr
from .textnum import fmt_dh

SEVERITY_ORDER = {"critique": 0, "élevé": 1, "moyen": 2, "info": 3}


def _flag(severity, category, title, detail="", action="", cite=None, amount=None):
    return {"severity": severity, "category": category, "title": title, "detail": detail,
            "action": action, "amount": amount,
            "article_key": (cite or {}).get("article_key"),
            "article_label": (cite or {}).get("article_label"),
            "page": (cite or {}).get("page"),
            "text": (cite or {}).get("text", "")}


def _cite(terms, key):
    t = (terms or {}).get(key)
    return t if isinstance(t, dict) and t.get("article_key") else None


def evaluate(project, documents, checklist, orders, items, decomptes, receptions, today=None,
             expenses=(), budget=(), guarantees=(), finance=None):
    today = today or date.today()
    terms = project.get("terms") or {}
    flags = []

    # ---- contract analysis issues (inconsistencies, missing clauses, derogations)
    for doc in documents:
        for issue in (doc.get("analysis") or {}).get("issues", []):
            flags.append(_flag(issue["severity"], "Contrat (%s)" % doc.get("doc_type", "doc"),
                               issue["title"], issue.get("detail", ""), issue.get("action", ""), issue))
        for risk in (doc.get("analysis") or {}).get("ai_risks", []):
            flags.append(_flag(risk.get("severity", "moyen"), "Analyse IA", risk.get("title", ""),
                               risk.get("detail", ""), risk.get("action", ""), risk))

    if not documents:
        flags.append(_flag("moyen", "Documents", "Aucun document contractuel chargé",
                           "Chargez le CPS et le BPDE pour extraire obligations, délais et pénalités.",
                           "Ajouter le CPS dans l'onglet Documents."))

    # ---- schedule and delay penalties
    sched = tr.schedule(project, orders, receptions, today)
    present = {c["code"]: c for c in checklist if c.get("present")}
    notif = tr.parse_date(project.get("approval_notif_date"))

    if notif and not sched["start"]:
        max_days = int(tr.term(terms, "os_start_max_days") or 60)
        waited = (today - notif).days
        if waited > max_days:
            flags.append(_flag("élevé", "Délais", "Ordre de service de commencement tardif",
                               "%d jours depuis la notification de l'approbation sans OS de commencement "
                               "(référence : %d jours)." % (waited, max_days),
                               "Vérifier vos droits (indemnisation ou résiliation) selon le CCAG-T et "
                               "adresser une demande écrite au maître d'ouvrage.",
                               _cite(terms, "os_start_max_days")))

    if notif and "CAUTION_DEF" not in present:
        limit = int(tr.term(terms, "caution_definitive_delay_days") or 30)
        days = (today - notif).days
        if days > limit:
            flags.append(_flag("critique", "Garanties", "Cautionnement définitif non constitué",
                               "%d jours depuis la notification (délai : %d jours)." % (days, limit),
                               "Déposer la caution définitive immédiatement : risque de confiscation du "
                               "cautionnement provisoire / résiliation.",
                               _cite(terms, "caution_definitive_delay_days")))
        elif days > limit - 10:
            flags.append(_flag("élevé", "Garanties", "Échéance du cautionnement définitif proche",
                               "Il reste %d jours pour le constituer." % (limit - days),
                               "Contacter la banque pour émettre la caution.",
                               _cite(terms, "caution_definitive_delay_days")))

    if sched["start"] and "ASSURANCES" not in present:
        flags.append(_flag("élevé", "Assurances", "Attestations d'assurance non enregistrées",
                           "Les travaux ont commencé le %s." % tr.fmt_date(sched["start"]),
                           "Transmettre les attestations (AT, RC, tous risques chantier) au maître d'ouvrage."))

    if sched["start"] and sched["end"]:
        pen = tr.penalty_estimate(project, sched)
        if sched["late_days"] > 0:
            sev = "critique" if pen["ratio_of_cap"] >= 0.8 else "élevé"
            flags.append(_flag(sev, "Pénalités", "Retard d'exécution : %d jours" % sched["late_days"],
                               "Pénalités estimées : %s (plafond %s)." % (fmt_dh(pen["amount"]), fmt_dh(pen["cap"])),
                               "Justifier le retard (OS d'arrêt, intempéries, retard de paiement, sujétions) "
                               "et demander une prolongation par écrit.",
                               _cite(terms, "penalty_rate_per_day"), amount=pen["amount"]))
            if pen["capped"] or pen["ratio_of_cap"] >= 0.8:
                flags.append(_flag("critique", "Résiliation",
                                   "Plafond des pénalités atteint ou proche (%d %%)" % round(pen["ratio_of_cap"] * 100),
                                   "Au-delà du plafond, le maître d'ouvrage peut résilier le marché.",
                                   "Plan de rattrapage immédiat et négociation écrite.",
                                   _cite(terms, "penalty_cap_pct")))
        elif sched["remaining"] is not None and not sched.get("finished"):
            total = max(1, (sched["end"] - sched["start"]).days)
            if 0 <= sched["remaining"] <= max(15, total * 0.1):
                flags.append(_flag("moyen", "Délais", "Fin du délai contractuel dans %d jours" % sched["remaining"],
                                   "Fin prévue le %s." % tr.fmt_date(sched["end"]),
                                   "Vérifier l'avancement et préparer la réception provisoire."))
        q = tr.quantities_summary(items, terms)
        if q["initial_ht"] and sched["progress"] > 0.2 and q["progress"] + 0.25 < sched["progress"]:
            flags.append(_flag("élevé", "Délais", "Avancement physique en retard sur le planning",
                               "Délai consommé : %d %%, travaux réalisés : %d %%." % (
                                   sched["progress"] * 100, q["progress"] * 100),
                               "Renforcer les moyens ou documenter les causes de retard."))
    if sched["stopped"]:
        stop = sched["stops"][-1]
        days = stop[2]
        flags.append(_flag("moyen" if days < 90 else "élevé", "Délais",
                           "Travaux arrêtés depuis %d jours" % days,
                           "OS d'arrêt du %s sans OS de reprise." % tr.fmt_date(stop[0]),
                           "Au-delà d'une longue période d'ajournement, le titulaire peut demander une "
                           "indemnisation ou la résiliation : formaliser une demande écrite."))

    # ---- quantities
    q = tr.quantities_summary(items, terms)
    over = [r for r in q["rows"] if r["overrun"]]
    for r in over[:10]:
        i = r["item"]
        flags.append(_flag("moyen" if r["variance_pct"] < 30 else "élevé", "Quantités",
                           "Dépassement prix n° %s : +%d %%" % (i.get("number"), r["variance_pct"]),
                           "%s : %s %s exécutés pour %s prévus." % (
                               i.get("designation", ""), _n(i.get("qty_executed")), i.get("unit", ""),
                               _n(i.get("qty_contract"))),
                           "Obtenir un ordre de service écrit avant d'exécuter au-delà des quantités du BPDE."))
    if q["initial_ht"]:
        limit = q["mass_increase_limit_pct"] or 10
        if q["mass_variation_pct"] > limit:
            flags.append(_flag("critique", "Quantités", "Augmentation dans la masse > %s %%" % _n(limit),
                               "Montant exécuté : %s HT pour %s HT initial (+%.1f %%)." % (
                                   fmt_dh(q["executed_ht"]), fmt_dh(q["initial_ht"]), q["mass_variation_pct"]),
                               "Un avenant est nécessaire : sans avenant, le surplus risque de ne pas être payé.",
                               _cite(terms, "mass_increase_pct")))
        elif q["mass_variation_pct"] > limit * 0.7:
            flags.append(_flag("moyen", "Quantités", "Masse des travaux proche du seuil de %s %%" % _n(limit),
                               "Variation actuelle : +%.1f %%." % q["mass_variation_pct"],
                               "Anticiper un avenant ou un OS de travaux supplémentaires."))

    # ---- payments
    for d in decomptes:
        st = tr.payment_status(d, terms, today)
        if st["late"] and not st["paid"]:
            flags.append(_flag("élevé", "Paiement",
                               "Décompte n° %s impayé depuis %d jours" % (d.get("number"), st["days"]),
                               "Délai réglementaire : %d jours. Montant : %s." % (st["limit"], fmt_dh(d.get("net_ttc"))),
                               "Les intérêts moratoires sont dus de plein droit : adresser une réclamation "
                               "écrite (référence : " + reg.TEXTS["DELAIS_PAIEMENT"] + ").",
                               _cite(terms, "payment_delay_days"), amount=d.get("net_ttc")))
        elif st["late"] and st["paid"]:
            flags.append(_flag("info", "Paiement",
                               "Décompte n° %s payé avec %d jours de retard" % (d.get("number"), st["late_days"]),
                               "Des intérêts moratoires peuvent être réclamés.",
                               "Vérifier qu'ils ont été liquidés avec le paiement."))
        if not d.get("submitted_date") and d.get("status") != "brouillon":
            flags.append(_flag("info", "Paiement", "Décompte n° %s : date de constatation manquante" % d.get("number"),
                               "Sans cette date, le délai de paiement ne peut pas être suivi.",
                               "Renseigner la date de constatation du service fait."))

    # ---- receptions
    rs = tr.reception_status(project, receptions, today)
    if rs["reserves_open"]:
        flags.append(_flag("élevé", "Réception", "Réserves non levées",
                           "Réception provisoire prononcée avec réserves.",
                           "Lever les réserves et faire constater la levée par PV."))
    if rs["final_due"]:
        flags.append(_flag("élevé", "Réception", "Réception définitive à demander",
                           "Le délai de garantie a expiré le %s." % tr.fmt_date(rs["warranty_end"]),
                           "Demander par écrit la réception définitive, la restitution de la retenue de "
                           "garantie et la mainlevée du cautionnement définitif.",
                           _cite(terms, "warranty_months")))
    if rs["final"] and "MAINLEVEE" not in present:
        flags.append(_flag("moyen", "Garanties", "Mainlevée des garanties à obtenir",
                           "Réception définitive prononcée.",
                           "Demander la mainlevée de la caution et la restitution de la retenue de garantie."))
    if rs["provisional"] and "RECOLEMENT" not in present:
        flags.append(_flag("moyen", "Documents", "Dossier de récolement non remis",
                           "Souvent exigé avant ou lors de la réception provisoire.",
                           "Préparer les plans de récolement."))

    # ---- missing documents for the current phase
    phase = current_phase(project, sched, rs)
    upto = reg.PHASES.index(phase)
    missing = [c for c in reg.DOCUMENT_CHECKLIST
               if c[3] and reg.PHASES.index(c[2]) < upto and c[0] not in present]
    if missing:
        flags.append(_flag("moyen" if len(missing) < 4 else "élevé", "Documents",
                           "%d document(s) obligatoire(s) non pointé(s)" % len(missing),
                           ", ".join(m[1] for m in missing[:8]) + ("…" if len(missing) > 8 else ""),
                           "Compléter la checklist de l'onglet Documents."))

    flags.extend(erp_flags(expenses, guarantees, finance, today))
    flags.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    return flags


def erp_flags(expenses, guarantees, finance, today):
    """Cost, margin, supplier and guarantee alerts (ERP modules)."""
    flags = []
    if finance:
        for c in finance.get("by_category", []):
            if c["overrun"]:
                flags.append(_flag("élevé" if c["ratio"] > 1.15 else "moyen", "Budget",
                                   "Dépassement budget : %s (+%d %%)" % (c["label"], (c["ratio"] - 1) * 100),
                                   "Réalisé %s pour un budget de %s." % (fmt_dh(c["actual"]), fmt_dh(c["budget"])),
                                   "Analyser les écarts et réviser le budget à terminaison.",
                                   amount=c["actual"] - c["budget"]))
        if finance.get("contract_ht") and finance.get("budget_ht") and finance["forecast_margin"] < 0:
            flags.append(_flag("critique", "Rentabilité", "Marge prévisionnelle négative",
                               "Coût à terminaison %s pour un marché de %s HT." % (
                                   fmt_dh(finance["cost_at_completion"]), fmt_dh(finance["contract_ht"])),
                               "Revoir les achats, les rendements et les réclamations (travaux "
                               "supplémentaires, révision des prix).", amount=-finance["forecast_margin"]))
    for e in expenses or ():
        if e.get("status") == "facture":
            due = tr.parse_date(e.get("due_date"))
            if due and due < today:
                flags.append(_flag("moyen", "Fournisseurs",
                                   "Facture fournisseur échue : %s" % (e.get("ref") or e.get("label") or ""),
                                   "Échéance dépassée de %d jours." % (today - due).days,
                                   "Planifier le règlement pour préserver la relation fournisseur."))
    for g in guarantees or ():
        if (g.get("status") or "active") == "liberee":
            continue
        exp = tr.parse_date(g.get("expiry_date"))
        if not exp:
            continue
        days = (exp - today).days
        name = (g.get("kind") or "caution").replace("_", " ")
        if days < 0:
            flags.append(_flag("élevé", "Garanties", "Caution %s expirée (%s)" % (name, g.get("ref") or ""),
                               "Expirée depuis %d jours." % -days,
                               "Demander la prorogation à la banque ou la mainlevée au maître d'ouvrage."))
        elif days <= 30:
            flags.append(_flag("moyen", "Garanties", "Caution %s expire dans %d jours" % (name, days),
                               "Référence %s - %s." % (g.get("ref") or "-", fmt_dh(g.get("amount"))),
                               "Anticiper la prorogation ou la mainlevée."))
    return flags


def current_phase(project, sched, rs):
    if rs.get("provisional"):
        return "Réception"
    if sched.get("start"):
        return "Exécution"
    if project.get("approval_notif_date"):
        return "Démarrage"
    return "Soumission"


def exposure(flags):
    """Quantified amounts behind the alerts: penalties the contractor risks
    paying, and receivables the owner is paying late."""
    pen = sum(f.get("amount") or 0 for f in flags if f["category"] == "Pénalités")
    late = sum(f.get("amount") or 0 for f in flags if f["category"] == "Paiement")
    return {"penalties": pen, "late_receivables": late}


def _n(v):
    if v is None:
        return "-"
    v = float(v)
    return str(int(v)) if v.is_integer() else ("%.2f" % v).replace(".", ",")
