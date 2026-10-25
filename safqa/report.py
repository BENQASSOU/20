"""HTML report and CSV exports."""

import csv
import html
import io
from datetime import date

from . import regulation as reg
from . import rules
from . import tracking as tr
from .analysis import KIND_LABELS, unified_findings
from .textnum import fmt_dh

SEV_COLORS = {"critique": "#b42318", "élevé": "#c4320a", "moyen": "#b54708", "info": "#175cd3"}


def _e(v):
    return html.escape("" if v is None else str(v))


def _cite(f):
    if not f.get("article_label"):
        return ""
    page = (" · p.%s" % f["page"]) if f.get("page") else ""
    return '<span class="cite">%s%s</span>' % (_e(f["article_label"]), page)


def project_report(bundle, terms, flags, today=None):
    today = today or date.today()
    p = bundle["project"]
    sched = tr.schedule(dict(p, terms=terms), bundle["orders"], bundle["receptions"], today)
    fin = tr.financial_summary(dict(p, terms=terms), bundle["items"], bundle["decomptes"], sched)
    out = io.StringIO()
    w = out.write
    w("<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
      "<meta name='viewport' content='width=device-width,initial-scale=1'>"
      "<title>Rapport %s</title><style>"
      "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#101828;margin:24px;line-height:1.45}"
      "h1{color:#0b4f6c;margin-bottom:0}h2{color:#0b4f6c;border-bottom:2px solid #e4e7ec;padding-bottom:4px;margin-top:28px}"
      "table{border-collapse:collapse;width:100%%;font-size:14px}td,th{border:1px solid #e4e7ec;padding:6px 8px;text-align:left;vertical-align:top}"
      "th{background:#f2f4f7}.sev{color:#fff;border-radius:10px;padding:1px 8px;font-size:12px;white-space:nowrap}"
      ".cite{background:#e0f2fe;color:#075985;border-radius:6px;padding:1px 6px;font-size:12px;white-space:nowrap}"
      ".muted{color:#667085;font-size:13px}.q{color:#475467;font-style:italic;font-size:13px}"
      "</style></head><body>" % _e(p.get("ref") or p.get("title")))
    w("<h1>%s</h1><div class='muted'>Marché n° %s · %s · rapport du %s</div>" % (
        _e(p.get("title")), _e(p.get("ref")), _e(p.get("owner")), today.strftime("%d/%m/%Y")))

    w("<h2>Synthèse</h2><table>")
    rows = [
        ("Montant TTC", fmt_dh(p.get("amount_ttc"))),
        ("Début des travaux", tr.fmt_date(sched["start"])),
        ("Fin contractuelle", tr.fmt_date(sched["end"])),
        ("Jours d'arrêt", sched["suspended_days"]),
        ("Retard", "%d jours" % sched["late_days"]),
        ("Pénalités estimées", fmt_dh(fin["penalties_est"])),
        ("Travaux exécutés HT", "%s (%d %%)" % (fmt_dh(fin["executed_ht"]), fin["progress"] * 100)),
        ("Payé TTC", fmt_dh(fin["paid_ttc"])),
        ("Reste à encaisser (décomptes émis)", fmt_dh(fin["unpaid_ttc"])),
    ]
    for k, v in rows:
        w("<tr><th>%s</th><td>%s</td></tr>" % (_e(k), _e(v)))
    w("</table>")

    w("<h2>Alertes (%d)</h2><table><tr><th>Niveau</th><th>Alerte</th><th>Action</th><th>Source</th></tr>" % len(flags))
    for f in flags:
        w("<tr><td><span class='sev' style='background:%s'>%s</span></td><td><b>%s</b><br>%s</td><td>%s</td><td>%s</td></tr>" % (
            SEV_COLORS.get(f["severity"], "#667085"), _e(f["severity"]), _e(f["title"]), _e(f["detail"]),
            _e(f["action"]), _cite(f)))
    w("</table>")

    w("<h2>Clauses clés</h2><table><tr><th>Clause</th><th>Valeur</th><th>Source</th></tr>")
    for key, label in rules.TERM_LABELS.items():
        t = terms.get(key)
        if not t:
            continue
        src = _cite(t) if t.get("article_key") else "<span class='muted'>%s</span>" % _e(t.get("article_label") or t.get("source"))
        w("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (_e(label), _e(rules.format_term(key, t.get("value"))), src))
    w("</table>")

    for d in bundle["documents"]:
        items = [f for f in unified_findings(d) if f["kind"] in
                 ("obligation", "deadline", "penalty", "document", "financial")]
        if not items:
            continue
        w("<h2>%s - %s</h2><table><tr><th>Type</th><th>Partie</th><th>Élément</th><th>Citation</th></tr>" % (
            _e(d.get("doc_type")), _e(d.get("filename"))))
        for f in items:
            ver = "" if f.get("verified") else " <span class='muted'>(citation non vérifiée)</span>"
            w("<tr><td>%s<br><span class='muted'>%s</span></td><td>%s</td><td>%s<div class='q'>« %s »</div></td><td>%s%s</td></tr>" % (
                _e(KIND_LABELS.get(f["kind"], f["kind"])), _e(f.get("source")), _e(f.get("party")),
                _e(f.get("summary")), _e((f.get("text") or "")[:400]), _cite(f), ver))
        w("</table>")

    if bundle["orders"]:
        w("<h2>Ordres de service</h2><table><tr><th>N°</th><th>Type</th><th>Date</th><th>Note</th></tr>")
        for o in bundle["orders"]:
            w("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                _e(o.get("number")), _e(tr.OS_LABELS.get(o.get("kind"), o.get("kind"))),
                _e(tr.fmt_date(o.get("date"))), _e(o.get("note"))))
        w("</table>")
    if bundle["decomptes"]:
        w("<h2>Décomptes</h2><table><tr><th>N°</th><th>Date</th><th>Total TTC cumulé</th><th>Retenue</th><th>Net à payer</th><th>Payé le</th></tr>")
        for d in bundle["decomptes"]:
            w("<tr><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                _e(d.get("number")), " (définitif)" if d.get("final") else "", _e(tr.fmt_date(d.get("date"))),
                fmt_dh(d.get("total_ttc")), fmt_dh(d.get("retenue")), fmt_dh(d.get("net_ttc")),
                _e(tr.fmt_date(d.get("paid_date")))))
        w("</table>")
    w("<p class='muted'>%s</p><p class='muted'>Généré par Safqa.</p></body></html>" % _e(reg.DISCLAIMER))
    return out.getvalue()


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
    for label, key in [("Travaux HT", "works_ht"), ("Révision HT", "revision_ht"), ("Total HT", "total_ht"),
                       ("TVA", "tva"), ("Total TTC", "total_ttc"), ("Retenue de garantie", "retenue"),
                       ("Pénalités", "penalties"), ("Remboursement avance", "advance_recovery"),
                       ("Cumul net TTC", "net_cumul_ttc"), ("Décomptes précédents", "previous_ttc"),
                       ("Net à payer TTC", "net_ttc")]:
        wr.writerow([label, "", "", "", "", _c(decompte.get(key))])
    return out.getvalue()


def _c(v):
    if v is None:
        return ""
    return ("%.2f" % float(v)).replace(".", ",")
