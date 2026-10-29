"""Contract workspace (12 tabs) and document analysis view."""

import os
from datetime import date

import flet as ft

from ... import analysis, erp, regulation as reg, reports, rules
from ... import tracking as tr
from ...analysis import KIND_LABELS, articles_of, unified_findings
from ...textract import DOC_TYPES
from .. import ui
from ..app import page_body, sub_appbar

TABS = [("synthese", "Synthèse"), ("pieces", "Pièces & IA"), ("obligations", "Obligations"), ("planning", "Planning"),
        ("os", "Ordres de service"), ("attachements", "Attachements"), ("decomptes", "Décomptes"),
        ("couts", "Budget & coûts"), ("journal", "Journal"), ("cautions", "Cautions"), ("receptions", "Réceptions"),
        ("risques", "Risques")]
TAB_KEYS = [k for k, _ in TABS]


def view(app, pid, tab=None):
    s = erp.project_state(app.store, pid)
    if not s:
        return ft.View(route="/marche/%s" % pid, appbar=sub_appbar("Marché introuvable"), controls=[ui.empty("Supprimé")])
    key = "ws_tab_%s" % pid
    if tab in TAB_KEYS:
        app.state[key] = tab
    tab = app.state.get(key, "synthese")
    p = s["project"]

    def change(e):
        app.state[key] = TAB_KEYS[e.control.selected_index]
        app.refresh()

    tabs = ft.Tabs(length=len(TABS), selected_index=TAB_KEYS.index(tab), on_change=change,
                   content=ft.TabBar(tabs=[ft.Tab(label=lbl) for _, lbl in TABS], scrollable=True,
                                     tab_alignment=ft.TabAlignment.START))
    ctx = Ctx(app, pid, s)
    body, fab = globals()["tab_" + tab](ctx)
    actions = [ft.IconButton(ft.Icons.PICTURE_AS_PDF, icon_color="#FFFFFF", tooltip="Rapport PDF",
                             on_click=lambda e: ctx.export_report()),
               ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, icon_color="#FFFFFF", items=[
                   ft.PopupMenuItem(content="Modifier le marché", icon=ft.Icons.EDIT, on_click=lambda e: ctx.edit()),
                   ft.PopupMenuItem(content="Assistant IA", icon=ft.Icons.AUTO_AWESOME,
                                    on_click=lambda e: app.go("/module/assistant?pid=%s" % pid)),
                   ft.PopupMenuItem(content="Archiver", icon=ft.Icons.ARCHIVE_OUTLINED, on_click=lambda e: ctx.archive()),
                   ft.PopupMenuItem(content="Supprimer", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda e: ctx.delete()),
               ])]
    return ft.View(route="/marche/%s" % pid, bgcolor=ui.BG, padding=0, floating_action_button=fab,
                   appbar=sub_appbar(p.get("title") or "Marché", "N° %s · %s" % (p.get("ref") or "-", p.get("owner") or "-"),
                                     actions),
                   controls=[ft.Column([ft.Container(tabs, bgcolor="#FFFFFF"),
                                        ft.Container(page_body(body), expand=True)], spacing=0, expand=True)])


class Ctx:
    def __init__(self, app, pid, s):
        self.app, self.pid, self.s = app, pid, s
        self.store, self.page = app.store, app.page

    def refresh(self):
        self.app.refresh()

    def fab(self, label, on_click, icon=ft.Icons.ADD):
        return ft.FloatingActionButton(icon=icon, content=label, bgcolor=ui.ACCENT, on_click=on_click)

    def export_report(self):
        async def go():
            ok, why = self.app.sub.can("export")
            if not ok:
                ui.info(self.page, "Export", why)
                return
            data = await self.app.run("Génération du rapport…", reports.contract_report, self.s, self.app.company())
            if data:
                self.app.export(data, "Safqa_marche_%s_%s.pdf" % (reports.safe_name(self.s["project"].get("ref")),
                                                                   date.today().strftime("%Y%m%d")), reports.MIME_PDF)
        self.app.task(go)

    def edit(self):
        from .projects import project_form
        project_form(self.app, self.pid)

    def archive(self):
        self.store.save_project({"archived": 1}, self.pid)
        ui.snack(self.page, "Marché archivé")
        self.app.go("/")

    def delete(self):
        def yes():
            for d in self.store.documents(self.pid):
                try:
                    os.remove(d.get("path") or "")
                except OSError:
                    pass
            self.store.delete_project(self.pid)
            self.app.go("/")
        ui.confirm(self.page, "Supprimer le marché", "Toutes les données de ce marché seront effacées.", yes, "Supprimer")


# --------------------------------------------------------------------------
# Synthèse
# --------------------------------------------------------------------------

def tab_synthese(x):
    s = x.s
    p, f, sched = s["project_full"], s["finance"], s["schedule"]
    pen = tr.penalty_estimate(p, sched)
    rs = tr.reception_status(p, s["receptions"])
    c = [ui.pills_row([ui.status_pill(p.get("status") or "en_cours", erp.label("project_status", p.get("status") or "en_cours"))] +
                      [ui.pill(v, ui.MUTED, "#F2F4F7") for v in (p.get("category"), p.get("location"), p.get("manager")) if v])]
    c.append(ui.kpi_grid([
        ui.kpi("Montant TTC", ui.short_money(f["contract_ttc"]), ft.Icons.REQUEST_QUOTE_OUTLINED, ui.PRIMARY),
        ui.kpi("Facturé HT", "%d %%" % (f["invoiced_ratio"] * 100), ft.Icons.RECEIPT_LONG_OUTLINED, ui.SUCCESS,
               ui.short_money(f["invoiced_ht"])),
        ui.kpi("Encaissé TTC", ui.short_money(f["paid_ttc"]), ft.Icons.PAYMENTS_OUTLINED, ui.INFO,
               "Reste dû %s" % ui.short_money(f["unpaid_ttc"])),
        ui.kpi("Marge prévisionnelle", "%.1f %%" % f["forecast_margin_pct"], ft.Icons.TRENDING_UP,
               ui.SUCCESS if f["forecast_margin"] >= 0 else ui.DANGER, ui.short_money(f["forecast_margin"])),
    ]))
    late = sched["late_days"]
    d = [ui.bold("Délais", 15)]
    if sched["start"]:
        d += [ft.Row([ui.ring(sched["progress"], "Délai consommé", ui.DANGER if late else ui.PRIMARY),
                      ui.ring(f["progress"], "Avancement physique", ui.SUCCESS),
                      ui.ring(f["invoiced_ratio"], "Facturation", ui.ACCENT)],
                     alignment=ft.MainAxisAlignment.SPACE_AROUND),
              ui.kv("Début (OS de commencement)", tr.fmt_date(sched["start"])),
              ui.kv("Fin contractuelle", tr.fmt_date(sched["end"]), strong=True)]
        if sched["suspended_days"]:
            d.append(ui.kv("Jours d'arrêt", "%d j" % sched["suspended_days"]))
        if late:
            d.append(ui.kv("Retard", "%d jours" % late, ui.DANGER, True))
            d.append(ui.kv("Pénalités estimées", ui.money(pen["amount"]), ui.DANGER, True))
        elif sched.get("finished"):
            d.append(ui.kv("Achèvement", tr.fmt_date(sched["finished"])))
        else:
            d.append(ui.kv("Jours restants", "%d j" % max(0, sched["remaining"] or 0)))
    else:
        d.append(ui.muted("Enregistrez l'ordre de service de commencement pour calculer le planning."))
    if rs["warranty_end"]:
        d.append(ui.kv("Fin du délai de garantie", tr.fmt_date(rs["warranty_end"])))
    c.append(ui.card(d))
    c.append(ui.card([ui.bold("Finances", 15),
                      ui.kv("Montant du marché HT", ui.money(f["contract_ht"])),
                      ui.kv("Travaux facturés HT", ui.money(f["invoiced_ht"])),
                      ui.kv("Reste à réaliser HT", ui.money(f["backlog_ht"])),
                      ui.kv("Dépenses HT", ui.money(f["costs_ht"])),
                      ui.kv("Budget HT", ui.money(f["budget_ht"])),
                      ui.kv("Marge brute à date", "%s (%.1f %%)" % (ui.money(f["margin_ht"], 0), f["margin_pct"]), strong=True),
                      ui.kv("Retenue de garantie", ui.money(f["retenue"]))], spacing=6))
    flags = s["flags"]
    c.append(ui.section("Alertes (%d)" % len(flags), ui.text_btn("Tout voir", lambda e: x.app.go("/marche/%s?tab=risques" % x.pid))))
    for fl in flags[:3]:
        c.append(flag_card(fl))
    if not flags:
        c.append(ui.card([ui.muted("Aucune alerte.")]))
    c.append(ui.section("Clauses clés", ui.text_btn("Corriger", lambda e: edit_terms(x))))
    rows = []
    for key, lbl in rules.TERM_LABELS.items():
        t = s["terms"].get(key)
        if not t or key in ("execution_delay_months", "penalty_other_cap_pct"):
            continue
        src = [ui.cite_pill(t.get("article_label"), t.get("page"))] if t.get("article_key") else \
            [ui.pill("Défaut : " + (t.get("article_label") or "")[:34], ui.MUTED, "#F2F4F7", 10.5)] if t.get("source") == "défaut" else \
            [ui.pill(t.get("source") or "", ui.MUTED, "#F2F4F7")]
        rows.append(ft.Column([ui.kv(lbl, rules.format_term(key, t.get("value")),
                                     ui.MUTED if t.get("source") == "défaut" else None, t.get("source") != "défaut"),
                               ui.pills_row(src)], spacing=3))
    c.append(ui.card(rows or [ui.muted("Chargez le CPS dans l'onglet Pièces & IA.")], spacing=10))
    c.append(ui.muted(reg.DISCLAIMER, 11.5))
    return c, None


