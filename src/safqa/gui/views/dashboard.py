"""Accueil: portfolio dashboard."""

from datetime import date

import flet as ft

from ... import demo, erp
from .. import ui
from ..app import page_body

SEV_ORDER = {"critique": 0, "élevé": 1, "moyen": 2, "info": 3}


def build(app):
    store = app.store
    today = date.today()
    if store.is_empty():
        return "Tableau de bord", [], None, page_body([welcome(app)])
    pf = erp.portfolio(store, today)
    t = pf["totals"]
    c = []
    c.append(ft.Container(ft.Column([
        ui.txt("Bonjour", 13, color="#CFE3EA"),
        ui.txt(app.company().get("name") or "Mon entreprise", 20, ft.FontWeight.W_700, "#FFFFFF"),
        ui.txt("Situation au %s · %d marché(s) en cours" % (today.strftime("%d/%m/%Y"), t["active_projects"]),
               12.5, color="#CFE3EA")], spacing=2, tight=True),
        padding=16, border_radius=16,
        gradient=ft.LinearGradient(colors=[ui.PRIMARY, "#13708F"], begin=ft.Alignment.TOP_LEFT,
                                   end=ft.Alignment.BOTTOM_RIGHT)))
    c.append(ui.kpi_grid([
        ui.kpi("Carnet de commandes HT", ui.short_money(t["backlog_ht"]), ft.Icons.INVENTORY_2_OUTLINED, ui.PRIMARY,
               "Reste à réaliser", on_click=lambda e: set_tab(app, 1)),
        ui.kpi("Facturé %d HT" % today.year, ui.short_money(t["year_invoiced_ht"]), ft.Icons.RECEIPT_LONG_OUTLINED,
               ui.SUCCESS, "Décomptes émis"),
        ui.kpi("Créances clients", ui.short_money(t["unpaid_ttc"]), ft.Icons.HOURGLASS_BOTTOM, ui.WARNING,
               "Décomptes non payés", on_click=lambda e: open_finance(app, 1)),
        ui.kpi("Marge brute HT", ui.short_money(t["margin_ht"]), ft.Icons.TRENDING_UP,
               ui.SUCCESS if t["margin_ht"] >= 0 else ui.DANGER, "%.1f %% du facturé" % t["margin_pct"]),
        ui.kpi("Dettes fournisseurs", ui.short_money(t["payables_ttc"]), ft.Icons.LOCAL_SHIPPING_OUTLINED, ui.INFO,
               "Non réglées", on_click=lambda e: open_finance(app, 2)),
        ui.kpi("Cautions en cours", ui.short_money(t["guarantees"]), ft.Icons.SHIELD_OUTLINED, "#7A5AF8",
               "%d à traiter" % pf["guarantees"]["alerts"], on_click=lambda e: open_finance(app, 3)),
    ]))

    # ---- alerts
    alerts = []
    for row in pf["rows"]:
        s = row["state"]
        for f in s["flags"]:
            if f["severity"] in ("critique", "élevé"):
                alerts.append((s, f))
    alerts.sort(key=lambda x: SEV_ORDER.get(x[1]["severity"], 9))
    c.append(ui.section("Alertes prioritaires (%d)" % len(alerts)))
    if not alerts:
        c.append(ui.card([ui.muted("Aucune alerte critique. Tout est sous contrôle.")]))
    for s, f in alerts[:5]:
        pid = s["project"]["id"]
        c.append(ui.list_row(f["title"], "%s · %s" % (s["project"].get("ref") or "", f.get("detail") or ""),
                             icon=ft.Icons.WARNING_AMBER_ROUNDED, icon_color=ui.SEVERITY[f["severity"]][0],
                             pills=[ui.sev_pill(f["severity"]), ui.pill(f["category"], ui.MUTED, "#F2F4F7")],
                             on_click=lambda e, pid=pid: app.go("/marche/%s?tab=risques" % pid)))

    # ---- agenda
    ev = [e for e in erp.agenda(store, today, horizon=21, past=30) if e["days"] >= -30]
    c.append(ui.section("Prochaines échéances", ui.text_btn("Échéancier", lambda e: app.go("/module/echeancier"))))
    if not ev:
        c.append(ui.card([ui.muted("Aucune échéance dans les 3 prochaines semaines.")]))
    for e in ev[:6]:
        color = ui.DANGER if e["days"] < 0 else (ui.WARNING if e["days"] <= 7 else ui.INFO)
        c.append(ui.list_row(e["title"], e["detail"] or e["kind"], ui.days_label(e["days"]),
                             e["date"].strftime("%d/%m/%Y"), icon=ft.Icons.EVENT, icon_color=color,
                             on_click=(lambda ev_, r=e["route"]: app.go(r)) if e.get("route") else None))

    # ---- activity chart
    c.append(ui.section("Activité des 12 derniers mois (HT)"))
    c.append(ui.card([ui.bar_chart([(lbl, inv, cost) for lbl, inv, cost, _col in pf["series"]],
                                   [ui.PRIMARY, ui.ACCENT], ["Travaux facturés", "Dépenses"])]))

    # ---- pipeline
    pl = pf["pipeline"]
    c.append(ui.section("Appels d'offres", ui.text_btn("Voir tout", lambda e: set_tab(app, 2))))
    chips = [ui.status_pill(code, "%s : %d" % (v["label"], v["count"])) for code, v in pl["by_status"].items()
             if v["count"]]
    rate = ("Taux de réussite : %d %%" % (round(pl["win_rate"] * 100))) if pl["win_rate"] is not None else ""
    items = [ui.pills_row(chips), ui.kv("Offres en cours (montant)", ui.money(pl["active_amount"], 0), strong=True)]
    if rate:
        items.append(ui.muted(rate))
    for days, tnd in pl["upcoming"][:3]:
        items.append(ui.list_row("AO %s - %s" % (tnd.get("ref") or "", tnd.get("title") or ""),
                                 tnd.get("owner") or "", ui.days_label(days), "dépôt des offres",
                                 icon=ft.Icons.GAVEL, icon_color=ui.WARNING if days <= 7 else ui.INFO,
                                 on_click=lambda e, tid=tnd["id"]: app.go("/ao/%s" % tid)))
    c.append(ui.card(items))

    # ---- projects
    c.append(ui.section("Marchés en cours", ui.text_btn("Tous les marchés", lambda e: set_tab(app, 1))))
    for row in pf["rows"]:
        s = row["state"]
        if (s["project"].get("status") or "en_cours") not in ("en_cours", "suspendu"):
            continue
        c.append(project_tile(app, row))
    return "Tableau de bord", [ft.IconButton(ft.Icons.PICTURE_AS_PDF, icon_color="#FFFFFF", tooltip="Rapport PDF",
                                             on_click=lambda e: export_portfolio(app))], None, page_body(c)


