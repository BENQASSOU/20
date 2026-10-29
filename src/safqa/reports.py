"""PDF and CSV reports built on pdf.PDF."""

import csv
import io
from datetime import date

from . import erp, regulation as reg, rules
from . import tracking as tr
from .analysis import KIND_LABELS, unified_findings
from .pdf import PDF
from .textnum import amount_in_words, fmt_dh

MIME_PDF = "application/pdf"
MIME_CSV = "text/csv"


def _n(v, dec=2):
    return fmt_dh(v, dec).replace(" DH", "") if v is not None else "-"


def _q(v):
    if v is None:
        return ""
    v = float(v)
    return str(int(v)) if v.is_integer() else ("%.3f" % v).rstrip("0").rstrip(".").replace(".", ",")


def _company_line(company):
    bits = [company.get("name") or "Mon entreprise"]
    for key, lbl in (("ice", "ICE"), ("rc", "RC"), ("if_number", "IF"), ("cnss", "CNSS")):
        if company.get(key):
            bits.append("%s %s" % (lbl, company[key]))
    return " - ".join(bits)


def safe_name(text):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (text or "doc"))[:40]


# --------------------------------------------------------------------------
# Contract report
# --------------------------------------------------------------------------

def contract_report(s, company, today=None):
    today = today or date.today()
    p, f, sched = s["project_full"], s["finance"], s["schedule"]
    pen = tr.penalty_estimate(p, sched)
    pdf = PDF("Rapport de marché", "Marché n° %s - %s" % (p.get("ref") or "-", p.get("owner") or ""),
              _company_line(company))
    pdf.para(p.get("title") or "", 12, "B")
    pdf.kpis([("Montant TTC", fmt_dh(f["contract_ttc"], 0), None),
              ("Facturé HT", "%s (%d %%)" % (fmt_dh(f["invoiced_ht"], 0), f["invoiced_ratio"] * 100), "#12B76A"),
              ("Encaissé TTC", fmt_dh(f["paid_ttc"], 0), "#2E90FA"),
              ("Marge prév.", "%.1f %%" % f["forecast_margin_pct"], "#E8A33D" if f["forecast_margin"] >= 0 else "#D92D20")])

    pdf.heading("Délais d'exécution")
    pdf.kv([("Début des travaux (OS de commencement)", tr.fmt_date(sched["start"])),
            ("Délai contractuel", "%s jours" % (p.get("delay_days") or "-")),
            ("Jours d'arrêt (OS)", "%d j" % sched["suspended_days"]),
            ("Fin contractuelle", tr.fmt_date(sched["end"])),
            ("Retard constaté", "%d jours" % sched["late_days"]),
            ("Pénalités de retard estimées", fmt_dh(pen["amount"]) + (" (plafond atteint)" if pen["capped"] else ""))])

    pdf.heading("Situation financière")
    pdf.kv([("Montant du marché TTC", fmt_dh(f["contract_ttc"])),
            ("Travaux facturés HT (cumul)", fmt_dh(f["invoiced_ht"])),
            ("Reste à réaliser HT", fmt_dh(f["backlog_ht"])),
            ("Encaissé TTC", fmt_dh(f["paid_ttc"])),
            ("Décomptes non payés TTC", fmt_dh(f["unpaid_ttc"])),
            ("Retenue de garantie", fmt_dh(f["retenue"])),
            ("Dépenses engagées HT", fmt_dh(f["costs_ht"])),
            ("Budget HT", fmt_dh(f["budget_ht"])),
            ("Marge brute à date HT", "%s (%.1f %%)" % (fmt_dh(f["margin_ht"]), f["margin_pct"])),
            ("Marge prévisionnelle à terminaison", "%s (%.1f %%)" % (fmt_dh(f["forecast_margin"]), f["forecast_margin_pct"]))])
    if f["by_category"]:
        pdf.table([("Poste", 3, "l"), ("Budget HT", 2, "r"), ("Réalisé HT", 2, "r"), ("Consommé", 1.2, "r")],
                  [[c["label"], _n(c["budget"]), _n(c["actual"]), "%d %%" % (c["ratio"] * 100)] for c in f["by_category"]])

    if s["flags"]:
        pdf.heading("Alertes et risques (%d)" % len(s["flags"]))
        pdf.table([("Niveau", 1.1, "l"), ("Alerte", 4, "l"), ("Action recommandée", 4, "l")],
                  [[fl["severity"].capitalize(), fl["title"] + (" - " + fl["detail"] if fl["detail"] else ""),
                    fl["action"] + (" [%s]" % fl["article_label"] if fl.get("article_label") else "")]
                   for fl in s["flags"][:40]])

    pdf.heading("Clauses clés du contrat")
    rows = []
    for key, lbl in rules.TERM_LABELS.items():
        t = s["terms"].get(key)
        if not t or key in ("execution_delay_months", "penalty_other_cap_pct"):
            continue
        src = t.get("article_label") or t.get("source") or ""
        if t.get("page"):
            src += " p.%s" % t["page"]
        rows.append([lbl, rules.format_term(key, t.get("value")), src])
    pdf.table([("Clause", 3, "l"), ("Valeur", 2, "r"), ("Source", 3.5, "l")], rows)

    if s["orders"]:
        pdf.heading("Ordres de service")
        pdf.table([("N°", 0.7, "l"), ("Type", 3, "l"), ("Date", 1.4, "l"), ("Observations", 4, "l")],
                  [[o.get("number") or "", tr.OS_LABELS.get(o.get("kind"), o.get("kind") or ""),
                    tr.fmt_date(o.get("date")), o.get("note") or ""] for o in s["orders"]])
    if s["decomptes"]:
        pdf.heading("Décomptes")
        pdf.table([("N°", 0.6, "l"), ("Date", 1.3, "l"), ("Cumul TTC", 2, "r"), ("Net à payer", 2, "r"),
                   ("Statut", 2, "l")],
                  [[str(d.get("number")), tr.fmt_date(d.get("date")), _n(d.get("total_ttc")), _n(d.get("net_ttc")),
                    ("Payé le " + tr.fmt_date(d.get("paid_date"))) if d.get("paid_date") else "En attente"]
                   for d in s["decomptes"]])
    if s["guarantees"]:
        pdf.heading("Cautions")
        pdf.table([("Type", 2.5, "l"), ("Référence", 2, "l"), ("Montant", 2, "r"), ("Échéance", 1.5, "l"), ("Statut", 1.5, "l")],
                  [[erp.label("guarantee_kind", g.get("kind")), g.get("ref") or "", _n(g.get("amount")),
                    tr.fmt_date(g.get("expiry_date")), erp.label("guarantee_status", g.get("status") or "active")]
                   for g in s["guarantees"]])
    pdf.spacer(6)
    pdf.para(reg.DISCLAIMER, 7.5, "I", "#667085")
    return pdf.output()