def edit_terms(x):
    terms = x.s["terms"]
    keys = ["penalty_rate_per_day", "penalty_cap_pct", "retenue_rate_pct", "retenue_cap_pct", "caution_definitive_pct",
            "warranty_months", "payment_delay_days", "tva_pct"]
    specs = []
    for k in keys:
        v = (terms.get(k) or {}).get("value")
        if k == "penalty_rate_per_day":
            specs.append({"key": k, "label": "Pénalité : 1/N par jour (N)", "type": "number",
                          "value": round(1 / v) if v else None})
        else:
            specs.append({"key": k, "label": rules.TERM_LABELS[k], "type": "number", "value": v})

    def save(vals):
        proj = x.store.project(x.pid)
        manual = dict(proj.get("terms") or {})
        for k, v in vals.items():
            if v is None:
                continue
            if k == "penalty_rate_per_day":
                if v <= 0:
                    return "N doit être positif"
                v = 1.0 / v
            cur = (terms.get(k) or {}).get("value")
            if cur is not None and abs(float(cur) - v) < 1e-12:
                continue
            manual[k] = {"value": v, "source": "saisie", "article_key": None, "article_label": "Saisie manuelle",
                         "page": None, "text": ""}
        x.store.save_project({"terms": manual}, x.pid)
        x.refresh()
    ui.form_dialog(x.page, "Clauses du contrat", specs, save)


def flag_card(f):
    fg = ui.SEVERITY.get(f["severity"], (ui.MUTED,))[0]
    items = [ui.pills_row([ui.sev_pill(f["severity"]), ui.pill(f.get("category") or "", ui.MUTED, "#F2F4F7")]),
             ui.txt(f["title"], 14.5, ft.FontWeight.W_600)]
    if f.get("detail"):
        items.append(ui.txt(f["detail"], 13))
    if f.get("action"):
        items.append(ft.Row([ft.Icon(ft.Icons.LIGHTBULB_OUTLINE, size=16, color=ui.PRIMARY),
                             ui.txt(f["action"], 13, color=ui.PRIMARY_DARK, expand=True)], vertical_alignment=ft.CrossAxisAlignment.START))
    if f.get("article_label"):
        items.append(ui.pills_row([ui.cite_pill(f["article_label"], f.get("page"))]))
    if f.get("text"):
        items.append(ui.muted("« %s »" % _trim(f["text"], 260), 12, italic=True))
    return ui.card(items, accent=fg, spacing=6)


def _trim(t, n):
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


# --------------------------------------------------------------------------
# Pièces & IA
# --------------------------------------------------------------------------

def tab_pieces(x):
    s = x.s
    c = [ui.card([ui.bold("Pièces du marché", 15),
                  ui.muted("CPS, marché, CCAG-T, BPDE, RC, avenants, PV… (PDF, Word, texte). Safqa extrait obligations, "
                           "délais et pénalités avec l'article source ; l'IA approfondit l'analyse."),
                  ui.primary_btn("Ajouter un document", lambda e: x.app.task(add_document, x), ft.Icons.UPLOAD_FILE, expand=True)])]
    for d in s["documents"]:
        a = d.get("analysis") or {}
        counts = {}
        for f in unified_findings(d):
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        issues = len(a.get("issues", [])) + len(a.get("ai_risks", []))
        pills = [ui.pill("%d obligations" % (counts.get("obligation", 0) + counts.get("prohibition", 0))),
                 ui.pill("%d délais" % counts.get("deadline", 0)), ui.pill("%d pénalités" % counts.get("penalty", 0))]
        if issues:
            pills.append(ui.pill("%d points d'attention" % issues, *ui.SEVERITY["élevé"][:2]))
        if a.get("ai"):
            pills.append(ui.pill("Analyse IA", ui.SUCCESS, ui._tint(ui.SUCCESS)))
        c.append(ui.card([
            ft.Row([ft.Icon(ft.Icons.DESCRIPTION, color=ui.PRIMARY), ui.bold(d.get("filename") or "", 14, expand=True, max_lines=2)]),
            ui.muted("%s · %s page(s)%s" % (DOC_TYPES.get(d.get("doc_type"), d.get("doc_type")), d.get("pages"),
                                           " · PDF scanné" if d.get("scanned") else "")),
            ui.pills_row(pills),
            ft.Row([ui.tonal_btn("Voir l'analyse", lambda e, d=d: x.app.go("/marche/%s/doc/%s" % (x.pid, d["id"])),
                                 ft.Icons.VISIBILITY, expand=True),
                    ui.primary_btn("Relancer l'IA" if a.get("ai") else "Analyse IA", lambda e, d=d: run_ai(x, d),
                                   ft.Icons.AUTO_AWESOME, expand=True)], spacing=8)]))
    c.append(ui.section("Checklist des pièces"))
    present = {r["code"] for r in s["checklist"] if r.get("present")}
    for phase in reg.PHASES:
        items = [i for i in reg.DOCUMENT_CHECKLIST if i[2] == phase]
        done = sum(1 for i in items if i[0] in present)
        rows = [ft.Row([ui.bold(phase, 14.5, expand=True), ui.muted("%d / %d" % (done, len(items)))]),
                ui.progress(done / len(items), ui.SUCCESS)]
        for code, label, _ph, mandatory in items:
            rows.append(ft.Checkbox(label=label + ("" if mandatory else " (facultatif)"), value=code in present,
                                    on_change=lambda e, cd=code: (x.store.set_check(x.pid, cd, e.control.value,
                                                                                    date.today().isoformat() if e.control.value else None))))
        c.append(ui.card(rows, spacing=2))
    return c, None


