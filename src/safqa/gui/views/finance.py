"""Finances: trésorerie, créances, dépenses & achats, cautions."""

from datetime import date

import flet as ft

from ... import erp, reports
from ... import tracking as tr
from .. import ui
from ..app import page_body

SUBTABS = ["Trésorerie", "Créances", "Dépenses", "Cautions"]


def build(app):
    sub = app.state.get("finance_tab", 0)

    def change(e):
        app.state["finance_tab"] = e.control.selected_index
        app.refresh()

    tabs = ft.Tabs(length=len(SUBTABS), selected_index=sub, on_change=change,
                   content=ft.TabBar(tabs=[ft.Tab(label=t) for t in SUBTABS], scrollable=True,
                                     tab_alignment=ft.TabAlignment.START))
    body = [treasury, receivables_tab, expenses_tab, guarantees_tab][sub](app)
    fab = None
    if sub == 2:
        fab = ft.FloatingActionButton(icon=ft.Icons.ADD, content="Dépense", bgcolor=ui.ACCENT,
                                      on_click=lambda e: expense_form(app))
    elif sub == 3:
        fab = ft.FloatingActionButton(icon=ft.Icons.ADD, content="Caution", bgcolor=ui.ACCENT,
                                      on_click=lambda e: guarantee_form(app))
    content = ft.Column([ft.Container(tabs, bgcolor="#FFFFFF"), ft.Container(page_body(body), expand=True)],
                        spacing=0, expand=True)
    return "Finances", [ft.IconButton(ft.Icons.PICTURE_AS_PDF, icon_color="#FFFFFF", tooltip="Exporter",
                                      on_click=lambda e: export_current(app, sub))], fab, content


def export_current(app, sub):
    async def go():
        today = date.today().strftime("%Y%m%d")
        if sub == 3:
            data = await app.run("Génération…", reports.guarantees_pdf, app.store, app.company())
            name, mime = "Safqa_cautions_%s.pdf" % today, reports.MIME_PDF
        elif sub == 2:
            data = await app.run("Génération…", reports.expenses_csv, app.store)
            name, mime = "Safqa_depenses_%s.csv" % today, reports.MIME_CSV
        else:
            data = await app.run("Génération…", reports.treasury_pdf, app.store, app.company())
            name, mime = "Safqa_tresorerie_%s.pdf" % today, reports.MIME_PDF
        if data:
            app.export(data, name, mime)
    app.task(go)


# --------------------------------------------------------------------------
# Trésorerie
# --------------------------------------------------------------------------

def treasury(app):
    today = date.today()
    cf = erp.cashflow_forecast(app.store, today)
    pf = erp.portfolio(app.store, today)
    tin = sum(m["inflow"] for m in cf)
    tout = sum(m["outflow"] for m in cf)
    c = [ui.kpi_grid([
        ui.kpi("Encaissements attendus (6 mois)", ui.short_money(tin), ft.Icons.SOUTH_WEST, ui.SUCCESS),
        ui.kpi("Décaissements prévus", ui.short_money(tout), ft.Icons.NORTH_EAST, ui.DANGER),
        ui.kpi("Solde prévisionnel", ui.short_money(tin - tout), ft.Icons.ACCOUNT_BALANCE,
               ui.SUCCESS if tin >= tout else ui.DANGER),
        ui.kpi("Encaissé (cumul)", ui.short_money(pf["totals"]["paid_ttc"]), ft.Icons.PAYMENTS_OUTLINED, ui.INFO),
    ])]
    c.append(ui.section("Prévision mensuelle (TTC)"))
    c.append(ui.card([ui.bar_chart([(m["month"], m["inflow"], m["outflow"]) for m in cf], [ui.SUCCESS, ui.DANGER],
                                   ["Encaissements", "Décaissements"])]))
    rows = [ft.DataRow(cells=[ft.DataCell(ui.txt(m["month"], 12.5)), ft.DataCell(ui.txt(ui.short_money(m["inflow"]), 12.5)),
                              ft.DataCell(ui.txt(ui.short_money(m["outflow"]), 12.5)),
                              ft.DataCell(ui.txt(ui.short_money(m["cumulative"]), 12.5, ft.FontWeight.W_600,
                                                 ui.DANGER if m["cumulative"] < 0 else ui.TEXT))]) for m in cf]
    c.append(ui.card([ft.Row([ft.DataTable(columns=[ft.DataColumn(ui.txt("Mois", 12)),
                                                    ft.DataColumn(ui.txt("Entrées", 12), numeric=True),
                                                    ft.DataColumn(ui.txt("Sorties", 12), numeric=True),
                                                    ft.DataColumn(ui.txt("Cumul", 12), numeric=True)],
                                           rows=rows, column_spacing=14, horizontal_margin=4,
                                           data_row_min_height=36, heading_row_height=36)],
                             scroll=ft.ScrollMode.AUTO)], padding=8))
    total = sum(v for _k, v in pf["aging"]) or 0
    c.append(ui.section("Antériorité des créances"))
    c.append(ui.card([ui.hbar(k, v, total, ui.DANGER if k in ("61-90 j", "> 90 j") else ui.WARNING)
                      for k, v in pf["aging"]], spacing=10))
    c.append(ui.muted("Au-delà du délai réglementaire de paiement (60 jours en règle générale), des intérêts "
                      "moratoires sont dus : pensez à les réclamer par écrit."))
    return c


