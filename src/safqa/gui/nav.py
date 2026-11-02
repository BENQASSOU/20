"""Cross-module navigation: deep links, article viewer, quick-create menu,
global search."""

from datetime import date, timedelta

import flet as ft

from .. import erp
from .. import tracking as tr
from ..analysis import articles_of
from . import ui

# Which workspace tab fixes an alert of a given category.
FLAG_TABS = {
    "Paiement": "decomptes", "Garanties": "cautions", "Quantités": "attachements", "Budget": "couts",
    "Rentabilité": "couts", "Fournisseurs": "couts", "Délais": "os", "Pénalités": "os", "Résiliation": "risques",
    "Réception": "receptions", "Documents": "pieces", "Assurances": "pieces", "Analyse IA": "obligations",
}


def flag_tab(flag):
    cat = flag.get("category") or ""
    if cat.startswith("Contrat"):
        return "obligations" if flag.get("article_key") else "pieces"
    return FLAG_TABS.get(cat, "risques")


def flag_route(pid, flag):
    return "/marche/%s?tab=%s" % (pid, flag_tab(flag))


# --------------------------------------------------------------------------
# Article viewer
# --------------------------------------------------------------------------

def find_article(store, pid, key, doc_id=None):
    docs = store.documents(pid)
    if doc_id:
        docs = sorted(docs, key=lambda d: d["id"] != doc_id)
    for d in docs:
        for a in articles_of(d):
            if a.key == key:
                return a, d
    return None, None


def show_article(app, pid, key, doc_id=None, quote=None):
    art, doc = find_article(app.store, pid, key, doc_id)
    if not art:
        ui.info(app.page, "Article", "Le texte de cet article n'est pas disponible.")
        return
    body = [ui.muted("%s · page %s" % (doc.get("filename") or "", art.page))]
    if quote:
        body.append(ft.Container(ui.txt("« %s »" % quote, 13, italic=True, color=ui.PRIMARY_DARK, selectable=True),
                                 bgcolor="#FFF7E6", border_radius=10, padding=10))
    body.append(ui.txt(art.text, 13.5, selectable=True))
    ui.info(app.page, art.label(), ft.Column(body, tight=True, spacing=10),
            [ft.TextButton(content="Ouvrir le document",
                           on_click=lambda e: (app.go("/marche/%s/doc/%s" % (pid, doc["id"]))))])


def cite(app, pid, item, doc_id=None):
    """Citation pill that opens the cited article."""
    pill = ui.cite_pill(item.get("article_label"), item.get("page"))
    if pid and item.get("article_key"):
        pill.on_click = lambda e: show_article(app, pid, item["article_key"], doc_id or item.get("doc_id"),
                                               item.get("text") or item.get("quote"))
        pill.ink = True
        pill.tooltip = "Lire l'article"
    return pill


# --------------------------------------------------------------------------
# Quick create
# --------------------------------------------------------------------------

