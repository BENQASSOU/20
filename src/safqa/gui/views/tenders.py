"""Appels d'offres: pipeline, detail and conversion into a contract."""

from datetime import date

import flet as ft

from ... import erp
from ... import tracking as tr
from .. import ui
from ..app import page_body, sub_appbar


def build(app):
    store = app.store
    today = date.today()
    tenders = store.all("tenders", "deposit_date DESC")
    pl = erp.tender_pipeline(tenders, today)
    flt = app.state.get("tender_filter", "actifs")

    def set_filter(code):
        app.state["tender_filter"] = code
        app.refresh()

    chips = [ft.Chip(label=ui.txt("En cours (%d)" % pl["active_count"], 12.5), selected=flt == "actifs",
                     on_select=lambda e: set_filter("actifs"))]
    for code, v in pl["by_status"].items():
        chips.append(ft.Chip(label=ui.txt("%s (%d)" % (v["label"], v["count"]), 12.5), selected=flt == code,
                             on_select=lambda e, c=code: set_filter(c)))
    chips.append(ft.Chip(label=ui.txt("Tous", 12.5), selected=flt == "tous", on_select=lambda e: set_filter("tous")))
    c = [ft.Row(chips, scroll=ft.ScrollMode.AUTO, spacing=6)]
    c.append(ui.kpi_grid([
        ui.kpi("Offres en cours", str(pl["active_count"]), ft.Icons.PENDING_ACTIONS, ui.INFO,
               ui.short_money(pl["active_amount"])),
        ui.kpi("Taux de réussite", ("%d %%" % (round(pl["win_rate"] * 100))) if pl["win_rate"] is not None else "-",
               ft.Icons.EMOJI_EVENTS_OUTLINED, ui.SUCCESS,
               "%d gagné(s) / %d perdu(s)" % (pl["by_status"]["gagne"]["count"], pl["by_status"]["perdu"]["count"])),
    ]))
    shown = 0
    for t in tenders:
        st = t.get("status") or "veille"
        if flt == "actifs" and st not in ("veille", "etude", "soumis"):
            continue
        if flt not in ("actifs", "tous") and st != flt:
            continue
        shown += 1
        c.append(tender_tile(app, t, today))
    if not shown:
        c.append(ui.empty("Aucun appel d'offres pour ce filtre.", ft.Icons.GAVEL,
                          ui.primary_btn("Nouvel appel d'offres", lambda e: tender_form(app), ft.Icons.ADD)))
    fab = ft.FloatingActionButton(icon=ft.Icons.ADD, content="AO", on_click=lambda e: tender_form(app),
                                  bgcolor=ui.ACCENT)
    return "Appels d'offres", [], fab, page_body(c)


def tender_tile(app, t, today):
    st = t.get("status") or "veille"
    dd = tr.parse_date(t.get("deposit_date"))
    days = (dd - today).days if dd else None
    pills = [ui.status_pill(st, erp.label("tender_status", st))]
    if days is not None and st in ("veille", "etude"):
        color = ui.DANGER if days <= 3 else (ui.WARNING if days <= 10 else ui.INFO)
        pills.append(ui.pill("Dépôt " + ui.days_label(days).lower(), color, ui._tint(color)))
    if t.get("category"):
        pills.append(ui.pill(t["category"], ui.MUTED, "#F2F4F7"))
    amount = t.get("bid_ttc") or t.get("estimate_ttc")
    return ui.card([
        ft.Row([ui.bold("AO n° %s" % (t.get("ref") or "-"), 14, expand=True),
                ui.txt(ui.short_money(amount), 13.5, ft.FontWeight.W_600)]),
        ui.txt(t.get("title") or "", 13.5, max_lines=2),
        ui.muted(t.get("owner") or "", max_lines=1),
        ui.pills_row(pills)],
        accent=ui.STATUS_COLORS.get(st, ui.MUTED), on_click=lambda e: app.go("/ao/%s" % t["id"]))