# --------------------------------------------------------------------------
# Créances
# --------------------------------------------------------------------------

def receivables_tab(app):
    rows = erp.receivables(app.store, date.today())
    total = sum(r["decompte"].get("net_ttc") or 0 for r in rows)
    late = sum(r["decompte"].get("net_ttc") or 0 for r in rows if r["status"]["late"])
    c = [ui.kpi_grid([ui.kpi("Décomptes non payés", ui.short_money(total), ft.Icons.HOURGLASS_BOTTOM, ui.WARNING,
                             "%d décompte(s)" % len(rows)),
                      ui.kpi("Dont hors délai", ui.short_money(late), ft.Icons.ALARM, ui.DANGER,
                             "Intérêts moratoires exigibles")])]
    if not rows:
        c.append(ui.empty("Aucune créance en attente.", ft.Icons.CHECK_CIRCLE_OUTLINE))
    for r in rows:
        d, p, st = r["decompte"], r["project"], r["status"]
        sub = "Constaté le %s" % tr.fmt_date(d.get("submitted_date")) if d.get("submitted_date") else "Date de constatation à saisir"
        c.append(ui.list_row("Décompte n° %s - %s" % (d.get("number"), p.get("ref") or ""), "%s · %s" % (p.get("title") or "", sub),
                             ui.money(d.get("net_ttc"), 0),
                             ("%d j / %d j" % (st["days"], st["limit"])) if st["days"] is not None else "",
                             icon=ft.Icons.RECEIPT_LONG, icon_color=ui.DANGER if st["late"] else ui.WARNING,
                             pills=[ui.pill("Hors délai", *ui.SEVERITY["critique"][:2])] if st["late"] else None,
                             on_click=lambda e, d=d: payment_form(app, d)))
    return c


def payment_form(app, d):
    def save(v):
        app.store.update("decomptes", d["id"], {"submitted_date": v["submitted_date"], "paid_date": v["paid_date"],
                                                "paid_amount": v["paid_amount"] if v["paid_date"] else None})
        ui.snack(app.page, "Paiement enregistré")
        app.refresh()
    ui.form_dialog(app.page, "Décompte n° %s - paiement" % d.get("number"), [
        {"key": "submitted_date", "label": "Date de constatation / dépôt", "type": "date", "value": d.get("submitted_date")},
        {"key": "paid_date", "label": "Date de paiement", "type": "date", "value": d.get("paid_date")},
        {"key": "paid_amount", "label": "Montant encaissé (DH)", "type": "number",
         "value": d.get("paid_amount") or d.get("net_ttc")}], save)


# --------------------------------------------------------------------------
# Dépenses & achats
# --------------------------------------------------------------------------