# --------------------------------------------------------------------------
# Payment statement
# --------------------------------------------------------------------------

def decompte_pdf(s, d, company):
    p = s["project_full"]
    kind = "définitif" if d.get("final") else "provisoire"
    pdf = PDF("Décompte %s n° %s" % (kind, d.get("number")),
              "Marché n° %s - %s" % (p.get("ref") or "-", p.get("owner") or ""), _company_line(company))
    pdf.kv([("Objet du marché", p.get("title") or ""),
            ("Maître d'ouvrage", p.get("owner") or ""),
            ("Titulaire", company.get("name") or ""),
            ("Date du décompte", tr.fmt_date(d.get("date"))),
            ("Montant du marché TTC", fmt_dh(p.get("amount_ttc")))], key_ratio=0.35)
    detail = d.get("detail") or []
    if detail:
        pdf.heading("Détail des travaux exécutés (quantités cumulées)")
        pdf.table([("N° prix", 0.9, "l"), ("Désignation", 4.2, "l"), ("U", 0.7, "c"), ("Qté cumulée", 1.4, "r"),
                   ("PU HT", 1.5, "r"), ("Montant HT", 1.8, "r")],
                  [[r.get("number") or "", r.get("designation") or "", r.get("unit") or "", _q(r.get("qty")),
                    _n(r.get("pu")), _n(r.get("amount"))] for r in detail],
                  totals=["", "Total des travaux HT", "", "", "", _n(d.get("works_ht"))])
    pdf.heading("Récapitulatif")
    rows = [("Montant des travaux HT", d.get("works_ht")), ("Révision des prix HT", d.get("revision_ht")),
            ("Total HT", d.get("total_ht")), ("TVA", d.get("tva")), ("Total TTC (cumul)", d.get("total_ttc")),
            ("À déduire : retenue de garantie", -(d.get("retenue") or 0)),
            ("À déduire : pénalités", -(d.get("penalties") or 0)),
            ("À déduire : remboursement de l'avance", -(d.get("advance_recovery") or 0)),
            ("Cumul net TTC", d.get("net_cumul_ttc")),
            ("À déduire : décomptes précédents", -(d.get("previous_ttc") or 0))]
    pdf.kv([(k, fmt_dh(v)) for k, v in rows if v or k.startswith(("Total", "Cumul", "Montant"))])
    pdf.ensure(70)
    pdf.rect(pdf.L, pdf.y, pdf.content_width, 30, "#E6F1F5")
    pdf.text(pdf.L + 10, pdf.y + 19, "NET À PAYER TTC", 11, "B", "#083B51")
    pdf.text_right(pdf.W - pdf.R - 10, pdf.y + 19, fmt_dh(d.get("net_ttc")), 13, "B", "#083B51")
    pdf.y += 40
    pdf.para("Arrêté le présent décompte à la somme de : %s." % amount_in_words(d.get("net_ttc") or 0).capitalize(),
             9.5, "I")
    pdf.spacer(26)
    y = pdf.y
    pdf.ensure(80)
    half = pdf.content_width / 2
    for i, who in enumerate(("Le titulaire", "Le maître d'ouvrage / maître d'œuvre")):
        pdf.text(pdf.L + i * half, y, who, 9.5, "B")
        pdf.text(pdf.L + i * half, y + 14, "Date, cachet et signature", 8, "R", "#667085")
        pdf.rect(pdf.L + i * half, y + 22, half - 16, 54, None, "#D0D5DD")
    pdf.y = y + 84
    return pdf.output()


