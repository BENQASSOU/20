"""Plus: échéancier, tiers, assistant IA, rapports, paramètres, diagnostic."""

import asyncio
import re
from datetime import date

import flet as ft

from ... import __version__, billing, config, demo, erp, regulation, reports, selftest
from ...ai import MODELS, ask
from ...analysis import articles_of
from ...storage import Store, restore_backup
from .. import ui
from ..app import page_body, sub_appbar

MODULES = [
    ("echeancier", "Échéancier", "Toutes les dates clés", ft.Icons.EVENT_NOTE, ui.INFO),
    ("tiers", "Tiers", "Clients, fournisseurs, banques", ft.Icons.CONTACTS_OUTLINED, "#7A5AF8"),
    ("assistant", "Assistant IA", "Questions sur vos marchés", ft.Icons.AUTO_AWESOME, ui.ACCENT),
    ("rapports", "Rapports & exports", "PDF, CSV, partage", ft.Icons.PICTURE_AS_PDF_OUTLINED, ui.DANGER),
    ("parametres", "Paramètres", "Entreprise, IA, données", ft.Icons.SETTINGS_OUTLINED, ui.MUTED),
    ("abonnement", "Abonnement", "Formules et activation", ft.Icons.WORKSPACE_PREMIUM_OUTLINED, ui.SUCCESS),
    ("diagnostic", "Diagnostic", "Vérifier l'application", ft.Icons.HEALTH_AND_SAFETY_OUTLINED, ui.PRIMARY),
]


def build(app):
    tiles = []
    for key, title, sub, icon, color in MODULES:
        tiles.append(ft.Container(ui.card([
            ft.Container(ft.Icon(icon, color=color, size=24), bgcolor=ui._tint(color), border_radius=12, padding=10),
            ui.bold(title, 14.5), ui.muted(sub, 12)], on_click=lambda e, k=key: app.go("/module/%s" % k), spacing=6),
            col={"xs": 6, "md": 4}))
    c = [ft.ResponsiveRow(tiles, spacing=10, run_spacing=10),
         ui.muted("Safqa ERP %s · %s" % (__version__, regulation.DISCLAIMER), 11.5)]
    return "Plus", [], None, page_body(c)


def module_view(app, key, params):
    fn = {"echeancier": agenda_view, "tiers": tiers_view, "assistant": assistant_view, "rapports": reports_view,
          "parametres": settings_view, "abonnement": subscription_view, "diagnostic": diagnostic_view,
          "garanties": guarantees_module}.get(key)
    title, actions, fab, body = fn(app, params)
    return ft.View(route="/module/%s" % key, bgcolor=ui.BG, padding=0, appbar=sub_appbar(title, actions=actions),
                   floating_action_button=fab, controls=[body])


# --------------------------------------------------------------------------
# Échéancier
# --------------------------------------------------------------------------

def agenda_view(app, params):
    today = date.today()
    ev = erp.agenda(app.store, today, horizon=180, past=60)
    c = []
    groups = [("En retard", [e for e in ev if e["days"] < 0]), ("Cette semaine", [e for e in ev if 0 <= e["days"] <= 7]),
              ("Ce mois-ci", [e for e in ev if 7 < e["days"] <= 31]), ("Plus tard", [e for e in ev if e["days"] > 31])]
    if not ev:
        c.append(ui.empty("Aucune échéance.", ft.Icons.EVENT_AVAILABLE))
    for title, items in groups:
        if not items:
            continue
        c.append(ui.section("%s (%d)" % (title, len(items))))
        for e in items:
            color = ui.DANGER if e["days"] < 0 else (ui.WARNING if e["days"] <= 7 else ui.INFO)
            c.append(ui.list_row(e["title"], "%s · %s" % (e["kind"], e["detail"]) if e["detail"] else e["kind"],
                                 e["date"].strftime("%d/%m/%Y"), ui.days_label(e["days"]), icon=ft.Icons.EVENT,
                                 icon_color=color, on_click=(lambda ev_, r=e["route"]: app.go(r)) if e.get("route") else None))
    return "Échéancier", [], None, page_body(c)