def quick_create(app):
    from .copilot_ui import letter_dialog
    from .views import finance, more, projects, tenders
    store = app.store
    projects_list = store.projects()
    holder = {}

    def go(fn):
        def handler(e):
            ui.close(app.page, holder.get("dlg"))
            fn()
        return handler

    def pick_project(title, then):
        if not projects_list:
            ui.info(app.page, title, "Créez d'abord un marché.")
            return
        if len(projects_list) == 1:
            then(projects_list[0]["id"])
            return
        ui.form_dialog(app.page, title, [{"key": "pid", "label": "Marché", "type": "select", "required": True,
                                          "int_keys": True, "value": projects_list[0]["id"],
                                          "options": [(str(p["id"]), "%s - %s" % (p.get("ref") or "", (p.get("title") or "")[:40]))
                                                      for p in projects_list]}],
                       lambda v: then(v["pid"]), "Continuer")

    def journal():
        def then(pid):
            app.state["ws_tab_%s" % pid] = "journal"
            app.go("/marche/%s?tab=journal&new=1" % pid)
        pick_project("Journal de chantier", then)

    def attachement():
        pick_project("Attachement", lambda pid: app.go("/marche/%s?tab=attachements" % pid))

    def decompte():
        pick_project("Décompte", lambda pid: app.go("/marche/%s?tab=decomptes&new=1" % pid))

    entries = [
        ("Marché", "Nouveau marché ou contrat", ft.Icons.WORK, ui.PRIMARY, lambda: projects.new_project(app)),
        ("Appel d'offres", "Suivre une consultation", ft.Icons.GAVEL, ui.WARNING, lambda: tenders.tender_form(app)),
        ("Dépense / achat", "Facture fournisseur, paie, location", ft.Icons.SHOPPING_CART, ui.INFO,
         lambda: finance.expense_form(app)),
        ("Caution bancaire", "Provisoire, définitive, retenue", ft.Icons.SHIELD, "#7A5AF8",
         lambda: finance.guarantee_form(app)),
        ("Attachement", "Quantités exécutées", ft.Icons.STRAIGHTEN, ui.SUCCESS, attachement),
        ("Décompte", "Situation de travaux", ft.Icons.RECEIPT_LONG, ui.SUCCESS, decompte),
        ("Journal de chantier", "Entrée du jour", ft.Icons.MENU_BOOK, ui.MUTED, journal),
        ("Courrier", "Relance, prolongation, mainlevée… rédigé par Safqa IA", ft.Icons.MAIL_OUTLINE, ui.ACCENT,
         lambda: letter_dialog(app)),
        ("Tiers", "Client, fournisseur, banque", ft.Icons.CONTACTS, ui.MUTED, lambda: more.tier_form(app)),
    ]
    rows = [ui.list_row(t, sub, icon=icon, icon_color=color, on_click=go(fn)) for t, sub, icon, color, fn in entries]
    holder["dlg"] = ui.info(app.page, "Créer", ft.Column(rows, tight=True, spacing=8))


def quick_fab(app):
    return ft.FloatingActionButton(icon=ft.Icons.ADD, content="Créer", bgcolor=ui.ACCENT,
                                   on_click=lambda e: quick_create(app))


# --------------------------------------------------------------------------
# Global search
# --------------------------------------------------------------------------

def search_results(app, query):
    store = app.store
    q = (query or "").strip().lower()
    if len(q) < 2:
        return []

    def hit(*values):
        return any(q in str(v or "").lower() for v in values)

    out = []
    for p in store.projects(include_archived=True):
        if hit(p.get("ref"), p.get("title"), p.get("owner"), p.get("location"), p.get("category"), p.get("manager")):
            out.append(("Marché", "%s - %s" % (p.get("ref") or "", p.get("title") or ""), p.get("owner") or "",
                        ft.Icons.WORK, "/marche/%s" % p["id"]))
    for t in store.all("tenders"):
        if hit(t.get("ref"), t.get("title"), t.get("owner"), t.get("category")):
            out.append(("Appel d'offres", "AO %s - %s" % (t.get("ref") or "", t.get("title") or ""),
                        erp.label("tender_status", t.get("status")), ft.Icons.GAVEL, "/ao/%s" % t["id"]))
    for t in store.tiers():
        if hit(t.get("name"), t.get("ice"), t.get("city"), t.get("contact"), t.get("phone"), t.get("email")):
            out.append(("Tiers", t["name"], erp.label("tier_kind", t["kind"]), ft.Icons.CONTACTS, "/tiers/%s" % t["id"]))
    for e in store.q("SELECT * FROM expenses ORDER BY date DESC"):
        if hit(e.get("label"), e.get("ref"), store.tier_name(e.get("supplier_id"))):
            out.append(("Dépense", e.get("label") or "", "%s · %s" % (tr.fmt_date(e.get("date")), ui.money(e.get("amount_ht"), 0)),
                        ft.Icons.RECEIPT, "/marche/%s?tab=couts" % e.get("project_id")))
    for d in store.q("SELECT id, project_id, filename, doc_type FROM documents"):
        if hit(d.get("filename"), d.get("doc_type")):
            out.append(("Document", d.get("filename") or "", d.get("doc_type") or "", ft.Icons.DESCRIPTION,
                        "/marche/%s/doc/%s" % (d["project_id"], d["id"])))
    for g in store.all("guarantees"):
        if hit(g.get("ref"), erp.label("guarantee_kind", g.get("kind"))):
            out.append(("Caution", "%s %s" % (erp.label("guarantee_kind", g.get("kind")), g.get("ref") or ""),
                        ui.money(g.get("amount"), 0), ft.Icons.SHIELD,
                        "/marche/%s?tab=cautions" % g["project_id"] if g.get("project_id") else
                        ("/ao/%s" % g["tender_id"] if g.get("tender_id") else "/module/garanties")))
    for j in store.q("SELECT * FROM journal ORDER BY date DESC"):
        if hit(j.get("work_done"), j.get("incidents"), j.get("visitors")):
            out.append(("Journal", "%s - %s" % (tr.fmt_date(j.get("date")), (j.get("work_done") or "")[:60]),
                        j.get("incidents") or "", ft.Icons.MENU_BOOK, "/marche/%s?tab=journal" % j["project_id"]))
    return out[:80]