def decompte_csv(project, decompte):
    out = io.StringIO()
    wr = csv.writer(out, delimiter=";")
    wr.writerow(["Marché", project.get("ref"), project.get("title")])
    wr.writerow(["Décompte n°", decompte.get("number"), "Date", tr.fmt_date(decompte.get("date"))])
    wr.writerow([])
    wr.writerow(["N° prix", "Désignation", "Unité", "Quantité cumulée", "PU HT", "Montant HT"])
    for r in decompte.get("detail") or []:
        wr.writerow([r["number"], r["designation"], r["unit"], _c(r["qty"]), _c(r["pu"]), _c(r["amount"])])
    wr.writerow([])
    for lbl, key in [("Travaux HT", "works_ht"), ("Révision HT", "revision_ht"), ("Total HT", "total_ht"),
                     ("TVA", "tva"), ("Total TTC", "total_ttc"), ("Retenue de garantie", "retenue"),
                     ("Pénalités", "penalties"), ("Remboursement avance", "advance_recovery"),
                     ("Cumul net TTC", "net_cumul_ttc"), ("Décomptes précédents", "previous_ttc"),
                     ("Net à payer TTC", "net_ttc")]:
        wr.writerow([lbl, "", "", "", "", _c(decompte.get(key))])
    return out.getvalue().encode("utf-8-sig")


def _c(v):
    return "" if v is None else ("%.2f" % float(v)).replace(".", ",")


# --------------------------------------------------------------------------
# Company-wide reports
# --------------------------------------------------------------------------