def guarantees_module(app, params):
    from .finance import guarantee_form, guarantees_tab
    return ("Cautions", [], ft.FloatingActionButton(icon=ft.Icons.ADD, bgcolor=ui.ACCENT,
                                                     on_click=lambda e: guarantee_form(app)),
            page_body(guarantees_tab(app)))


# --------------------------------------------------------------------------
# Tiers
# --------------------------------------------------------------------------

def tiers_view(app, params):
    flt = app.state.get("tiers_filter", "tous")

    def set_flt(code):
        app.state["tiers_filter"] = code
        app.refresh()

    chips = [ft.Chip(label=ui.txt(lbl, 12.5), selected=flt == code, on_select=lambda e, c=code: set_flt(c))
             for code, lbl in [("tous", "Tous")] + erp.TIER_KINDS]
    c = [ft.Row(chips, spacing=6, scroll=ft.ScrollMode.AUTO)]
    rows = app.store.tiers(None if flt == "tous" else flt)
    if not rows:
        c.append(ui.empty("Aucun tiers enregistré.", ft.Icons.CONTACTS_OUTLINED))
    icons = {"client": ft.Icons.ACCOUNT_BALANCE, "fournisseur": ft.Icons.LOCAL_SHIPPING, "sous_traitant": ft.Icons.ENGINEERING,
             "banque": ft.Icons.SAVINGS, "bet": ft.Icons.SCIENCE, "autre": ft.Icons.PERSON}
    for t in rows:
        c.append(ui.list_row(t["name"], " · ".join(x for x in [erp.label("tier_kind", t["kind"]), t.get("city"),
                                                               t.get("phone")] if x),
                             icon=icons.get(t["kind"], ft.Icons.PERSON), on_click=lambda e, t=t: tier_form(app, t["id"])))
    return "Tiers", [], ft.FloatingActionButton(icon=ft.Icons.ADD, bgcolor=ui.ACCENT,
                                                on_click=lambda e: tier_form(app)), page_body(c)


def tier_form(app, tid=None):
    store = app.store
    t = store.get_row("tiers", tid) if tid else {"kind": app.state.get("tiers_filter") if app.state.get("tiers_filter") not in (None, "tous") else "fournisseur"}
    specs = [
        {"key": "kind", "label": "Type", "type": "select", "options": erp.TIER_KINDS, "value": t.get("kind"), "required": True},
        {"key": "name", "label": "Raison sociale / nom", "value": t.get("name"), "required": True},
        {"key": "ice", "label": "ICE", "value": t.get("ice")},
        {"key": "rc", "label": "RC", "value": t.get("rc")},
        {"key": "if_number", "label": "Identifiant fiscal (IF)", "value": t.get("if_number")},
        {"key": "contact", "label": "Interlocuteur", "value": t.get("contact")},
        {"key": "phone", "label": "Téléphone", "value": t.get("phone")},
        {"key": "email", "label": "E-mail", "value": t.get("email")},
        {"key": "address", "label": "Adresse", "value": t.get("address")},
        {"key": "city", "label": "Ville", "value": t.get("city")},
        {"key": "notes", "label": "Notes", "type": "multiline", "value": t.get("notes")},
    ]

    def save(v):
        if not tid:
            v["created_at"] = date.today().isoformat()
        store.save("tiers", v, tid)
        ui.snack(app.page, "Tiers enregistré")
        app.refresh()

    def delete():
        store.delete("tiers", tid)
        app.refresh()
    ui.form_dialog(app.page, "Modifier le tiers" if tid else "Nouveau tiers", specs, save,
                   on_delete=delete if tid else None)


# --------------------------------------------------------------------------
# Assistant IA
# --------------------------------------------------------------------------

CITE_RE = re.compile(r"\[(A\d+(?:_\d+)?|A0|P\d+)\]")