def tender_form(app, tid=None):
    store = app.store
    t = store.get_row("tenders", tid) if tid else {}
    clients = [(str(x["id"]), x["name"]) for x in store.tiers("client")]
    specs = [
        {"key": "ref", "label": "N° de l'appel d'offres", "value": t.get("ref"), "required": True},
        {"key": "title", "label": "Objet", "type": "multiline", "value": t.get("title"), "required": True},
        {"key": "client_id", "label": "Maître d'ouvrage (fiche tiers)", "type": "select", "options": clients,
         "value": t.get("client_id"), "int_keys": True},
        {"key": "owner", "label": "Maître d'ouvrage (libellé)", "value": t.get("owner")},
        {"key": "category", "label": "Catégorie", "type": "select", "value": t.get("category"),
         "options": [(c, c) for c in erp.PROJECT_CATEGORIES]},
        {"key": "location", "label": "Lieu", "value": t.get("location")},
        {"key": "estimate_ttc", "label": "Estimation du maître d'ouvrage TTC", "type": "number",
         "value": t.get("estimate_ttc")},
        {"key": "deposit_date", "label": "Date limite de dépôt", "type": "date", "value": t.get("deposit_date")},
        {"key": "opening_date", "label": "Ouverture des plis", "type": "date", "value": t.get("opening_date")},
        {"key": "caution_amount", "label": "Caution provisoire (DH)", "type": "number", "value": t.get("caution_amount")},
        {"key": "qualification", "label": "Qualification / classification exigée", "value": t.get("qualification")},
        {"key": "status", "label": "Statut", "type": "select", "value": t.get("status") or "veille",
         "options": erp.TENDER_STATUS},
        {"key": "bid_ttc", "label": "Notre offre TTC", "type": "number", "value": t.get("bid_ttc")},
        {"key": "winner", "label": "Attributaire (si perdu)", "value": t.get("winner")},
        {"key": "winning_bid_ttc", "label": "Offre retenue TTC", "type": "number", "value": t.get("winning_bid_ttc")},
        {"key": "notes", "label": "Notes (go / no-go, risques, partenaires)", "type": "multiline", "value": t.get("notes")},
    ]

    def save(v):
        if v.get("client_id") and not v.get("owner"):
            v["owner"] = store.tier_name(v["client_id"])
        v["updated_at"] = date.today().isoformat()
        if not tid:
            v["created_at"] = date.today().isoformat()
        new_id = store.save("tenders", v, tid)
        ui.snack(app.page, "Appel d'offres enregistré")
        if tid:
            app.refresh()
        else:
            app.go("/ao/%s" % new_id)

    def delete():
        store.delete("tenders", tid)
        app.go("/")

    ui.form_dialog(app.page, "Modifier l'AO" if tid else "Nouvel appel d'offres", specs, save,
                   on_delete=delete if tid else None)