def portfolio_pdf(store, company, today=None):
    today = today or date.today()
    pf = erp.portfolio(store, today)
    t = pf["totals"]
    pdf = PDF("Tableau de bord du portefeuille", "Situation au %s" % today.strftime("%d/%m/%Y"),
              _company_line(company))
    pdf.kpis([("Carnet de commandes HT", fmt_dh(t["backlog_ht"], 0), None),
              ("Facturé %d HT" % today.year, fmt_dh(t["year_invoiced_ht"], 0), "#12B76A"),
              ("Créances TTC", fmt_dh(t["unpaid_ttc"], 0), "#F79009"),
              ("Cautions en cours", fmt_dh(t["guarantees"], 0), "#2E90FA")])
    pdf.heading("Activité des 12 derniers mois (HT)")
    pdf.bars([(lbl.split(" ")[0], inv, cost) for lbl, inv, cost, _col in pf["series"]],
             ["#0B4F6C", "#E8A33D"], ["Travaux facturés", "Dépenses"])
    pdf.heading("Marchés")
    rows = []
    for r in pf["rows"]:
        s = r["state"]
        f = s["finance"]
        rows.append([s["project"].get("ref") or "", s["project"].get("title") or "", _n(f["contract_ht"], 0),
                     "%d %%" % (f["invoiced_ratio"] * 100), _n(f["unpaid_ttc"], 0), "%.1f %%" % f["forecast_margin_pct"],
                     "%d / %d" % (r["critical"], r["high"])])
    pdf.table([("Réf.", 1, "l"), ("Objet", 3.6, "l"), ("Montant HT", 1.7, "r"), ("Facturé", 1, "r"),
               ("Créances", 1.6, "r"), ("Marge prév.", 1.2, "r"), ("Alertes C/É", 1, "c")], rows,
              totals=["", "Total", _n(t["contract_ht"], 0), "", _n(t["unpaid_ttc"], 0), "", ""])
    pdf.heading("Antériorité des créances (TTC)")
    pdf.kv([(k, fmt_dh(v)) for k, v in pf["aging"]])
    pl = pf["pipeline"]
    pdf.heading("Appels d'offres")
    pdf.table([("Statut", 3, "l"), ("Nombre", 1, "r"), ("Montant TTC", 2, "r")],
              [[v["label"], str(v["count"]), _n(v["amount"], 0)] for v in pl["by_status"].values()])
    if pl["win_rate"] is not None:
        pdf.para("Taux de réussite : %d %%." % (pl["win_rate"] * 100), 9.5, "B")
    return pdf.output()


def treasury_pdf(store, company, today=None):
    today = today or date.today()
    cf = erp.cashflow_forecast(store, today)
    rec = erp.receivables(store, today)
    pdf = PDF("Situation de trésorerie", "Prévisions sur 6 mois au %s" % today.strftime("%d/%m/%Y"),
              _company_line(company))
    pdf.table([("Mois", 1.5, "l"), ("Encaissements attendus", 2, "r"), ("Décaissements", 2, "r"),
               ("Solde du mois", 2, "r"), ("Cumul", 2, "r")],
              [[m["month"], _n(m["inflow"], 0), _n(m["outflow"], 0), _n(m["net"], 0), _n(m["cumulative"], 0)] for m in cf])
    pdf.bars([(m["month"].split(" ")[0], m["inflow"], m["outflow"]) for m in cf], ["#12B76A", "#D92D20"],
             ["Encaissements", "Décaissements"])
    pdf.heading("Créances clients (décomptes non payés)")
    pdf.table([("Marché", 3, "l"), ("Décompte", 1, "c"), ("Montant TTC", 2, "r"), ("Jours", 1, "r"), ("Statut", 2, "l")],
              [[r["project"].get("ref") or r["project"].get("title") or "", str(r["decompte"].get("number")),
                _n(r["decompte"].get("net_ttc")), str(r["status"]["days"] if r["status"]["days"] is not None else "-"),
                "En retard (intérêts moratoires)" if r["status"]["late"] else "Dans les délais"] for r in rec])
    pay = store.q("SELECT * FROM expenses WHERE status IS NULL OR status != 'paye' ORDER BY due_date")
    if pay:
        pdf.heading("Dettes fournisseurs")
        pdf.table([("Fournisseur", 2.5, "l"), ("Objet", 3, "l"), ("Montant TTC", 2, "r"), ("Échéance", 1.5, "l")],
                  [[store.tier_name(e.get("supplier_id")), e.get("label") or "", _n(erp.expense_ttc(e)),
                    tr.fmt_date(e.get("due_date"))] for e in pay])
    return pdf.output()