def assistant_view(app, params):
    store = app.store
    projects = store.projects()
    pid = int(params["pid"]) if params.get("pid") else app.state.get("chat_pid") or (projects[0]["id"] if projects else None)
    app.state["chat_pid"] = pid
    c = []
    if not projects:
        return "Assistant IA", [], None, page_body([ui.empty("Créez un marché et chargez ses pièces pour poser vos questions.")])

    def pick(e):
        app.state["chat_pid"] = int(e.control.value)
        app.refresh()

    c.append(ft.Dropdown(label="Marché", value=str(pid), expand=True, on_select=pick,
                         options=[ft.DropdownOption(key=str(p["id"]), text="%s - %s" % (p.get("ref") or "", (p.get("title") or "")[:45]))
                                  for p in projects]))
    st = app.sub
    c.append(ui.muted("%d question(s) restante(s) ce mois-ci" % st.remaining("ai_question")))
    labels = {}
    for d in store.documents(pid):
        for a in articles_of(d):
            labels.setdefault(a.key, a)
    hist = store.chat_history(pid)
    if not hist:
        sugg = ["Quelles sont mes obligations avant le démarrage des travaux ?",
                "Comment sont calculées les pénalités de retard ?",
                "Quels documents dois-je fournir pour la réception provisoire ?",
                "Le maître d'ouvrage paie en retard : que puis-je réclamer ?",
                "Quelle est ma marge prévisionnelle et quels postes dérapent ?"]
        c.append(ui.card([ui.bold("Posez vos questions sur ce marché", 14)] +
                         [ui.outline_btn(q, lambda e, q=q: send(app, pid, q), expand=True) for q in sugg], bgcolor=ui.TINT))
    for h in hist:
        content = h["content"]
        if h["role"] == "assistant":
            md = CITE_RE.sub(lambda m: "**[%s]**" % (("Art. %s" % labels[m.group(1)].number) if m.group(1) in labels else m.group(1)),
                             content)
            c.append(ft.Container(ft.Markdown(md, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB),
                                  bgcolor="#FFFFFF", border_radius=14, padding=12, border=ft.Border.all(1, ui.BORDER)))
        else:
            c.append(ft.Row([ft.Container(width=40),
                             ft.Container(ui.txt(content, 14, color="#FFFFFF"), bgcolor=ui.PRIMARY, border_radius=14,
                                          padding=12, expand=True)]))
    field = ft.TextField(hint_text="Votre question…", expand=True, border_radius=24, multiline=True, max_lines=4,
                         bgcolor="#FFFFFF", on_submit=lambda e: send(app, pid, field.value))
    bar = ft.Container(ft.Row([field, ft.IconButton(ft.Icons.SEND, icon_color="#FFFFFF", bgcolor=ui.PRIMARY,
                                                    on_click=lambda e: send(app, pid, field.value))]),
                       padding=10, bgcolor="#FFFFFF")
    body = ft.Column([ft.Container(ft.ListView(c, padding=14, spacing=10, expand=True, auto_scroll=True), expand=True), bar],
                     spacing=0, expand=True)
    return "Assistant IA", [ft.IconButton(ft.Icons.DELETE_SWEEP_OUTLINED, icon_color="#FFFFFF", tooltip="Effacer",
                                          on_click=lambda e: clear_chat(app, pid))], None, body


def clear_chat(app, pid):
    app.store.x("DELETE FROM chat WHERE project_id=?", (pid,))
    app.refresh()


def send(app, pid, question):
    from .workspace import project_context
    q = (question or "").strip()
    if not q:
        return
    ok, why = app.sub.can("ai_question")
    if not ok:
        ui.info(app.page, "Assistant IA", why)
        return
    client = app.ai_client()
    if not client.configured:
        ui.info(app.page, "Configuration requise", "Renseignez votre clé API ou le serveur Safqa dans Plus › Paramètres.")
        return
    store = app.store
    history = store.chat_history(pid)
    store.add_chat(pid, "user", q)
    app.refresh()
    s = erp.project_state(store, pid)
    docs = [("%s - %s" % (d.get("doc_type"), d.get("filename")), articles_of(d)) for d in s["documents"]]

    async def go():
        res = await app.run("Safqa analyse votre question…", ask, client, q, docs, project_context(s), history)
        if res:
            store.add_chat(pid, "assistant", res[0])
            store.bump_usage("ai_question")
        app.refresh()
    app.task(go)