async def add_document(x):
    name, data = await x.app.pick_file(["pdf", "docx", "txt"])
    if not data:
        return
    safe = "".join(ch for ch in (name or "document") if ch.isalnum() or ch in "._- ") or "document"
    path = os.path.join(x.app.docs_dir, "%s_%s" % (x.pid, safe))
    i = 1
    while os.path.exists(path):
        base, ext = os.path.splitext(safe)
        path = os.path.join(x.app.docs_dir, "%s_%s_%d%s" % (x.pid, base, i, ext))
        i += 1
    with open(path, "wb") as fh:
        fh.write(data)

    def chosen(v):
        x.app.task(ingest, x, path, name, v.get("doc_type") or None)
    ui.form_dialog(x.page, "Type de document", [
        {"key": "doc_type", "label": "Nature de la pièce", "type": "select", "value": "",
         "options": [("", "Détection automatique")] + list(DOC_TYPES.items())}], chosen, "Analyser")


async def ingest(x, path, name, doc_type):
    res = await x.app.run("Extraction et analyse du document…", analysis.ingest, path, name, doc_type)
    if not res:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    res.update(project_id=x.pid, uploaded_at=date.today().isoformat())
    doc_id = x.store.insert("documents", res)
    autofill(x, res)
    x.store.touch(x.pid)
    msg = "%d éléments extraits hors-ligne" % len(res["analysis"]["findings"])
    if res["scanned"]:
        msg = "PDF scanné : lancez l'analyse IA pour l'exploiter"
    ui.snack(x.page, msg)
    x.app.go("/marche/%s/doc/%s" % (x.pid, doc_id))


def autofill(x, doc):
    p = x.store.project(x.pid)
    terms = (doc.get("analysis") or {}).get("terms", {})
    upd = {}
    amt = terms.get("contract_amount_ttc", {})
    if not p.get("amount_ttc") and amt.get("source") in ("CPS", "IA"):
        upd["amount_ttc"] = amt["value"]
    dd = terms.get("execution_delay_days", {})
    if not p.get("delay_days") and dd.get("source") in ("CPS", "IA"):
        upd["delay_days"] = int(dd["value"])
        dm = terms.get("execution_delay_months", {})
        if dm.get("value"):
            upd["delay_months"] = int(dm["value"])
    ct = ((doc.get("analysis") or {}).get("ai") or {}).get("contract") or {}
    if not p.get("owner") and ct.get("maitre_ouvrage"):
        upd["owner"] = ct["maitre_ouvrage"]
    if not p.get("title") and ct.get("objet"):
        upd["title"] = ct["objet"]
    if upd:
        x.store.save_project(upd, x.pid)


def run_ai(x, d):
    ok, why = x.app.sub.can("ai_analysis")
    if not ok:
        ui.info(x.page, "Analyse IA", why)
        return
    client = x.app.ai_client()
    if not client.configured:
        ui.info(x.page, "Configuration requise", "Renseignez votre clé API ou le serveur Safqa dans Plus › Paramètres.")
        return
    doc = x.store.get_row("documents", d["id"])

    async def go():
        new = await x.app.run("Analyse IA en cours (1 à 3 minutes)…", analysis.run_ai, client, doc)
        if not new:
            return
        x.store.update("documents", d["id"], {"analysis": new, "ai_status": "ok"})
        x.store.bump_usage("ai_analysis")
        doc["analysis"] = new
        autofill(x, doc)
        ai_res = new.get("ai") or {}
        n = sum(len(ai_res.get(k, [])) for k in ("obligations", "deadlines", "penalties", "risks"))
        v = sum(1 for k in ("obligations", "deadlines", "penalties", "risks") for i in ai_res.get(k, []) if i.get("verified"))
        ui.snack(x.page, "Analyse IA : %d éléments, %d citations vérifiées" % (n, v))
        x.app.go("/marche/%s/doc/%s" % (x.pid, d["id"]))
    x.app.task(go)


# --------------------------------------------------------------------------
# Obligations
# --------------------------------------------------------------------------

FILTERS = ["Tout", "Titulaire", "Maître d'ouvrage", "Délais", "Pénalités", "Documents", "Finances"]


def tab_obligations(x):
    key = "obl_filter_%s" % x.pid
    flt = x.app.state.get(key, "Tout")
    items = []
    for d in x.s["documents"]:
        for f in unified_findings(d):
            if f["kind"] in ("obligation", "prohibition", "deadline", "penalty", "document", "financial"):
                items.append(f)

    def keep(f):
        if flt == "Tout":
            return True
        if flt in ("Titulaire", "Maître d'ouvrage"):
            return f.get("party") == flt and f["kind"] in ("obligation", "prohibition", "document")
        return {"Délais": "deadline", "Pénalités": "penalty", "Documents": "document", "Finances": "financial"}[flt] == f["kind"]

    def set_flt(v):
        x.app.state[key] = v
        x.refresh()

    c = [ft.Row([ft.Chip(label=ui.txt(v, 12.5), selected=flt == v, on_select=lambda e, v=v: set_flt(v)) for v in FILTERS],
                spacing=6, scroll=ft.ScrollMode.AUTO)]
    shown = [f for f in items if keep(f)]
    c.append(ui.muted("%d élément(s) · chaque élément renvoie à l'article source" % len(shown)))
    if not x.s["documents"]:
        c.append(ui.empty("Ajoutez le CPS dans l'onglet Pièces & IA.", ft.Icons.DESCRIPTION))
    for f in shown[:150]:
        c.append(finding_card(f))
    return c, None


def finding_card(f):
    kind = f["kind"]
    accent = {"penalty": ui.DANGER, "deadline": ui.INFO, "document": ui.ACCENT, "financial": ui.SUCCESS}.get(kind, ui.PRIMARY)
    pills = [ui.pill(KIND_LABELS.get(kind, kind), accent, ui._tint(accent))]
    if f.get("party") and f["party"] != "Non précisé":
        pills.append(ui.pill(f["party"], ui.TEXT, "#F2F4F7"))
    pills.append(ui.pill(f.get("source") or "", ui.MUTED, "#F2F4F7"))
    items = [ui.pills_row(pills), ui.txt(f.get("summary") or "", 14)]
    if f.get("deadline"):
        items.append(ui.txt("Échéance : %s" % f["deadline"], 13, color="#175CD3"))
    if f.get("text") and f.get("text") != f.get("summary"):
        items.append(ui.muted("« %s »" % _trim(f["text"], 300), 12, italic=True))
    cite = []
    if f.get("article_label"):
        cite.append(ui.cite_pill(f["article_label"], f.get("page")))
    if f.get("source") == "IA":
        cite.append(ui.pill("Citation vérifiée" if f.get("verified") else "À vérifier",
                            *(ui.SEVERITY["info"][:2] if f.get("verified") else ui.SEVERITY["moyen"][:2])))
    if cite:
        items.append(ui.pills_row(cite))
    return ui.card(items, accent=accent, spacing=6)


# --------------------------------------------------------------------------
# Planning (Gantt)
# --------------------------------------------------------------------------