def guarantees_pdf(store, company, today=None):
    today = today or date.today()
    rows = store.q("SELECT * FROM guarantees ORDER BY status, expiry_date")
    summary = erp.guarantees_summary(store, today)
    pdf = PDF("État des cautions bancaires", "Au %s" % today.strftime("%d/%m/%Y"), _company_line(company))
    pdf.kpis([("Encours total", fmt_dh(summary["total"], 0), None),
              ("Cautions", str(summary["count"]), "#2E90FA"),
              ("À traiter (< 30 j / échues)", str(summary["alerts"]), "#D92D20")])
    if summary["by_bank"]:
        pdf.heading("Encours par banque")
        pdf.kv([(b, fmt_dh(v)) for b, v in summary["by_bank"]])
    pdf.heading("Détail")
    out = []
    for g in rows:
        info = erp.guarantee_info(g, today)
        target = ""
        if g.get("project_id"):
            pr = store.project(g["project_id"])
            target = "Marché %s" % ((pr or {}).get("ref") or "")
        elif g.get("tender_id"):
            t = store.get_row("tenders", g["tender_id"])
            target = "AO %s" % ((t or {}).get("ref") or "")
        out.append([erp.label("guarantee_kind", g.get("kind")), target, store.tier_name(g.get("bank_id")),
                    _n(g.get("amount"), 0), tr.fmt_date(g.get("expiry_date")),
                    erp.label("guarantee_status", g.get("status") or "active") + (" - ÉCHUE" if info["expired"] else "")])
    pdf.table([("Type", 2.2, "l"), ("Objet", 1.8, "l"), ("Banque", 1.8, "l"), ("Montant", 1.5, "r"),
               ("Échéance", 1.2, "l"), ("Statut", 1.8, "l")], out)
    return pdf.output()


def analysis_pdf(s, company):
    p = s["project_full"]
    pdf = PDF("Analyse contractuelle", "Marché n° %s - %s" % (p.get("ref") or "-", p.get("owner") or ""),
              _company_line(company))
    for d in s["documents"]:
        items = [f for f in unified_findings(d) if f["kind"] in
                 ("obligation", "prohibition", "deadline", "penalty", "document", "financial")]
        pdf.heading("%s - %s" % (d.get("doc_type"), d.get("filename")))
        if not items:
            pdf.para("Aucun élément extrait.", 9, "I")
            continue
        pdf.table([("Type", 1.3, "l"), ("Partie", 1.3, "l"), ("Élément", 4.5, "l"), ("Source", 1.8, "l")],
                  [[KIND_LABELS.get(f["kind"], f["kind"]), f.get("party") or "", f.get("summary") or "",
                    "%s%s%s" % (f.get("article_label") or "", (" p.%s" % f["page"]) if f.get("page") else "",
                                "" if f.get("verified", True) else " (à vérifier)")] for f in items[:200]], size=7.8)
        issues = (d.get("analysis") or {}).get("issues", []) + (d.get("analysis") or {}).get("ai_risks", [])
        if issues:
            pdf.para("Points d'attention", 10.5, "B", "#B42318")
            pdf.table([("Niveau", 1, "l"), ("Point", 4, "l"), ("Action", 4, "l")],
                      [[str(i.get("severity") or "").capitalize(), i.get("title") or "", i.get("action") or ""]
                       for i in issues], size=7.8)
    pdf.para(reg.DISCLAIMER, 7.5, "I", "#667085")
    return pdf.output()


def expenses_csv(store, project_id=None):
    out = io.StringIO()
    wr = csv.writer(out, delimiter=";")
    wr.writerow(["Date", "Marché", "Catégorie", "Libellé", "Fournisseur", "Référence", "Montant HT", "TVA %",
                 "Montant TTC", "Statut", "Échéance", "Payé le"])
    sql = "SELECT * FROM expenses" + (" WHERE project_id=?" if project_id else "") + " ORDER BY date"
    for e in store.q(sql, (project_id,) if project_id else ()):
        pr = store.project(e.get("project_id")) or {}
        wr.writerow([tr.fmt_date(e.get("date")), pr.get("ref") or "", erp.label("expense_category", e.get("category")),
                     e.get("label") or "", store.tier_name(e.get("supplier_id")), e.get("ref") or "",
                     _c(e.get("amount_ht")), _c(e.get("tva_pct")), _c(erp.expense_ttc(e)),
                     erp.label("expense_status", e.get("status")), tr.fmt_date(e.get("due_date")),
                     tr.fmt_date(e.get("paid_date"))])
    return out.getvalue().encode("utf-8-sig")