def expenses_tab(app, project_id=None):
    store = app.store
    key = "exp_filter_%s" % (project_id or "all")
    flt = app.state.get(key, "tous")
    sql = "SELECT * FROM expenses" + (" WHERE project_id=?" if project_id else "") + " ORDER BY date DESC, id DESC"
    rows = store.q(sql, (project_id,) if project_id else ())
    total = sum(e.get("amount_ht") or 0 for e in rows)
    unpaid = sum(erp.expense_ttc(e) for e in rows if e.get("status") != "paye")

    def set_flt(code):
        app.state[key] = code
        app.refresh()

    chips = [ft.Chip(label=ui.txt(lbl, 12.5), selected=flt == code, on_select=lambda e, c=code: set_flt(c))
             for code, lbl in [("tous", "Toutes")] + erp.EXPENSE_STATUS]
    c = [ui.kpi_grid([ui.kpi("Dépenses HT", ui.short_money(total), ft.Icons.SHOPPING_CART_OUTLINED, ui.PRIMARY,
                             "%d opération(s)" % len(rows)),
                      ui.kpi("Reste à payer TTC", ui.short_money(unpaid), ft.Icons.PAYMENTS_OUTLINED, ui.WARNING)]),
         ft.Row(chips, spacing=6, scroll=ft.ScrollMode.AUTO)]
    projects = {p["id"]: p for p in store.projects(include_archived=True)}
    today = date.today()
    shown = 0
    for e in rows:
        st = e.get("status") or "engage"
        if flt != "tous" and st != flt:
            continue
        shown += 1
        due = tr.parse_date(e.get("due_date"))
        overdue = st == "facture" and due and due < today
        pills = [ui.status_pill(st, erp.label("expense_status", st)),
                 ui.pill(erp.label("expense_category", e.get("category")), ui.MUTED, "#F2F4F7")]
        if overdue:
            pills.append(ui.pill("Échue", *ui.SEVERITY["élevé"][:2]))
        p = projects.get(e.get("project_id")) or {}
        sub = " · ".join(x for x in [store.tier_name(e.get("supplier_id")), tr.fmt_date(e.get("date")),
                                     None if project_id else (p.get("ref") or "")] if x)
        c.append(ui.list_row(e.get("label") or "Dépense", sub, ui.money(e.get("amount_ht"), 0), "HT",
                             icon=ft.Icons.RECEIPT, icon_color=ui.STATUS_COLORS.get(st, ui.MUTED), pills=pills,
                             on_click=lambda ev, e=e: expense_form(app, e["id"])))
    if not shown:
        c.append(ui.empty("Aucune dépense.", ft.Icons.SHOPPING_CART_OUTLINED,
                          ui.primary_btn("Ajouter une dépense", lambda e: expense_form(app, project_id=project_id),
                                         ft.Icons.ADD)))
    return c


def expense_form(app, eid=None, project_id=None):
    store = app.store
    e = store.get_row("expenses", eid) if eid else {"project_id": project_id, "date": date.today().isoformat(),
                                                     "tva_pct": 20, "status": "facture"}
    projects = [(str(p["id"]), "%s - %s" % (p.get("ref") or "", (p.get("title") or "")[:40])) for p in store.projects()]
    suppliers = [(str(t["id"]), t["name"]) for t in store.tiers() if t["kind"] in ("fournisseur", "sous_traitant", "bet", "autre")]
    specs = [
        {"key": "project_id", "label": "Marché", "type": "select", "options": projects, "value": e.get("project_id"),
         "required": True, "int_keys": True},
        {"key": "date", "label": "Date", "type": "date", "value": e.get("date"), "required": True},
        {"key": "category", "label": "Poste de coût", "type": "select", "options": erp.EXPENSE_CATEGORIES,
         "value": e.get("category") or "materiaux", "required": True},
        {"key": "label", "label": "Libellé", "value": e.get("label"), "required": True},
        {"key": "supplier_id", "label": "Fournisseur / sous-traitant", "type": "select", "options": suppliers,
         "value": e.get("supplier_id"), "int_keys": True},
        {"key": "ref", "label": "N° de facture / bon de commande", "value": e.get("ref")},
        {"key": "amount_ht", "label": "Montant HT (DH)", "type": "number", "value": e.get("amount_ht"), "required": True},
        {"key": "tva_pct", "label": "TVA (%)", "type": "number", "value": e.get("tva_pct")},
        {"key": "status", "label": "Statut", "type": "select", "options": erp.EXPENSE_STATUS, "value": e.get("status")},
        {"key": "due_date", "label": "Échéance de paiement", "type": "date", "value": e.get("due_date")},
        {"key": "paid_date", "label": "Payé le", "type": "date", "value": e.get("paid_date")},
        {"key": "notes", "label": "Notes", "type": "multiline", "value": e.get("notes")},
    ]

    def save(v):
        if v.get("paid_date") and v.get("status") != "paye":
            v["status"] = "paye"
        store.save("expenses", v, eid)
        ui.snack(app.page, "Dépense enregistrée")
        app.refresh()

    def delete():
        store.delete("expenses", eid)
        app.refresh()

    if not suppliers:
        specs[4]["hint"] = "Ajoutez vos fournisseurs dans Plus › Tiers"
    ui.form_dialog(app.page, "Modifier la dépense" if eid else "Nouvelle dépense", specs, save,
                   on_delete=delete if eid else None)


# --------------------------------------------------------------------------
# Cautions
# --------------------------------------------------------------------------