def tab_planning(x):
    tasks = x.s["tasks"]
    c = []
    if not tasks:
        c.append(ui.empty("Aucune tâche planifiée.", ft.Icons.VIEW_TIMELINE_OUTLINED,
                          ui.primary_btn("Ajouter une tâche", lambda e: task_form(x), ft.Icons.ADD)))
        return c, x.fab("Tâche", lambda e: task_form(x))
    dates = [tr.parse_date(t.get("start")) for t in tasks] + [tr.parse_date(t.get("end")) for t in tasks]
    dates = [d for d in dates if d]
    today = date.today()
    lo, hi = min(dates + [today]), max(dates + [today])
    span = max(1, (hi - lo).days)
    done = sum((t.get("progress") or 0) for t in tasks) / len(tasks)
    late = [t for t in tasks if tr.parse_date(t.get("end")) and tr.parse_date(t["end"]) < today and (t.get("progress") or 0) < 100]
    c.append(ui.card([ft.Row([ui.ring(done / 100, "Avancement moyen", ui.SUCCESS),
                              ft.Column([ui.kv("Tâches", str(len(tasks))), ui.kv("En retard", str(len(late)),
                                                                                  ui.DANGER if late else None, True),
                                         ui.kv("Période", "%s – %s" % (lo.strftime("%d/%m/%y"), hi.strftime("%d/%m/%y")))],
                                        expand=True, spacing=4)], spacing=16)]))
    today_off = (today - lo).days
    rows = []
    for t in tasks:
        s, e = tr.parse_date(t.get("start")) or lo, tr.parse_date(t.get("end")) or hi
        off, dur = max(0, (s - lo).days), max(1, (e - s).days)
        rest = max(0, span - off - dur)
        prog = max(0.0, min(100.0, t.get("progress") or 0))
        is_late = e < today and prog < 100
        color = ui.DANGER if is_late else (ui.SUCCESS if prog >= 100 else ui.PRIMARY)
        done_w = int(round(prog))
        bar = ft.Row(_segments([(done_w, color), (100 - done_w, ui._tint(color, 0.3))], 12), spacing=0)
        lane = ft.Row(_segments([(off, None), (dur, bar), (rest, None)], 12), spacing=0)
        rows.append(ft.Container(ft.Column([
            ft.Row([ui.txt(t.get("name") or "", 13.5, ft.FontWeight.W_600, expand=True, max_lines=1),
                    ui.muted("%d %%" % prog, 12)]),
            lane,
            ui.muted("%s – %s%s" % (s.strftime("%d/%m"), e.strftime("%d/%m/%Y"), " · en retard" if is_late else ""), 11,
                     color=ui.DANGER if is_late else ui.MUTED)], spacing=4),
            padding=ft.Padding(0, 6, 0, 6), on_click=lambda ev, t=t: task_form(x, t["id"])))
    marker = ft.Row([c for c in (ft.Container(expand=today_off) if today_off > 0 else None,
                                 ft.Container(width=2, height=10, bgcolor=ui.ACCENT),
                                 ft.Container(expand=span - today_off) if span - today_off > 0 else None) if c],
                    spacing=0)
    c.append(ui.card([ft.Row([ui.bold("Diagramme de Gantt", 15, expand=True),
                              ft.Row([ft.Container(width=10, height=10, bgcolor=ui.ACCENT), ui.muted("aujourd'hui", 11)],
                                     spacing=4)]), marker] + rows, spacing=0))
    return c, x.fab("Tâche", lambda e: task_form(x))


def _segments(parts, height):
    """Row children with integer expand weights; zero-width parts are dropped."""
    out = []
    for weight, fill in parts:
        weight = int(weight)
        if weight <= 0:
            continue
        if isinstance(fill, ft.Control):
            out.append(ft.Container(fill, expand=weight))
        else:
            out.append(ft.Container(expand=weight, height=height, bgcolor=fill, border_radius=6 if fill else None))
    return out


def task_form(x, tid=None):
    t = x.store.get_row("tasks", tid) if tid else {"start": date.today().isoformat(), "progress": 0}
    specs = [{"key": "name", "label": "Tâche", "value": t.get("name"), "required": True},
             {"key": "start", "label": "Début", "type": "date", "value": t.get("start"), "required": True},
             {"key": "end", "label": "Fin", "type": "date", "value": t.get("end"), "required": True},
             {"key": "progress", "label": "Avancement (%)", "type": "number", "value": t.get("progress")},
             {"key": "responsible", "label": "Responsable", "value": t.get("responsible")},
             {"key": "notes", "label": "Notes", "type": "multiline", "value": t.get("notes")}]

    def save(v):
        if v["end"] < v["start"]:
            return "La fin doit être après le début"
        v["progress"] = max(0, min(100, v.get("progress") or 0))
        v["project_id"] = x.pid
        if not tid:
            v["sort"] = len(x.s["tasks"])
        x.store.save("tasks", v, tid)
        x.refresh()

    def delete():
        x.store.delete("tasks", tid)
        x.refresh()
    ui.form_dialog(x.page, "Tâche", specs, save, on_delete=delete if tid else None)


# --------------------------------------------------------------------------
# Ordres de service
# --------------------------------------------------------------------------

def tab_os(x):
    sched = x.s["schedule"]
    p = x.s["project"]
    c = [ui.card([ui.bold("Planning contractuel", 15),
                  ui.kv("Délai d'exécution", "%s jours" % (p.get("delay_days") or "-")),
                  ui.kv("Début", tr.fmt_date(sched["start"])),
                  ui.kv("Arrêts cumulés", "%d j" % sched["suspended_days"]),
                  ui.kv("Prolongations", "%d j" % sched["extension_days"]),
                  ui.kv("Fin contractuelle", tr.fmt_date(sched["end"]), strong=True)] +
                 ([ui.pill("Chantier à l'arrêt", *ui.SEVERITY["moyen"][:2])] if sched["stopped"] else []), spacing=6)]
    colors = {"commencement": ui.SUCCESS, "arret": ui.DANGER, "reprise": ui.INFO, "prolongation": ui.ACCENT}
    for o in reversed(x.s["orders"]):
        sub = "Notifié le %s" % tr.fmt_date(o.get("date"))
        if o.get("days"):
            sub += " · %s jours" % o["days"]
        if o.get("note"):
            sub += " · " + o["note"]
        c.append(ui.list_row("OS n° %s - %s" % (o.get("number") or "-", tr.OS_LABELS.get(o.get("kind"), "")), sub,
                             icon=ft.Icons.ASSIGNMENT, icon_color=colors.get(o.get("kind"), ui.MUTED),
                             on_click=lambda e, o=o: os_form(x, o)))
    if not x.s["orders"]:
        c.append(ui.empty("Aucun ordre de service.", ft.Icons.ASSIGNMENT_OUTLINED))
    return c, x.fab("OS", lambda e: os_form(x))


def os_form(x, o=None):
    o = o or {}
    specs = [{"key": "kind", "label": "Type", "type": "select", "options": tr.OS_KINDS, "value": o.get("kind", "commencement")},
             {"key": "number", "label": "Numéro", "value": o.get("number", str(len(x.s["orders"]) + 1))},
             {"key": "date", "label": "Date de notification", "type": "date", "value": o.get("date"), "required": True},
             {"key": "effective_date", "label": "Date d'effet si différente", "type": "date", "value": o.get("effective_date")},
             {"key": "days", "label": "Jours (prolongation)", "type": "int", "value": o.get("days")},
             {"key": "note", "label": "Objet / observations", "type": "multiline", "value": o.get("note")}]

    def save(v):
        v["project_id"] = x.pid
        x.store.save("orders", v, o.get("id"))
        if v["kind"] == "commencement":
            x.store.set_check(x.pid, "OS_COMMENCEMENT", True, v["date"])
        x.refresh()

    def delete():
        x.store.delete("orders", o["id"])
        x.refresh()
    ui.form_dialog(x.page, "Ordre de service", specs, save, on_delete=delete if o.get("id") else None)