def project_tile(app, row):
    s = row["state"]
    p, f, sched = s["project"], s["finance"], s["schedule"]
    late = sched["late_days"]
    time_ratio = sched["progress"] if sched["start"] else 0
    pills = []
    if row["critical"]:
        pills.append(ui.pill("%d critique(s)" % row["critical"], *ui.SEVERITY["critique"][:2]))
    if row["high"]:
        pills.append(ui.pill("%d élevée(s)" % row["high"], *ui.SEVERITY["élevé"][:2]))
    pills.append(ui.status_pill(p.get("status") or "en_cours", erp.label("project_status", p.get("status") or "en_cours")))
    return ui.card([
        ft.Row([ui.bold(p.get("title") or "Sans titre", 14.5, max_lines=2, expand=True),
                ui.txt(ui.short_money(f["contract_ttc"]), 13, ft.FontWeight.W_600)]),
        ui.muted("N° %s · %s" % (p.get("ref") or "-", p.get("owner") or "-"), max_lines=1),
        ft.Row([ft.Column([ui.muted("Délai consommé", 11), ui.progress(time_ratio, ui.DANGER if late else ui.PRIMARY)],
                          expand=True, spacing=3),
                ft.Column([ui.muted("Avancement", 11), ui.progress(f["progress"], ui.SUCCESS)], expand=True, spacing=3)],
               spacing=12),
        ui.muted(("Retard de %d jours" % late) if late else (
            "Fin prévue le %s" % sched["end"].strftime("%d/%m/%Y") if sched.get("end") else "Non démarré"),
            12, color=ui.DANGER if late else ui.MUTED),
        ui.pills_row(pills)],
        accent=ui.DANGER if row["critical"] else (ui.WARNING if row["high"] else ui.SUCCESS),
        on_click=lambda e, pid=p["id"]: app.go("/marche/%s" % pid))


def set_tab(app, i):
    app.tab = i
    app.refresh()


def open_finance(app, sub):
    app.state["finance_tab"] = sub
    set_tab(app, 3)


def export_portfolio(app):
    from ... import reports

    async def go():
        data = await app.run("Génération du rapport…", reports.portfolio_pdf, app.store, app.company())
        if data:
            app.export(data, "Safqa_portefeuille_%s.pdf" % date.today().strftime("%Y%m%d"), reports.MIME_PDF)
    app.task(go)


def welcome(app):
    def load_demo(e):
        async def go():
            await app.run("Chargement des données de démonstration…", demo.load_demo, app.store)
            app.refresh()
        app.task(go)

    def new_project(e):
        from .projects import project_form
        project_form(app)

    return ui.card([
        ft.Icon(ft.Icons.ROCKET_LAUNCH_OUTLINED, size=40, color=ui.PRIMARY),
        ui.txt("Bienvenue dans Safqa ERP", 20, ft.FontWeight.W_700),
        ui.txt("La gestion complète de vos marchés publics de travaux : appels d'offres, analyse des CPS par "
               "l'IA avec citations, ordres de service, attachements, décomptes, budget et dépenses, cautions, "
               "trésorerie et alertes de risques.", 14),
        ui.primary_btn("Voir la démonstration", load_demo, ft.Icons.AUTO_AWESOME, expand=True),
        ui.outline_btn("Créer mon premier marché", new_project, ft.Icons.ADD, expand=True),
        ui.muted("Les données de démonstration peuvent être effacées à tout moment dans Plus › Paramètres."),
    ], padding=20, spacing=12)