def guarantees_tab(app, project_id=None):
    store = app.store
    today = date.today()
    sql = "SELECT * FROM guarantees" + (" WHERE project_id=?" if project_id else "") + " ORDER BY status, expiry_date"
    rows = store.q(sql, (project_id,) if project_id else ())
    summary = erp.guarantees_summary(store, today)
    c = []
    if not project_id:
        c.append(ui.kpi_grid([ui.kpi("Encours de cautions", ui.short_money(summary["total"]), ft.Icons.SHIELD_OUTLINED,
                                     "#7A5AF8", "%d caution(s)" % summary["count"]),
                              ui.kpi("À traiter", str(summary["alerts"]), ft.Icons.NOTIFICATION_IMPORTANT_OUTLINED,
                                     ui.DANGER, "Échues ou < 30 jours")]))
        if summary["by_bank"]:
            c.append(ui.section("Encours par banque"))
            c.append(ui.card([ui.hbar(b, v, summary["total"], "#7A5AF8") for b, v in summary["by_bank"]], spacing=10))
        c.append(ui.section("Toutes les cautions"))
    if not rows:
        c.append(ui.empty("Aucune caution enregistrée.", ft.Icons.SHIELD_OUTLINED,
                          ui.primary_btn("Ajouter une caution", lambda e: guarantee_form(app, defaults={"project_id": project_id}),
                                         ft.Icons.ADD)))
    for g in rows:
        info = erp.guarantee_info(g, today)
        st = g.get("status") or "active"
        pills = [ui.status_pill(st, erp.label("guarantee_status", st))]
        if info["expired"]:
            pills.append(ui.pill("Échue", *ui.SEVERITY["critique"][:2]))
        elif info["expiring"]:
            pills.append(ui.pill("Expire " + ui.days_label(info["days_to_expiry"]).lower(), *ui.SEVERITY["moyen"][:2]))
        target = ""
        if g.get("project_id"):
            target = "Marché %s" % ((store.project(g["project_id"]) or {}).get("ref") or "")
        elif g.get("tender_id"):
            target = "AO %s" % ((store.get_row("tenders", g["tender_id"]) or {}).get("ref") or "")
        c.append(ui.list_row("%s %s" % (erp.label("guarantee_kind", g.get("kind")), g.get("ref") or ""),
                             " · ".join(x for x in [target, store.tier_name(g.get("bank_id")),
                                                    "échéance " + tr.fmt_date(g.get("expiry_date"))] if x),
                             ui.money(g.get("amount"), 0),
                             ("frais ≈ %s" % ui.short_money(info["fees_estimate"])) if info["fees_estimate"] else None,
                             icon=ft.Icons.SHIELD, icon_color=ui.STATUS_COLORS.get(st, ui.MUTED), pills=pills,
                             on_click=lambda e, g=g: guarantee_form(app, g["id"])))
    return c


def guarantee_form(app, gid=None, defaults=None):
    store = app.store
    g = store.get_row("guarantees", gid) if gid else dict({"status": "active", "issue_date": date.today().isoformat(),
                                                             "commission_pct": 1.5}, **(defaults or {}))
    banks = [(str(t["id"]), t["name"]) for t in store.tiers("banque")]
    projects = [(str(p["id"]), "%s - %s" % (p.get("ref") or "", (p.get("title") or "")[:40])) for p in store.projects()]
    tenders = [(str(t["id"]), "AO %s - %s" % (t.get("ref") or "", (t.get("title") or "")[:40])) for t in store.all("tenders")]
    specs = [
        {"key": "kind", "label": "Type", "type": "select", "options": erp.GUARANTEE_KINDS, "value": g.get("kind") or "definitive",
         "required": True},
        {"key": "project_id", "label": "Marché", "type": "select", "options": projects, "value": g.get("project_id"),
         "int_keys": True},
        {"key": "tender_id", "label": "ou appel d'offres", "type": "select", "options": tenders,
         "value": g.get("tender_id"), "int_keys": True},
        {"key": "bank_id", "label": "Banque", "type": "select", "options": banks, "value": g.get("bank_id"),
         "int_keys": True},
        {"key": "ref", "label": "Référence", "value": g.get("ref")},
        {"key": "amount", "label": "Montant (DH)", "type": "number", "value": g.get("amount"), "required": True},
        {"key": "issue_date", "label": "Date d'émission", "type": "date", "value": g.get("issue_date")},
        {"key": "expiry_date", "label": "Date d'échéance", "type": "date", "value": g.get("expiry_date")},
        {"key": "commission_pct", "label": "Commission annuelle (%)", "type": "number", "value": g.get("commission_pct")},
        {"key": "status", "label": "Statut", "type": "select", "options": erp.GUARANTEE_STATUS, "value": g.get("status")},
        {"key": "notes", "label": "Notes", "type": "multiline", "value": g.get("notes")},
    ]

    def save(v):
        store.save("guarantees", v, gid)
        if v.get("project_id") and v.get("kind") == "definitive":
            store.set_check(v["project_id"], "CAUTION_DEF", True, v.get("issue_date"))
        ui.snack(app.page, "Caution enregistrée")
        app.refresh()

    def delete():
        store.delete("guarantees", gid)
        app.refresh()
    ui.form_dialog(app.page, "Modifier la caution" if gid else "Nouvelle caution", specs, save,
                   on_delete=delete if gid else None)