def detail_view(app, tid):
    store = app.store
    t = store.get_row("tenders", tid)
    if not t:
        return ft.View(route="/ao/%s" % tid, appbar=sub_appbar("Introuvable"), controls=[ui.empty("AO supprimé")])
    today = date.today()
    st = t.get("status") or "veille"
    dd = tr.parse_date(t.get("deposit_date"))
    c = []
    head = [ui.pills_row([ui.status_pill(st, erp.label("tender_status", st))] +
                         ([ui.pill(t["category"], ui.MUTED, "#F2F4F7")] if t.get("category") else [])),
            ui.txt(t.get("title") or "", 16, ft.FontWeight.W_600),
            ui.muted(t.get("owner") or "")]
    if dd and st in ("veille", "etude"):
        days = (dd - today).days
        color = ui.DANGER if days <= 3 else (ui.WARNING if days <= 10 else ui.SUCCESS)
        head.append(ft.Container(ft.Row([ft.Icon(ft.Icons.TIMER_OUTLINED, color=color),
                                         ui.txt("Dépôt des offres : %s (%s)" % (dd.strftime("%d/%m/%Y"),
                                                                                 ui.days_label(days).lower()),
                                                13.5, ft.FontWeight.W_600, color)]),
                                 bgcolor=ui._tint(color), border_radius=10, padding=10))
    c.append(ui.card(head))

    est, bid = t.get("estimate_ttc"), t.get("bid_ttc")
    fin = [ui.kv("Estimation du maître d'ouvrage", ui.money(est)), ui.kv("Notre offre", ui.money(bid), strong=True)]
    if est and bid:
        gap = (bid - est) / est * 100
        fin.append(ui.kv("Écart / estimation", "%+.1f %%" % gap, ui.DANGER if gap > 0 else ui.SUCCESS))
    if t.get("winning_bid_ttc"):
        fin.append(ui.kv("Offre retenue (%s)" % (t.get("winner") or "attributaire"), ui.money(t["winning_bid_ttc"])))
        if bid:
            fin.append(ui.kv("Écart avec l'attributaire", "%+.1f %%" % ((bid - t["winning_bid_ttc"]) / t["winning_bid_ttc"] * 100)))
    fin.append(ui.kv("Caution provisoire", ui.money(t.get("caution_amount"))))
    fin.append(ui.kv("Ouverture des plis", tr.fmt_date(t.get("opening_date"))))
    if t.get("qualification"):
        fin.append(ui.kv("Qualification exigée", t["qualification"]))
    c.append(ui.section("Offre"))
    c.append(ui.card(fin, spacing=6))

    gs = store.q("SELECT * FROM guarantees WHERE tender_id=?", (tid,))
    c.append(ui.section("Caution provisoire", ui.text_btn("Ajouter", lambda e: guarantee_for_tender(app, t))))
    if not gs:
        c.append(ui.card([ui.muted("Aucune caution enregistrée pour cet appel d'offres.")]))
    for g in gs:
        info = erp.guarantee_info(g, today)
        c.append(ui.list_row("%s - %s" % (erp.label("guarantee_kind", g.get("kind")), g.get("ref") or ""),
                             store.tier_name(g.get("bank_id")), ui.money(g.get("amount"), 0),
                             ui.days_label(info["days_to_expiry"]) if info["active"] else "Libérée",
                             icon=ft.Icons.SHIELD_OUTLINED))

    if t.get("notes"):
        c.append(ui.section("Notes"))
        c.append(ui.card([ui.txt(t["notes"], 13.5, selectable=True)]))

    actions = [ui.tonal_btn("Modifier", lambda e: tender_form(app, tid), ft.Icons.EDIT, expand=True)]
    if t.get("project_id"):
        actions.append(ui.primary_btn("Ouvrir le marché", lambda e: app.go("/marche/%s" % t["project_id"]),
                                      ft.Icons.WORK, expand=True))
    elif st in ("soumis", "gagne", "etude", "veille"):
        actions.append(ui.primary_btn("Attribué : créer le marché", lambda e: convert(app, t), ft.Icons.EMOJI_EVENTS,
                                      expand=True))
    c.append(ft.Row(actions, spacing=10))
    if st == "soumis":
        c.append(ui.outline_btn("Marquer comme perdu", lambda e: mark_lost(app, t), ft.Icons.THUMB_DOWN_OUTLINED,
                                expand=True, color=ui.DANGER))
    return ft.View(route="/ao/%s" % tid, bgcolor=ui.BG, padding=0,
                   appbar=sub_appbar("AO n° %s" % (t.get("ref") or ""), t.get("owner")),
                   controls=[page_body(c)])


def convert(app, t):
    from .projects import project_form
    project_form(app, prefill={"ref": t.get("ref"), "title": t.get("title"), "owner": t.get("owner"),
                               "client_id": t.get("client_id"), "category": t.get("category"),
                               "location": t.get("location"), "amount_ttc": t.get("bid_ttc"),
                               "tender_id": t["id"]})


def mark_lost(app, t):
    def save(v):
        v["status"] = "perdu"
        app.store.update("tenders", t["id"], v)
        app.refresh()
    ui.form_dialog(app.page, "Offre non retenue", [
        {"key": "winner", "label": "Attributaire", "value": t.get("winner")},
        {"key": "winning_bid_ttc", "label": "Montant retenu TTC", "type": "number", "value": t.get("winning_bid_ttc")},
        {"key": "notes", "label": "Enseignements", "type": "multiline", "value": t.get("notes")}], save)


def guarantee_for_tender(app, t):
    from .finance import guarantee_form
    guarantee_form(app, defaults={"tender_id": t["id"], "kind": "provisoire", "amount": t.get("caution_amount")})