# --------------------------------------------------------------------------
# Rapports
# --------------------------------------------------------------------------

def reports_view(app, params):
    store = app.store
    co = app.company()
    stamp = date.today().strftime("%Y%m%d")

    def gen(label, fn, name, mime, *args):
        async def go():
            ok, why = app.sub.can("export")
            if not ok:
                ui.info(app.page, "Export", why)
                return
            data = await app.run("Génération : %s…" % label, fn, *args)
            if data:
                app.export(data, name, mime)
        app.task(go)

    c = [ui.section("Rapports de l'entreprise")]
    for label, fn, name, mime, args, icon in [
        ("Tableau de bord du portefeuille", reports.portfolio_pdf, "Safqa_portefeuille_%s.pdf" % stamp, reports.MIME_PDF, (store, co), ft.Icons.DASHBOARD),
        ("Situation de trésorerie", reports.treasury_pdf, "Safqa_tresorerie_%s.pdf" % stamp, reports.MIME_PDF, (store, co), ft.Icons.ACCOUNT_BALANCE),
        ("État des cautions", reports.guarantees_pdf, "Safqa_cautions_%s.pdf" % stamp, reports.MIME_PDF, (store, co), ft.Icons.SHIELD),
        ("Journal des dépenses (Excel / CSV)", reports.expenses_csv, "Safqa_depenses_%s.csv" % stamp, reports.MIME_CSV, (store,), ft.Icons.TABLE_CHART),
    ]:
        c.append(ui.list_row(label, name, icon=icon, on_click=lambda e, a=(label, fn, name, mime) + args: gen(*a)))
    c.append(ui.section("Rapports par marché"))
    for p in store.projects():
        def contract(e, pid=p["id"], ref=p.get("ref")):
            s = erp.project_state(store, pid)
            gen("rapport de marché", reports.contract_report, "Safqa_marche_%s_%s.pdf" % (reports.safe_name(ref), stamp),
                reports.MIME_PDF, s, co)

        def analysis(e, pid=p["id"], ref=p.get("ref")):
            s = erp.project_state(store, pid)
            gen("analyse contractuelle", reports.analysis_pdf, "Safqa_analyse_%s.pdf" % reports.safe_name(ref),
                reports.MIME_PDF, s, co)
        c.append(ui.card([ui.bold("%s - %s" % (p.get("ref") or "", p.get("title") or ""), 14, max_lines=2),
                          ft.Row([ui.tonal_btn("Rapport", contract, ft.Icons.PICTURE_AS_PDF, expand=True),
                                  ui.tonal_btn("Analyse CPS", analysis, ft.Icons.FACT_CHECK, expand=True)], spacing=8)]))
    return "Rapports & exports", [], None, page_body(c)


# --------------------------------------------------------------------------
# Paramètres
# --------------------------------------------------------------------------