# --------------------------------------------------------------------------
# Attachements / BPDE
# --------------------------------------------------------------------------

def tab_attachements(x):
    q = tr.quantities_summary(x.s["items"], x.s["terms"])
    c = [ui.card([ui.bold("Bordereau des prix - détail estimatif", 15),
                  ui.kv("Montant initial HT", ui.money(q["initial_ht"])),
                  ui.kv("Exécuté HT (cumul)", ui.money(q["executed_ht"]), strong=True),
                  ui.progress(q["progress"], ui.SUCCESS, 9),
                  ui.kv("Variation dans la masse", "%+.1f %%" % q["mass_variation_pct"],
                        ui.DANGER if q["mass_variation_pct"] > (q["mass_increase_limit_pct"] or 10) else None, True)], spacing=6),
         ft.Row([ui.tonal_btn("Prix", lambda e: item_form(x), ft.Icons.ADD, expand=True),
                 ui.tonal_btn("Importer CSV", lambda e: x.app.task(import_csv, x), ft.Icons.UPLOAD_FILE, expand=True)], spacing=8)]
    ai_items = [it for d in x.s["documents"] for it in (((d.get("analysis") or {}).get("ai") or {}).get("bpde_items") or [])]
    if ai_items and not x.s["items"]:
        c.append(ui.primary_btn("Importer %d prix extraits par l'IA" % len(ai_items), lambda e: import_items(x, [
            {"number": it.get("number"), "designation": it.get("designation"), "unit": it.get("unit"),
             "qty_contract": it.get("quantity") or 0, "unit_price_ht": it.get("unit_price_ht") or 0, "qty_executed": 0}
            for it in ai_items]), ft.Icons.AUTO_AWESOME, expand=True))
    if not x.s["items"]:
        c.append(ui.muted("Format CSV : n° ; désignation ; unité ; quantité ; prix unitaire HT."))
    for r in q["rows"]:
        it = r["item"]
        color = ui.DANGER if r["overrun"] else ui.PRIMARY
        c.append(ui.card([
            ft.Row([ui.bold("%s  %s" % (it.get("number") or "", it.get("designation") or ""), 14, expand=True, max_lines=2),
                    ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_size=18, on_click=lambda e, it=it: item_form(x, it))]),
            ui.muted("%s %s × %s = %s HT" % (_q(it.get("qty_contract")), it.get("unit") or "", ui.money(it.get("unit_price_ht")),
                                            ui.money((it.get("qty_contract") or 0) * (it.get("unit_price_ht") or 0), 0))),
            ui.progress(r["progress"], color, 8),
            ft.Row([ui.txt("Exécuté %s %s (%d %%)" % (_q(it.get("qty_executed")), it.get("unit") or "", r["progress"] * 100),
                           13, expand=True),
                    ui.txt(("+%d %%" % r["variance_pct"]) if r["overrun"] else ui.money(r["amount_ht"], 0), 13,
                           ft.FontWeight.W_600, ui.DANGER if r["overrun"] else None)]),
            ui.outline_btn("Nouvel attachement", lambda e, it=it: measure_form(x, it), ft.Icons.STRAIGHTEN, expand=True)],
            accent=ui.DANGER if r["overrun"] else None, spacing=6))
    ms = x.s["measurements"]
    if ms:
        items = {i["id"]: i for i in x.s["items"]}
        c.append(ui.section("Historique des attachements"))
        for m in ms[:30]:
            it = items.get(m.get("item_id"), {})
            c.append(ui.list_row("Prix %s : +%s %s" % (it.get("number") or "?", _q(m.get("qty")), it.get("unit") or ""),
                                 "%s · %s" % (tr.fmt_date(m.get("date")), m.get("ref") or ""), icon=ft.Icons.STRAIGHTEN,
                                 on_click=lambda e, m=m: delete_measure(x, m)))
    return c, None


def _q(v):
    if v is None:
        return ""
    v = float(v)
    return str(int(v)) if v.is_integer() else ("%.3f" % v).rstrip("0").rstrip(".").replace(".", ",")


def item_form(x, it=None):
    it = it or {}
    specs = [{"key": "number", "label": "N° de prix", "value": it.get("number")},
             {"key": "designation", "label": "Désignation", "value": it.get("designation"), "required": True},
             {"key": "unit", "label": "Unité (m³, ml, m², U, Ft…)", "value": it.get("unit")},
             {"key": "qty_contract", "label": "Quantité du BPDE", "type": "number", "value": it.get("qty_contract"), "required": True},
             {"key": "unit_price_ht", "label": "Prix unitaire HT (DH)", "type": "number", "value": it.get("unit_price_ht"), "required": True}]

    def save(v):
        v["project_id"] = x.pid
        if not it.get("id"):
            v["qty_executed"] = 0
        x.store.save("items", v, it.get("id"))
        x.refresh()

    def delete():
        x.store.x("DELETE FROM measurements WHERE item_id=?", (it["id"],))
        x.store.delete("items", it["id"])
        x.refresh()
    ui.form_dialog(x.page, "Prix du bordereau", specs, save, on_delete=delete if it.get("id") else None)


def measure_form(x, it):
    n = len({m.get("ref") for m in x.s["measurements"]}) + 1
    specs = [{"key": "qty", "label": "Quantité de cet attachement (%s)" % (it.get("unit") or ""), "type": "number", "required": True},
             {"key": "date", "label": "Date", "type": "date", "value": date.today().isoformat()},
             {"key": "ref", "label": "Référence", "value": "Attachement n° %d" % n},
             {"key": "notes", "label": "Observations", "type": "multiline"}]

    def save(v):
        v.update(project_id=x.pid, item_id=it["id"])
        x.store.insert("measurements", v)
        x.store.recompute_item(it["id"])
        x.store.set_check(x.pid, "ATTACHEMENTS", True)
        x.refresh()
    ui.form_dialog(x.page, "Prix %s - attachement" % (it.get("number") or ""), specs, save)


def delete_measure(x, m):
    def yes():
        x.store.delete("measurements", m["id"])
        x.store.recompute_item(m["item_id"])
        x.refresh()
    ui.confirm(x.page, "Supprimer l'attachement", "Retirer %s ?" % _q(m.get("qty")), yes, "Supprimer")


async def import_csv(x):
    name, data = await x.app.pick_file(["csv", "txt"])
    if not data:
        return
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", "replace")
    items = tr.parse_bpde_csv(text)
    if not items:
        ui.info(x.page, "Import CSV", "Aucune ligne valide. Format : n° ; désignation ; unité ; quantité ; prix unitaire HT")
        return
    import_items(x, items)


def import_items(x, items):
    for it in items:
        it["project_id"] = x.pid
        x.store.insert("items", it)
    x.store.set_check(x.pid, "BPDE_SIGNE", True)
    ui.snack(x.page, "%d prix importés" % len(items))
    x.refresh()


# --------------------------------------------------------------------------
# Décomptes
# --------------------------------------------------------------------------