def search_view_body(app, initial=""):
    results = ft.Column(spacing=8, tight=True)

    def render(query):
        res = search_results(app, query)
        results.controls.clear()
        if len((query or "").strip()) < 2:
            results.controls.append(ui.muted("Tapez au moins 2 caractères : n° de marché, objet, maître d'ouvrage, "
                                             "fournisseur, référence de facture ou de caution, document…"))
        elif not res:
            results.controls.append(ui.empty("Aucun résultat.", ft.Icons.SEARCH_OFF))
        for kind, title, sub, icon, route in res:
            results.controls.append(ui.list_row(title, "%s · %s" % (kind, sub) if sub else kind, icon=icon,
                                                on_click=lambda e, r=route: app.go(r)))

    def changed(e):
        app.state["search_query"] = e.control.value
        render(e.control.value)
        try:
            results.update()
        except Exception:  # noqa: BLE001 - not mounted (tests)
            pass

    field = ft.TextField(value=initial, autofocus=True, hint_text="Rechercher dans tout Safqa…",
                         prefix_icon=ft.Icons.SEARCH, border_radius=12, bgcolor="#FFFFFF", on_change=changed)
    render(initial)
    return [field, results]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def mark_expense_paid(app, e):
    app.store.update("expenses", e["id"], {"status": "paye", "paid_date": date.today().isoformat()})
    ui.snack(app.page, "Dépense marquée payée")
    app.refresh()


def mark_decompte_paid(app, d):
    app.store.update("decomptes", d["id"], {"paid_date": date.today().isoformat(),
                                            "paid_amount": d.get("net_ttc"),
                                            "submitted_date": d.get("submitted_date") or d.get("date")})
    ui.snack(app.page, "Décompte n° %s encaissé" % d.get("number"))
    app.refresh()


def obligation_to_task(app, pid, f):
    days = (f.get("value") or {}).get("days")
    start = date.today()
    end = start + timedelta(days=int(days) if days else 7)
    app.store.insert("tasks", {"project_id": pid, "name": (f.get("summary") or "Obligation")[:120],
                               "start": start.isoformat(), "end": end.isoformat(), "progress": 0,
                               "notes": "%s%s" % (f.get("article_label") or "", (" p.%s" % f["page"]) if f.get("page") else ""),
                               "sort": 999})
    ui.snack(app.page, "Ajouté au planning (fin prévue le %s)" % end.strftime("%d/%m/%Y"))