def settings_view(app, params):
    store = app.store
    co = app.company()
    c = [ui.section("Entreprise")]
    c.append(ui.list_row(co.get("name") or "Renseigner l'entreprise",
                         " · ".join(x for x in ["ICE " + co["ice"] if co.get("ice") else "", co.get("city")] if x) or
                         "Raison sociale, ICE, RC, IF, CNSS (apparaissent sur les rapports)",
                         icon=ft.Icons.BUSINESS, on_click=lambda e: company_form(app)))
    c.append(ui.section("Intelligence artificielle"))
    mode = store.get("ai_mode", "proxy" if config.DEFAULT_PROXY_URL else "direct")
    model = store.get("ai_model", MODELS[0][0])
    c.append(ui.list_row("Mode : %s" % ("Serveur Safqa" if mode == "proxy" else "Clé API personnelle"),
                         dict(MODELS).get(model, model), icon=ft.Icons.AUTO_AWESOME, icon_color=ui.ACCENT,
                         on_click=lambda e: ai_form(app)))
    c.append(ui.section("Données"))
    c.append(ui.list_row("Sauvegarder mes données", "Fichier .db à conserver ou envoyer", icon=ft.Icons.BACKUP,
                         on_click=lambda e: backup(app)))
    c.append(ui.list_row("Restaurer une sauvegarde", "Remplace toutes les données actuelles", icon=ft.Icons.RESTORE,
                         icon_color=ui.WARNING, on_click=lambda e: app.task(restore, app)))
    c.append(ui.list_row("Charger les données de démonstration", "Entreprise fictive avec 3 marchés",
                         icon=ft.Icons.AUTO_AWESOME_MOSAIC, icon_color=ui.INFO, on_click=lambda e: load_demo(app)))
    c.append(ui.list_row("Effacer toutes les données", "Irréversible : faites d'abord une sauvegarde",
                         icon=ft.Icons.DELETE_FOREVER, icon_color=ui.DANGER,
                         on_click=lambda e: ui.confirm(app.page, "Tout effacer",
                                                       "Marchés, AO, dépenses, cautions et tiers seront supprimés.",
                                                       lambda: (demo.clear_all(store), app.go("/")), "Tout effacer")))
    c.append(ui.section("À propos"))
    c.append(ui.card([ui.txt("Safqa ERP %s" % __version__, 14, ft.FontWeight.W_600),
                      ui.muted("Textes de référence : " + " ; ".join(regulation.TEXTS[k] for k in
                                                                     ("DECRET_MP", "CCAG_T", "DELAIS_PAIEMENT"))),
                      ui.muted(regulation.DISCLAIMER),
                      ui.muted("Vos données restent sur votre téléphone. Avec l'IA, le texte des pièces est envoyé "
                               "au service d'IA uniquement au moment de l'analyse.")]))
    return "Paramètres", [], None, page_body(c)


def company_form(app):
    co = app.company()
    specs = [{"key": k, "label": lbl, "value": co.get(k), "required": k == "name"} for k, lbl in [
        ("name", "Raison sociale"), ("ice", "ICE"), ("rc", "Registre de commerce"), ("if_number", "Identifiant fiscal"),
        ("cnss", "N° CNSS"), ("patente", "Taxe professionnelle (patente)"), ("address", "Adresse"), ("city", "Ville"),
        ("phone", "Téléphone"), ("email", "E-mail"), ("manager", "Signataire / gérant")]]

    def save(v):
        app.store.set_json("company", v)
        ui.snack(app.page, "Entreprise enregistrée")
        app.refresh()
    ui.form_dialog(app.page, "Mon entreprise", specs, save)


def ai_form(app):
    s = app.store
    specs = [
        {"key": "ai_mode", "label": "Mode", "type": "select", "value": s.get("ai_mode", "proxy" if config.DEFAULT_PROXY_URL else "direct"),
         "options": [("proxy", "Serveur Safqa (inclus dans l'abonnement)"), ("direct", "Clé API Anthropic personnelle")]},
        {"key": "proxy_url", "label": "Adresse du serveur Safqa", "value": s.get("proxy_url", config.DEFAULT_PROXY_URL)},
        {"key": "api_key", "label": "Clé API Anthropic", "type": "password", "value": s.get("api_key", "")},
        {"key": "ai_model", "label": "Modèle", "type": "select", "value": s.get("ai_model", MODELS[0][0]), "options": MODELS},
    ]

    def save(v):
        for k, val in v.items():
            s.set(k, val or "")
        ui.snack(app.page, "Paramètres IA enregistrés")
        app.refresh()
    ui.form_dialog(app.page, "Intelligence artificielle", specs, save)


def backup(app):
    data = app.store.backup_bytes()
    app.export(data, "Safqa_sauvegarde_%s.db" % date.today().strftime("%Y%m%d"), "application/octet-stream",
               "Sauvegarde")


async def restore(app):
    name, data = await app.pick_file(["db"])
    if not data:
        return

    def do():
        app.store.close()
        try:
            restore_backup(app.db_path, data)
        finally:
            app.store = Store(app.db_path)
            app.sub = billing.Subscription(app.store)
    try:
        await asyncio.to_thread(do)
    except ValueError as exc:
        ui.info(app.page, "Restauration impossible", str(exc))
        return
    ui.snack(app.page, "Sauvegarde restaurée")
    app.go("/")