def tab_decomptes(x):
    c = []
    if not x.s["items"]:
        c.append(ui.card([ui.muted("Les décomptes sont calculés à partir des quantités cumulées des attachements.")]))
    for d in reversed(x.s["decomptes"]):
        st = tr.payment_status(d, x.s["terms"])
        color = ui.SUCCESS if d.get("paid_date") else (ui.DANGER if st["late"] else ui.WARNING)
        status = ("Payé le %s" % tr.fmt_date(d["paid_date"])) if d.get("paid_date") else (
            ("%d j / %d j" % (st["days"], st["limit"])) if st["days"] is not None else "Constatation à saisir")
        c.append(ui.card([
            ft.Row([ui.bold("Décompte %s n° %s" % ("définitif" if d.get("final") else "provisoire", d.get("number")), 15, expand=True),
                    ui.pill(status, color, ui._tint(color))]),
            ui.kv("Date", tr.fmt_date(d.get("date"))),
            ui.kv("Total TTC cumulé", ui.money(d.get("total_ttc"))),
            ui.kv("Retenue de garantie", "- " + ui.money(d.get("retenue"))),
            ui.kv("Pénalités", "- " + ui.money(d.get("penalties")), ui.DANGER if d.get("penalties") else None),
            ui.kv("Décomptes précédents", "- " + ui.money(d.get("previous_ttc"))),
            ui.kv("Net à payer", ui.money(d.get("net_ttc")), ui.PRIMARY, True),
            ft.Row([ui.tonal_btn("Paiement", lambda e, d=d: _payment(x, d), ft.Icons.PAYMENTS, expand=True),
                    ui.tonal_btn("PDF", lambda e, d=d: export_decompte(x, d), ft.Icons.PICTURE_AS_PDF, expand=True),
                    ft.IconButton(ft.Icons.TABLE_CHART_OUTLINED, tooltip="CSV", on_click=lambda e, d=d: export_decompte(x, d, csv=True)),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=ui.DANGER, tooltip="Supprimer",
                                  on_click=lambda e, d=d: ui.confirm(x.page, "Supprimer", "Supprimer ce décompte ?",
                                                                     lambda: (x.store.delete("decomptes", d["id"]), x.refresh())))],
                   spacing=6)], accent=color, spacing=5))
    if not x.s["decomptes"]:
        c.append(ui.empty("Aucun décompte.", ft.Icons.RECEIPT_LONG_OUTLINED))
    return c, x.fab("Décompte n° %d" % (len(x.s["decomptes"]) + 1), lambda e: new_decompte(x))


def _payment(x, d):
    from .finance import payment_form
    payment_form(x.app, d)


def export_decompte(x, d, csv=False):
    async def go():
        if csv:
            data = await x.app.run("Génération…", reports.decompte_csv, x.s["project"], d)
            name, mime = "Decompte_%s_n%s.csv" % (reports.safe_name(x.s["project"].get("ref")), d.get("number")), reports.MIME_CSV
        else:
            data = await x.app.run("Génération…", reports.decompte_pdf, x.s, d, x.app.company())
            name, mime = "Decompte_%s_n%s.pdf" % (reports.safe_name(x.s["project"].get("ref")), d.get("number")), reports.MIME_PDF
        if data:
            x.app.export(data, name, mime)
    x.app.task(go)


def new_decompte(x):
    s = x.s
    pen = tr.penalty_estimate(s["project_full"], s["schedule"])
    preview = ui.txt("", 13)
    specs = [{"key": "date", "label": "Date du décompte", "type": "date", "value": date.today().isoformat(), "required": True},
             {"key": "revision", "label": "Révision des prix HT (cumul)", "type": "number", "value": 0},
             {"key": "penalties", "label": "Pénalités à déduire", "type": "number", "value": round(pen["amount"], 2)},
             {"key": "advance", "label": "Remboursement de l'avance (cumul)", "type": "number", "value": 0},
             {"key": "final", "label": "Décompte définitif", "type": "bool", "value": False}]

    def compute(v):
        return tr.compute_decompte(s["project_full"], s["items"], s["decomptes"], revision_ht=v.get("revision") or 0,
                                   penalties=v.get("penalties") or 0, advance_recovery=v.get("advance") or 0,
                                   final=v.get("final"))

    def save(v):
        res = compute(v)
        res.update(project_id=x.pid, date=v["date"], status="émis")
        x.store.insert("decomptes", res)
        x.store.set_check(x.pid, "DECOMPTES", True)
        if v.get("final"):
            x.store.set_check(x.pid, "DECOMPTE_DEF", True, v["date"])
        ui.snack(x.page, "Décompte n° %d : net à payer %s" % (res["number"], ui.money(res["net_ttc"])))
        x.refresh()

    form = ui.form_dialog(x.page, "Décompte n° %d" % (len(s["decomptes"]) + 1), specs, save, extra=preview)

    def update(e=None):
        v, err = form.values()
        if err:
            return
        r = compute(v)
        preview.value = ("Travaux HT %s · TVA %s\nTotal TTC %s · Retenue %s\nPrécédents %s\nNet à payer : %s" % (
            ui.money(r["works_ht"], 0), ui.money(r["tva"], 0), ui.money(r["total_ttc"], 0), ui.money(r["retenue"], 0),
            ui.money(r["previous_ttc"], 0), ui.money(r["net_ttc"])))
        try:
            preview.update()
        except Exception:  # noqa: BLE001 - not yet mounted
            pass
    update()
    for k in ("revision", "penalties", "advance"):
        form.controls[k].on_change = update
    form.controls["final"].on_change = update


# --------------------------------------------------------------------------
# Budget & coûts
# --------------------------------------------------------------------------

def tab_couts(x):
    from .finance import expense_form, expenses_tab
    f = x.s["finance"]
    c = [ui.kpi_grid([
        ui.kpi("Budget HT", ui.short_money(f["budget_ht"]), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, ui.PRIMARY),
        ui.kpi("Dépenses HT", ui.short_money(f["costs_ht"]), ft.Icons.SHOPPING_CART_OUTLINED, ui.WARNING,
               "%d %% du budget" % ((f["costs_ht"] / f["budget_ht"] * 100) if f["budget_ht"] else 0)),
        ui.kpi("Coût à terminaison", ui.short_money(f["cost_at_completion"]), ft.Icons.FLAG_OUTLINED, ui.INFO),
        ui.kpi("Marge prévisionnelle", "%.1f %%" % f["forecast_margin_pct"], ft.Icons.TRENDING_UP,
               ui.SUCCESS if f["forecast_margin"] >= 0 else ui.DANGER, ui.short_money(f["forecast_margin"])),
    ])]
    c.append(ui.section("Budget par poste", ui.text_btn("Modifier", lambda e: budget_form(x))))
    if f["by_category"]:
        c.append(ui.card([ui.budget_bar(cat["label"], cat["actual"], cat["budget"]) for cat in f["by_category"]], spacing=12))
    else:
        c.append(ui.card([ui.muted("Définissez le budget par poste pour suivre la marge."),
                          ui.tonal_btn("Définir le budget", lambda e: budget_form(x), ft.Icons.EDIT)]))
    c.append(ui.section("Dépenses du marché"))
    c += expenses_tab(x.app, x.pid)
    return c, x.fab("Dépense", lambda e: expense_form(x.app, project_id=x.pid))


