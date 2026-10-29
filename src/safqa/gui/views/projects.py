"""Marchés: list, search, filters and the create/edit form."""

from datetime import date

import flet as ft

from ... import erp
from .. import ui
from ..app import page_body
from .dashboard import project_tile

FILTERS = [("actifs", "En cours"), ("receptionne", "Réceptionnés"), ("clos", "Clôturés"), ("tous", "Tous")]


def build(app):
    st = app.state
    flt = st.get("projects_filter", "actifs")
    query = st.get("projects_query", "")
    pf = erp.portfolio(app.store, date.today())
    rows = []
    for row in pf["rows"]:
        p = row["state"]["project"]
        status = p.get("status") or "en_cours"
        if flt == "actifs" and status not in ("en_cours", "suspendu"):
            continue
        if flt in ("receptionne", "clos") and status != flt:
            continue
        hay = " ".join(str(p.get(k) or "") for k in ("ref", "title", "owner", "location", "category")).lower()
        if query and query.lower() not in hay:
            continue
        rows.append(row)

    def on_search(e):
        st["projects_query"] = e.control.value
        app.refresh()

    def on_filter(code):
        st["projects_filter"] = code
        app.refresh()

    controls = [
        ft.TextField(value=query, hint_text="Rechercher (n°, objet, maître d'ouvrage, ville)…",
                     prefix_icon=ft.Icons.SEARCH, border_radius=12, bgcolor="#FFFFFF", dense=True,
                     on_submit=on_search),
        ft.Row([ft.Chip(label=ui.txt(lbl, 12.5), selected=flt == k, on_select=lambda e, k=k: on_filter(k))
                for k, lbl in FILTERS], spacing=6, scroll=ft.ScrollMode.AUTO),
    ]
    t = pf["totals"]
    controls.append(ui.card([ui.kv("Marchés", str(t["projects"])),
                             ui.kv("Montant total HT", ui.money(t["contract_ht"], 0), strong=True),
                             ui.kv("Facturé HT", ui.money(t["invoiced_ht"], 0)),
                             ui.kv("Reste à réaliser HT", ui.money(t["backlog_ht"], 0))], padding=12, spacing=5))
    if not rows:
        controls.append(ui.empty("Aucun marché pour ce filtre.", ft.Icons.WORK_OFF_OUTLINED,
                                 ui.primary_btn("Nouveau marché", lambda e: project_form(app), ft.Icons.ADD)))
    for row in rows:
        controls.append(project_tile(app, row))
    fab = ft.FloatingActionButton(icon=ft.Icons.ADD, content="Marché", on_click=lambda e: new_project(app),
                                  bgcolor=ui.ACCENT)
    return "Marchés", [], fab, page_body(controls)


def new_project(app):
    ok, why = app.sub.can("project", len(app.store.projects()))
    if not ok:
        ui.info(app.page, "Limite de votre formule", why + "\n\nArchivez un marché terminé ou changez de formule.")
        return
    project_form(app)


def project_form(app, pid=None, prefill=None):
    store = app.store
    p = store.project(pid) if pid else dict(prefill or {})
    clients = [(str(t["id"]), t["name"]) for t in store.tiers("client")]
    specs = [
        {"key": "ref", "label": "N° du marché", "value": p.get("ref"), "required": True},
        {"key": "title", "label": "Objet du marché", "value": p.get("title"), "type": "multiline", "required": True},
        {"key": "client_id", "label": "Maître d'ouvrage (fiche tiers)", "type": "select", "options": clients,
         "value": p.get("client_id"), "int_keys": True},
        {"key": "owner", "label": "Maître d'ouvrage (libellé)", "value": p.get("owner"),
         "hint": "Rempli automatiquement depuis la fiche tiers"},
        {"key": "category", "label": "Catégorie", "type": "select", "value": p.get("category"),
         "options": [(c, c) for c in erp.PROJECT_CATEGORIES]},
        {"key": "location", "label": "Lieu d'exécution", "value": p.get("location")},
        {"key": "amount_ttc", "label": "Montant TTC (DH)", "type": "number", "value": p.get("amount_ttc")},
        {"key": "approval_notif_date", "label": "Notification de l'approbation", "type": "date",
         "value": p.get("approval_notif_date")},
        {"key": "delay_days", "label": "Délai d'exécution (jours)", "type": "int", "value": p.get("delay_days")},
        {"key": "manager", "label": "Chef de projet", "value": p.get("manager")},
        {"key": "status", "label": "Statut", "type": "select", "value": p.get("status") or "en_cours",
         "options": erp.PROJECT_STATUS},
    ]

    def save(v):
        if v.get("client_id") and not v.get("owner"):
            v["owner"] = store.tier_name(v["client_id"])
        if v.get("delay_days") and not p.get("delay_months"):
            v["delay_months"] = None
        if prefill and prefill.get("tender_id"):
            v["tender_id"] = prefill["tender_id"]
        new_id = store.save_project(v, pid)
        if prefill and prefill.get("tender_id"):
            store.update("tenders", prefill["tender_id"], {"project_id": new_id, "status": "gagne"})
        ui.snack(app.page, "Marché enregistré")
        if pid:
            app.refresh()
        else:
            app.go("/marche/%s" % new_id)

    ui.form_dialog(app.page, "Modifier le marché" if pid else "Nouveau marché", specs, save)