def load_demo(app):
    async def go():
        await app.run("Chargement des données de démonstration…", demo.load_demo, app.store)
        app.go("/")
    if not app.store.is_empty():
        ui.confirm(app.page, "Données de démonstration",
                   "Les données de démonstration s'ajouteront à vos données existantes.", lambda: app.task(go),
                   "Ajouter", danger=False)
    else:
        app.task(go)


# --------------------------------------------------------------------------
# Abonnement
# --------------------------------------------------------------------------

def subscription_view(app, params):
    store = app.store
    st = app.sub.status()
    lim = st["limits"]
    c = [ui.card([ui.txt("Formule : %s" % st["label"], 17, ft.FontWeight.W_700), ui.txt(st["message"]),
                  ui.kv("Analyses IA ce mois", "%d / %d" % (store.usage("ai_analysis"), lim["ai_analyses"])),
                  ui.kv("Questions IA ce mois", "%d / %d" % (store.usage("ai_question"), lim["ai_questions"])),
                  ui.kv("Marchés actifs", "%d / %s" % (len(store.projects()),
                                                       "illimité" if lim["max_projects"] >= 1000 else lim["max_projects"]))],
                 accent=ui.SUCCESS if st["active"] else ui.WARNING)]
    for code, plan in billing.PLANS.items():
        c.append(ui.card([ft.Row([ui.bold(plan["name"], 17, expand=True),
                                  ui.txt("%d DH / mois" % plan["price_dh"], 16, ft.FontWeight.W_700, ui.PRIMARY)]),
                          ui.muted(plan["pitch"]),
                          ft.Column([ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=ui.SUCCESS), ui.txt(f, 13.5, expand=True)])
                                     for f in plan["features"]], spacing=4),
                          ui.tonal_btn("Souscrire", lambda e, p=plan: subscribe(app, p), ft.Icons.SHOPPING_BAG_OUTLINED,
                                       expand=True)], accent=ui.ACCENT if code == "PRO" else None))
    key = ft.TextField(label="Clé d'activation", value=store.get("license_key", "") or "",
                       hint_text="SAFQA-PRO-20271231-SOCIETE-XXXXXXXXXX", border_radius=10)

    def activate(e):
        ok, msg = app.sub.activate(key.value or "")
        ui.snack(app.page, msg, error=not ok)
        if ok:
            app.refresh()
    c.append(ui.card([ui.bold("Activer une clé", 15), key, ui.primary_btn("Activer", activate, ft.Icons.KEY)]))
    return "Abonnement", [], None, page_body(c)


def subscribe(app, plan):
    from urllib.parse import quote
    num = re.sub(r"\D", "", config.SALES_WHATSAPP)
    url = "https://wa.me/%s?text=%s" % (num, quote("Bonjour, je souhaite souscrire à Safqa ERP %s." % plan["name"]))
    ui.info(app.page, "Souscrire - %s (%d DH/mois)" % (plan["name"], plan["price_dh"]),
            "%s\n\nWhatsApp : %s\nE-mail : %s" % (config.PAYMENT_INFO, config.SALES_WHATSAPP, config.SALES_EMAIL),
            [ft.TextButton(content="Ouvrir WhatsApp", url=url)])


# --------------------------------------------------------------------------
# Diagnostic
# --------------------------------------------------------------------------

def diagnostic_view(app, params):
    out = ft.Column([ui.muted("Vérifie la base de données, l'analyse des documents, les calculs et la génération "
                              "des PDF sur cet appareil, sans toucher à vos données.")], spacing=6)

    async def go(e=None):
        res = await app.run("Diagnostic en cours…", selftest.run, None)
        if not res:
            return
        ok, lines = res
        out.controls.append(ui.card([ui.txt("Résultat : %s" % ("tout fonctionne" if ok else "problème détecté"), 15,
                                            ft.FontWeight.W_700, ui.SUCCESS if ok else ui.DANGER)] +
                                    [ui.txt(ln, 11.5, selectable=True) for ln in lines]))
        out.update()
    c = [out, ui.primary_btn("Lancer le diagnostic", lambda e: app.task(go), ft.Icons.PLAY_ARROW)]
    return "Diagnostic", [], None, page_body(c)