def budget_form(x):
    current = {}
    for line in x.s["budget"]:
        current[line.get("category")] = current.get(line.get("category"), 0) + (line.get("amount_ht") or 0)
    specs = [{"key": code, "label": "%s (HT)" % lbl, "type": "number", "value": current.get(code)} for code, lbl in erp.EXPENSE_CATEGORIES]

    def save(v):
        x.store.x("DELETE FROM budget_lines WHERE project_id=?", (x.pid,))
        for code, amount in v.items():
            if amount:
                x.store.insert("budget_lines", {"project_id": x.pid, "category": code, "amount_ht": amount})
        x.refresh()
    ui.form_dialog(x.page, "Budget du marché", specs, save)


# --------------------------------------------------------------------------
# Journal de chantier
# --------------------------------------------------------------------------

def tab_journal(x):
    c = [ui.muted("Le journal de chantier est votre meilleure preuve en cas de litige (intempéries, arrêts, ordres "
                  "verbaux, visites).", 12.5)]
    if not x.s["journal"]:
        c.append(ui.empty("Aucune entrée.", ft.Icons.MENU_BOOK_OUTLINED))
    for j in x.s["journal"]:
        items = [ft.Row([ui.bold(tr.fmt_date(j.get("date")), 14.5, expand=True),
                         ui.pill(j.get("weather") or "-", ui.INFO, ui._tint(ui.INFO)),
                         ui.pill("%s ouvriers" % (j.get("workforce") or 0), ui.MUTED, "#F2F4F7")]),
                 ui.txt(j.get("work_done") or "", 13.5)]
        if j.get("equipment"):
            items.append(ui.muted("Matériel : " + j["equipment"]))
        if j.get("incidents"):
            items.append(ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=16, color=ui.DANGER),
                                 ui.txt(j["incidents"], 13, color=ui.DANGER, expand=True)],
                                vertical_alignment=ft.CrossAxisAlignment.START))
        if j.get("visitors"):
            items.append(ui.muted("Visites : " + j["visitors"]))
        c.append(ui.card(items, accent=ui.DANGER if j.get("incidents") else None, spacing=5,
                         on_click=lambda e, j=j: journal_form(x, j)))
    return c, x.fab("Entrée", lambda e: journal_form(x))


def journal_form(x, j=None):
    j = j or {"date": date.today().isoformat()}
    specs = [{"key": "date", "label": "Date", "type": "date", "value": j.get("date"), "required": True},
             {"key": "weather", "label": "Météo", "type": "select", "value": j.get("weather"),
              "options": [(w, w) for w in erp.WEATHER]},
             {"key": "workforce", "label": "Effectif présent", "type": "int", "value": j.get("workforce")},
             {"key": "equipment", "label": "Matériel sur site", "value": j.get("equipment")},
             {"key": "work_done", "label": "Travaux réalisés", "type": "multiline", "value": j.get("work_done"), "required": True},
             {"key": "incidents", "label": "Incidents / arrêts / réserves", "type": "multiline", "value": j.get("incidents")},
             {"key": "visitors", "label": "Visites (MO, BET, laboratoire)", "value": j.get("visitors")}]

    def save(v):
        v["project_id"] = x.pid
        if not j.get("id"):
            v["created_at"] = date.today().isoformat()
        x.store.save("journal", v, j.get("id"))
        x.store.set_check(x.pid, "JOURNAL_CHANTIER", True)
        x.refresh()

    def delete():
        x.store.delete("journal", j["id"])
        x.refresh()
    ui.form_dialog(x.page, "Journal de chantier", specs, save, on_delete=delete if j.get("id") else None)


# --------------------------------------------------------------------------
# Cautions / Réceptions / Risques
# --------------------------------------------------------------------------

def tab_cautions(x):
    from .finance import guarantee_form, guarantees_tab
    return guarantees_tab(x.app, x.pid), x.fab("Caution", lambda e: guarantee_form(x.app, defaults={"project_id": x.pid}))


def tab_receptions(x):
    s = x.s
    rs = tr.reception_status(s["project_full"], s["receptions"])
    c = []
    for kind, label in (("provisoire", "Réception provisoire"), ("definitive", "Réception définitive")):
        r = next((i for i in s["receptions"] if i.get("kind") == kind), None)
        items = [ft.Row([ui.bold(label, 15, expand=True),
                         ui.pill("Prononcée" if r else "Non prononcée", *((ui.SUCCESS, ui._tint(ui.SUCCESS)) if r else (ui.MUTED, "#F2F4F7")))])]
        if r:
            items.append(ui.kv("Date du PV", tr.fmt_date(r.get("date"))))
            if kind == "provisoire":
                items.append(ui.kv("Réserves", "Oui" if r.get("with_reserves") else "Non"))
                if r.get("with_reserves"):
                    items.append(ui.kv("Levée des réserves", tr.fmt_date(r.get("reserves_lifted_date")),
                                       None if r.get("reserves_lifted_date") else ui.DANGER))
                items.append(ui.kv("Délai de garantie", "%d mois" % rs["warranty_months"]))
                items.append(ui.kv("Réception définitive attendue", tr.fmt_date(rs["warranty_end"]), strong=True))
        elif kind == "definitive" and rs["warranty_end"]:
            items.append(ui.muted("Exigible à partir du %s." % tr.fmt_date(rs["warranty_end"])))
        items.append(ui.tonal_btn("Modifier" if r else "Enregistrer le PV", lambda e, k=kind, r=r: reception_form(x, k, r),
                                  ft.Icons.EDIT_NOTE, expand=True))
        c.append(ui.card(items, accent=ui.SUCCESS if r else None, spacing=6))
    c.append(ui.muted("À la réception définitive : demandez la restitution de la retenue de garantie et la mainlevée "
                      "du cautionnement définitif."))
    return c, None


def reception_form(x, kind, r=None):
    r = r or {}
    specs = [{"key": "date", "label": "Date du PV", "type": "date", "value": r.get("date"), "required": True}]
    if kind == "provisoire":
        specs += [{"key": "works_end_date", "label": "Date d'achèvement constatée", "type": "date", "value": r.get("works_end_date")},
                  {"key": "with_reserves", "label": "Prononcée avec réserves", "type": "bool", "value": r.get("with_reserves")},
                  {"key": "reserves_lifted_date", "label": "Levée des réserves", "type": "date", "value": r.get("reserves_lifted_date")}]
    specs.append({"key": "note", "label": "Observations", "type": "multiline", "value": r.get("note")})

    def save(v):
        v.update(project_id=x.pid, kind=kind)
        if "with_reserves" in v:
            v["with_reserves"] = 1 if v["with_reserves"] else 0
        x.store.save("receptions", v, r.get("id"))
        x.store.set_check(x.pid, "PV_RECEP_PROV" if kind == "provisoire" else "PV_RECEP_DEF", True, v["date"])
        status = "receptionne" if kind == "provisoire" else "clos"
        x.store.save_project({"status": status}, x.pid)
        x.refresh()
    ui.form_dialog(x.page, "Réception " + kind, specs, save)


def tab_risques(x):
    from ...risk import exposure
    flags = x.s["flags"]
    counts = {k: sum(1 for f in flags if f["severity"] == k) for k in ("critique", "élevé", "moyen", "info")}
    exp = exposure(flags)
    c = [ui.card([ui.bold("Tableau des risques", 15),
                  ui.pills_row([ui.pill("%d %s" % (n, ui.SEVERITY[k][2].lower()), *ui.SEVERITY[k][:2]) for k, n in counts.items() if n]),
                  ui.kv("Pénalités encourues", ui.money(exp["penalties"]), ui.DANGER if exp["penalties"] else None, True),
                  ui.kv("Créances en retard", ui.money(exp["late_receivables"]), ui.WARNING if exp["late_receivables"] else None)],
                 spacing=8)]
    if not flags:
        c.append(ui.empty("Aucun risque détecté.", ft.Icons.VERIFIED_OUTLINED))
    for f in flags:
        c.append(flag_card(f))
    return c, None


# --------------------------------------------------------------------------
# Document view
# --------------------------------------------------------------------------

DOC_TABS = [("elements", "Éléments"), ("problemes", "Points d'attention"), ("resume", "Résumé IA"), ("articles", "Articles")]


def document_view(app, pid, doc_id):
    store = app.store
    doc = store.get_row("documents", doc_id)
    route = "/marche/%s/doc/%s" % (pid, doc_id)
    if not doc:
        return ft.View(route=route, appbar=sub_appbar("Document supprimé"), controls=[ui.empty("Supprimé")])
    key = "doc_tab_%s" % doc_id
    tab = app.state.get(key, "elements")

    def change(e):
        app.state[key] = DOC_TABS[e.control.selected_index][0]
        app.refresh()

    tabs = ft.Tabs(length=len(DOC_TABS), selected_index=[k for k, _ in DOC_TABS].index(tab), on_change=change,
                   content=ft.TabBar(tabs=[ft.Tab(label=lbl) for _, lbl in DOC_TABS], scrollable=True,
                                     tab_alignment=ft.TabAlignment.START))
    a = doc.get("analysis") or {}
    c = []
    if tab == "elements":
        if doc.get("scanned") and not a.get("ai"):
            c.append(ui.card([ui.bold("PDF scanné", 14),
                              ui.txt("Le texte est une image : lancez l'analyse IA depuis l'onglet Pièces & IA.", 13)],
                             accent=ui.WARNING))
        fnd = unified_findings(doc)
        kinds = ["Tout"] + sorted({KIND_LABELS.get(f["kind"], f["kind"]) for f in fnd})
        sel = app.state.get("doc_kind_%s" % doc_id, "Tout")

        def set_kind(v):
            app.state["doc_kind_%s" % doc_id] = v
            app.refresh()
        c.append(ft.Row([ft.Chip(label=ui.txt(k, 12.5), selected=sel == k, on_select=lambda e, k=k: set_kind(k)) for k in kinds],
                        spacing=6, scroll=ft.ScrollMode.AUTO))
        items = [f for f in fnd if sel == "Tout" or KIND_LABELS.get(f["kind"], f["kind"]) == sel]
        c.append(ui.muted("%d élément(s)" % len(items)))
        c += [finding_card(f) for f in items[:200]]
    elif tab == "problemes":
        issues = list(a.get("issues", []))
        for r in a.get("ai_risks", []):
            issues.append({"severity": r.get("severity"), "title": r.get("title"), "detail": r.get("detail"),
                           "action": r.get("action"), "article_label": r.get("article_label"), "page": r.get("page"),
                           "text": r.get("quote"), "category": "IA"})
        from ...risk import SEVERITY_ORDER
        for i in sorted(issues, key=lambda i: SEVERITY_ORDER.get(i.get("severity"), 9)):
            i.setdefault("category", "Règles")
            c.append(flag_card(i))
        if not issues:
            c.append(ui.empty("Aucun point d'attention.", ft.Icons.VERIFIED_OUTLINED))
    elif tab == "resume":
        ai_res = a.get("ai")
        if not ai_res:
            c.append(ui.empty("Aucune analyse IA pour ce document.", ft.Icons.AUTO_AWESOME))
        else:
            ct = ai_res.get("contract") or {}
            c.append(ui.card([ui.kv(lbl, ct[k]) for k, lbl in (("objet", "Objet"), ("maitre_ouvrage", "Maître d'ouvrage"),
                                                               ("reference", "Référence"), ("lieu", "Lieu")) if ct.get(k)] +
                             [ft.Markdown(ai_res.get("summary") or "", selectable=True)]))
    else:
        arts = articles_of(doc)
        c.append(ui.muted("%d article(s) détecté(s)" % len(arts)))
        for art in arts:
            c.append(ft.ExpansionTile(title=ui.txt(art.label(), 13.5, ft.FontWeight.W_600, max_lines=2),
                                      subtitle=ui.muted("page %s" % art.page, 11.5), bgcolor="#FFFFFF",
                                      collapsed_bgcolor="#FFFFFF",
                                      controls=[ft.Container(ui.txt(art.text, 13, selectable=True), padding=12)]))

    def delete():
        try:
            os.remove(doc.get("path") or "")
        except OSError:
            pass
        store.delete("documents", doc_id)
        app.go("/marche/%s?tab=pieces" % pid)

    actions = [ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color="#FFFFFF", tooltip="Supprimer",
                             on_click=lambda e: ui.confirm(app.page, "Supprimer le document",
                                                           "Le document et son analyse seront supprimés.", delete))]
    return ft.View(route=route, bgcolor=ui.BG, padding=0,
                   appbar=sub_appbar(doc.get("filename") or "Document",
                                     "%s · %s page(s)" % (DOC_TYPES.get(doc.get("doc_type"), ""), doc.get("pages")), actions),
                   controls=[ft.Column([ft.Container(tabs, bgcolor="#FFFFFF"), ft.Container(page_body(c), expand=True)],
                                       spacing=0, expand=True)])


# --------------------------------------------------------------------------
# Context for the AI assistant
# --------------------------------------------------------------------------

def project_context(s):
    p, f, sched = s["project_full"], s["finance"], s["schedule"]
    lines = [
        "Marché : %s (n° %s), maître d'ouvrage : %s" % (p.get("title"), p.get("ref"), p.get("owner")),
        "Montant TTC : %s" % ui.money(p.get("amount_ttc")),
        "Date du jour : %s" % date.today().strftime("%d/%m/%Y"),
        "Début des travaux : %s ; fin contractuelle : %s ; jours d'arrêt : %s ; retard : %s jours" % (
            tr.fmt_date(sched["start"]), tr.fmt_date(sched["end"]), sched["suspended_days"], sched["late_days"]),
        "Facturé HT : %s (%d %%) ; encaissé TTC : %s ; impayé : %s" % (
            ui.money(f["invoiced_ht"]), f["invoiced_ratio"] * 100, ui.money(f["paid_ttc"]), ui.money(f["unpaid_ttc"])),
        "Budget HT : %s ; dépenses HT : %s ; marge prévisionnelle : %s (%.1f %%)" % (
            ui.money(f["budget_ht"]), ui.money(f["costs_ht"]), ui.money(f["forecast_margin"]), f["forecast_margin_pct"]),
    ]
    for cat in f["by_category"]:
        lines.append("Poste %s : budget %s, réalisé %s" % (cat["label"], ui.money(cat["budget"]), ui.money(cat["actual"])))
    for o in s["orders"]:
        lines.append("OS n° %s (%s) du %s %s" % (o.get("number"), tr.OS_LABELS.get(o.get("kind")),
                                                 tr.fmt_date(o.get("date")), o.get("note") or ""))
    for r in s["receptions"]:
        lines.append("Réception %s le %s%s" % (r.get("kind"), tr.fmt_date(r.get("date")),
                                               " avec réserves" if r.get("with_reserves") else ""))
    for g in s["guarantees"]:
        lines.append("Caution %s %s : %s, échéance %s" % (g.get("kind"), g.get("ref") or "", ui.money(g.get("amount")),
                                                          tr.fmt_date(g.get("expiry_date"))))
    for fl in s["flags"][:15]:
        lines.append("Alerte (%s) : %s - %s" % (fl["severity"], fl["title"], fl["detail"]))
    return "\n".join(lines)

