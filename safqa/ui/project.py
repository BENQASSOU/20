"""Project screens: creation form, project workspace (tabs) and document
analysis view."""

import os
from datetime import date

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import escape_markup

from .. import analysis, regulation as reg, report, rules, tracking as tr
from ..analysis import KIND_LABELS, unified_findings
from ..platform_android import save_to_downloads, share
from ..textnum import fmt_dh, parse_decimal
from ..textract import DOC_TYPES
from . import widgets as W
from .screens import BaseScreen
from .widgets import C

e = escape_markup


def _num(text):
    if text in (None, ""):
        return None
    return parse_decimal(str(text))


def _date_or_err(value, label, required=False):
    if not value:
        return (None, "%s : date requise (JJ/MM/AAAA)" % label) if required else (None, None)
    d = tr.parse_date(value)
    if not d:
        return None, "%s : format JJ/MM/AAAA attendu" % label
    return d.isoformat(), None


# ==========================================================================
# Project form
# ==========================================================================

class ProjectFormScreen(BaseScreen):
    title = "Marché"
    back = True

    def load(self, pid=None, **kw):
        self.pid = pid
        p = self.app.store.project(pid) if pid else {}
        self.bar.title = "Modifier le marché" if pid else "Nouveau marché"
        page = self.page
        page.clear()
        self.f = {}
        specs = [
            ("ref", "N° du marché / de l'appel d'offres", "12/2026", None),
            ("title", "Objet du marché", "Travaux de …", None),
            ("owner", "Maître d'ouvrage", "Commune, ministère, office…", None),
            ("location", "Lieu d'exécution", "Ville / province", None),
            ("amount_ttc", "Montant du marché TTC (DH)", "2450000,00", "float"),
            ("approval_notif_date", "Date de notification de l'approbation", "JJ/MM/AAAA", None),
            ("delay_months", "Délai d'exécution (mois)", "6", "int"),
            ("delay_days", "ou délai d'exécution (jours)", "180", "int"),
        ]
        c = W.Card()
        for key, label, hint, flt in specs:
            val = p.get(key) if p else ""
            if key == "approval_notif_date" and val:
                val = tr.fmt_date(val)
            if key == "amount_ttc" and val:
                val = ("%.2f" % val).replace(".", ",")
            fld = W.Field(label=label, hint=hint, text="" if val is None else str(val),
                          input_filter=None if flt != "int" else "int")
            self.f[key] = fld
            c.add_widget(fld)
        page.add(c)
        page.add(W.Muted(text="Astuce : laissez montant et délai vides, ils seront pré-remplis à partir du CPS "
                              "lors de l'analyse."))
        b = W.Btn(text="Enregistrer")
        b.bind(on_release=lambda *_: self.save())
        page.add(b)
        if pid:
            arch = W.ghost("Archiver ce marché (libère une place)")
            arch.bind(on_release=lambda *_: self.archive())
            page.add(arch)
            dl = W.danger_btn("Supprimer définitivement")
            dl.bind(on_release=lambda *_: self.delete())
            page.add(dl)

    def save(self):
        v = {k: f.text.strip() for k, f in self.f.items()}
        if not v["title"] and not v["ref"]:
            W.toast("Indiquez au moins l'objet ou le numéro du marché")
            return
        d, err = _date_or_err(v["approval_notif_date"], "Notification")
        if err:
            W.toast(err)
            return
        data = {"ref": v["ref"], "title": v["title"], "owner": v["owner"], "location": v["location"],
                "amount_ttc": _num(v["amount_ttc"]), "approval_notif_date": d,
                "delay_months": int(v["delay_months"]) if v["delay_months"] else None,
                "delay_days": int(v["delay_days"]) if v["delay_days"] else None}
        if data["delay_months"] and not data["delay_days"]:
            data["delay_days"] = data["delay_months"] * 30
        pid = self.app.store.save_project(data, self.pid)
        app = self.app
        if self.pid:
            app.back()
        else:
            app._history = []
            app.go("project", pid=pid)
            app._history = ["home"]

    def archive(self):
        self.app.store.save_project({"archived": 1}, self.pid)
        self.app.go("home", root_tab=True)
        self.app.sm.get_screen("home").refresh()

    def delete(self):
        def yes():
            self.app.store.delete_project(self.pid)
            self.app.go("home", root_tab=True)
            self.app.sm.get_screen("home").refresh()
        W.confirm("Supprimer le marché", "Toutes les données (documents, OS, décomptes…) seront effacées.",
                  yes, yes="Supprimer", danger=True)


# ==========================================================================
# Project workspace
# ==========================================================================

TABS = [("synthese", "Synthèse"), ("documents", "Documents"), ("obligations", "Obligations"),
        ("os", "Ordres de service"), ("quantites", "Quantités"), ("decomptes", "Décomptes"),
        ("receptions", "Réceptions"), ("risques", "Risques")]


class ProjectScreen(BaseScreen):
    title = "Marché"
    back = True

    def build_body(self):
        self.tabs = W.TabStrip()
        self.tabs.setup(TABS)
        self.tabs.bind(on_select=lambda inst, k: self.show(k))
        self.root_box.add_widget(self.tabs)
        self.page = W.Page()
        self.root_box.add_widget(self.page)
        self.tab = "synthese"
        self.pid = None
        self.filter = "Tout"

    def load(self, pid=None, tab=None, **kw):
        if pid:
            if pid != self.pid:
                self.tab = "synthese"
                self.filter = "Tout"
            self.pid = pid
        if tab:
            self.tab = tab
        self.refresh()

    def refresh(self):
        self.show(self.tab)

    def show(self, tab):
        self.tab = tab
        self.tabs.current = tab
        self.state = self.app.project_state(self.pid)
        if not self.state:
            return
        p = self.state["project_full"]
        self.bar.title = p.get("title") or "Marché"
        self.bar.subtitle = "N° %s · %s" % (p.get("ref") or "-", p.get("owner") or "-")
        self.bar.set_actions([W.bar_action("Modifier", lambda: self.app.go("project_form", pid=self.pid))])
        self.page.clear()
        getattr(self, "tab_" + tab)()

    # ------------------------------------------------------------ synthèse
    def tab_synthese(self):
        s, p, page = self.state, self.state["project_full"], self.page
        sched = tr.schedule(p, s["orders"], s["receptions"])
        fin = tr.financial_summary(p, s["items"], s["decomptes"], sched)
        rs = tr.reception_status(p, s["receptions"])

        c = W.Card(accent=C.danger if sched["late_days"] else C.primary)
        c.add_widget(W.Title(text="Délais"))
        if sched["start"]:
            c.add_widget(W.ProgressBarH(value=sched["progress"], color=C.danger if sched["late_days"] else C.primary))
            c.add_widget(W.kv_row("Début (OS de commencement)", tr.fmt_date(sched["start"])))
            c.add_widget(W.kv_row("Fin contractuelle", tr.fmt_date(sched["end"]), bold=True))
            if sched["suspended_days"]:
                c.add_widget(W.kv_row("Jours d'arrêt (OS)", "%d j" % sched["suspended_days"]))
            if sched.get("finished"):
                c.add_widget(W.kv_row("Achèvement", tr.fmt_date(sched["finished"])))
            elif sched["remaining"] is not None:
                c.add_widget(W.kv_row("Jours restants", "%d j" % max(0, sched["remaining"])))
            if sched["late_days"]:
                c.add_widget(W.kv_row("Retard", "%d jours" % sched["late_days"], C.danger, True))
        else:
            c.add_widget(W.Muted(text="Ajoutez l'ordre de service de commencement pour calculer le planning."))
            if not p.get("delay_days") and not p.get("delay_months"):
                c.add_widget(W.Muted(text="Délai d'exécution non renseigné."))
        if rs["warranty_end"]:
            c.add_widget(W.kv_row("Fin du délai de garantie", tr.fmt_date(rs["warranty_end"])))
        page.add(c)

        c = W.Card()
        c.add_widget(W.Title(text="Finances"))
        c.add_widget(W.kv_row("Montant du marché TTC", fmt_dh(p.get("amount_ttc"))))
        if fin["initial_ht"]:
            c.add_widget(W.kv_row("BPDE initial HT", fmt_dh(fin["initial_ht"])))
            c.add_widget(W.kv_row("Exécuté HT", "%s (%d %%)" % (fmt_dh(fin["executed_ht"]), fin["progress"] * 100)))
        c.add_widget(W.kv_row("Payé TTC", fmt_dh(fin["paid_ttc"]), C.success))
        c.add_widget(W.kv_row("Décomptes non payés", fmt_dh(fin["unpaid_ttc"]),
                              C.warning if fin["unpaid_ttc"] else None))
        c.add_widget(W.kv_row("Retenue de garantie", fmt_dh(fin["retenue"])))
        c.add_widget(W.kv_row("Pénalités de retard estimées", fmt_dh(fin["penalties_est"]),
                              C.danger if fin["penalties_est"] else None, bold=bool(fin["penalties_est"])))
        page.add(c)

        flags = s["flags"]
        page.add(W.section("Alertes prioritaires (%d)" % len(flags)))
        if not flags:
            page.add(W.Muted(text="Aucune alerte."))
        for f in flags[:4]:
            page.add(flag_card(f))
        if len(flags) > 4:
            b = W.ghost("Voir les %d alertes" % len(flags))
            b.bind(on_release=lambda *_: self.show("risques"))
            page.add(b)

        page.add(W.section("Clauses clés du contrat"))
        terms = s["terms"]
        c = W.Card()
        shown = 0
        for key, label in rules.TERM_LABELS.items():
            t = terms.get(key)
            if not t or key in ("execution_delay_months", "penalty_other_cap_pct"):
                continue
            shown += 1
            c.add_widget(W.kv_row(label, rules.format_term(key, t.get("value")),
                                  None if t.get("source") != "défaut" else C.muted))
            if t.get("article_key"):
                c.add_widget(W.chip_row([W.cite_chip(t.get("article_label"), t.get("page")),
                                         W.Chip(text=t.get("source"), bg=C.field, fg=C.muted)]))
            else:
                c.add_widget(W.Muted(text="Valeur par défaut : " + (t.get("article_label") or "")))
        if not shown:
            c.add_widget(W.Muted(text="Chargez le CPS pour extraire les clauses."))
        page.add(c)
        b = W.ghost("Corriger une valeur")
        b.bind(on_release=lambda *_: self.edit_terms())
        page.add(b)
        b = W.Btn(text="Exporter le rapport complet")
        b.bind(on_release=lambda *_: self.export_report())
        page.add(b)
        page.add(W.Muted(text=reg.DISCLAIMER))

    def edit_terms(self):
        terms = self.state["terms"]
        keys = ["penalty_rate_per_day", "penalty_cap_pct", "retenue_rate_pct", "retenue_cap_pct",
                "caution_definitive_pct", "warranty_months", "payment_delay_days", "tva_pct"]
        fields = []
        for k in keys:
            v = (terms.get(k) or {}).get("value")
            if k == "penalty_rate_per_day" and v:
                v = round(1 / v) if v else ""
                label = "Pénalité : 1/N par jour (N)"
            else:
                label = rules.TERM_LABELS[k]
            fields.append({"key": k, "label": label, "text": "" if v is None else str(v).replace(".", ",")})

        def submit(vals):
            proj = self.app.store.project(self.pid)
            manual = dict(proj.get("terms") or {})
            for k, v in vals.items():
                cur = (terms.get(k) or {}).get("value")
                num = _num(v)
                if num is None:
                    continue
                if k == "penalty_rate_per_day":
                    if num <= 0:
                        return "N doit être positif"
                    num = 1.0 / num
                if cur is not None and abs(float(cur) - num) < 1e-12:
                    continue
                manual[k] = {"value": num, "source": "saisie", "article_key": None,
                             "article_label": "Saisie manuelle", "page": None, "text": ""}
            self.app.store.save_project({"terms": manual}, self.pid)
            self.refresh()
        W.form("Clauses du contrat", fields, submit)

    def export_report(self):
        ok, why = self.app.sub.can("export")
        if not ok:
            W.info("Export", why)
            return
        s = self.state
        html_ = report.project_report(s, s["terms"], s["flags"])
        name = "Safqa_%s_%s.html" % ((s["project"].get("ref") or "marche").replace("/", "-"),
                                     date.today().strftime("%Y%m%d"))
        try:
            where, uri = save_to_downloads(name, html_.encode("utf-8"), "text/html", self.app.export_dir)
        except Exception as exc:  # noqa: BLE001
            W.info("Export", "Échec de l'enregistrement : %s" % exc)
            return
        W.info("Rapport exporté", "Enregistré dans : %s" % where,
               [W.ghost("Partager", on_release=lambda *_: share(uri, "text/html", name))])

    # ------------------------------------------------------------ documents
    def tab_documents(self):
        page, s = self.page, self.state
        b = W.Btn(text="+ Ajouter un document (CPS, marché, CCAG-T, BPDE…)")
        b.bind(on_release=lambda *_: self.add_document())
        page.add(b)
        if not s["documents"]:
            page.add(W.Muted(text="Formats acceptés : PDF, Word (.docx), texte. Les PDF scannés sont "
                                  "analysés par l'IA."))
        for d in s["documents"]:
            page.add(self._doc_card(d))
        page.add(W.section("Checklist des pièces"))
        page.add(W.Muted(text="Cochez les pièces disponibles : Safqa signale celles qui manquent selon la phase."))
        present = {c["code"]: c for c in s["checklist"] if c.get("present")}
        for phase in reg.PHASES:
            c = W.Card()
            items = [x for x in reg.DOCUMENT_CHECKLIST if x[2] == phase]
            done = sum(1 for x in items if x[0] in present)
            c.add_widget(W.WrapLabel(text="[b]%s[/b]  [color=#667085]%d/%d[/color]" % (phase, done, len(items))))
            for code, label, _ph, mandatory in items:
                cb = W.check(code in present, lambda v, cd=code: self._set_check(cd, v))
                c.add_widget(W.check_row(cb, e(label) + ("" if mandatory else
                                                         "  [color=#98A2B3](facultatif)[/color]"), sp(13.5)))
            page.add(c)

    def _set_check(self, code, value):
        self.app.store.set_check(self.pid, code, value, date.today().isoformat() if value else None)

    def _doc_card(self, d):
        a = d.get("analysis") or {}
        fnd = unified_findings(d)
        counts = {}
        for f in fnd:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        c = W.Card(accent=C.accent if d.get("doc_type") in ("CPS", "MARCHE") else C.primary)
        c.add_widget(W.WrapLabel(text="[b]%s[/b]" % e(d.get("filename") or ""), font_size=sp(14.5)))
        c.add_widget(W.Muted(text="%s · %s page(s)%s" % (DOC_TYPES.get(d.get("doc_type"), d.get("doc_type")),
                                                        d.get("pages"), " · PDF scanné" if d.get("scanned") else "")))
        chips = [W.Chip(text="%d obligations" % (counts.get("obligation", 0) + counts.get("prohibition", 0))),
                 W.Chip(text="%d délais" % counts.get("deadline", 0)),
                 W.Chip(text="%d pénalités" % counts.get("penalty", 0))]
        nb_issues = len(a.get("issues", [])) + len(a.get("ai_risks", []))
        if nb_issues:
            chips.append(W.Chip(text="%d points d'attention" % nb_issues, fg=W.SEVERITY["élevé"][0],
                                bg=W.SEVERITY["élevé"][1]))
        c.add_widget(W.chip_row(chips[:3]))
        if len(chips) > 3:
            c.add_widget(W.chip_row(chips[3:]))
        if a.get("ai"):
            c.add_widget(W.Muted(text="[color=#12B76A][b]Analyse IA effectuée[/b][/color]"))
        row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        b1 = W.ghost("Voir l'analyse", height=dp(42))
        b1.bind(on_release=lambda *_: self.app.go("document", doc_id=d["id"], pid=self.pid))
        b2 = W.Btn(text="Analyse IA" if not a.get("ai") else "Relancer l'IA", height=dp(42), bg=C.accent,
                   fg=C.text)
        b2.bind(on_release=lambda *_: self.run_ai(d))
        row.add_widget(b1)
        row.add_widget(b2)
        c.add_widget(row)
        return c

    def add_document(self):
        def picked(path, name):
            if not path:
                if name:
                    W.info("Document", name)
                return
            if path.lower().endswith(".csv"):
                self._import_csv(path)
                return
            self._choose_type(path, name)
        self.app.picker.pick(picked)

    def _choose_type(self, path, name):
        choices = [("", "Détection automatique")] + list(DOC_TYPES.items())

        def submit(vals):
            self._ingest(path, name, vals.get("doc_type") or None)
        W.form("Type de document", [{"key": "doc_type", "label": "Nature de la pièce", "choices": choices,
                                     "text": ""}], submit, submit="Analyser")

    def _ingest(self, path, name, doc_type):
        pid = self.pid

        def work(progress):
            progress("Extraction du texte…")
            return analysis.ingest(path, name, doc_type)

        def done(res):
            res["project_id"] = pid
            res["uploaded_at"] = date.today().isoformat()
            doc_id = self.app.store.insert("documents", res)
            self._autofill(res)
            self.app.store.touch(pid)
            n = len(res["analysis"]["findings"])
            msg = "%d éléments extraits hors-ligne." % n
            if res["scanned"]:
                msg = "PDF scanné : le texte n'est pas lisible hors-ligne. Lancez l'analyse IA."
            W.toast(msg, 3.5)
            self.app.go("document", doc_id=doc_id, pid=pid)

        def fail(msg):
            W.info("Document illisible", msg)
            try:
                os.remove(path)
            except OSError:
                pass
        self.app.run_bg(work, done, "Analyse du document…", fail)

    def _autofill(self, doc):
        """Fill empty project fields from the contract terms."""
        p = self.app.store.project(self.pid)
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
        ai_res = (doc.get("analysis") or {}).get("ai") or {}
        ct = ai_res.get("contract") or {}
        if not p.get("owner") and ct.get("maitre_ouvrage"):
            upd["owner"] = ct["maitre_ouvrage"]
        if not p.get("title") and ct.get("objet"):
            upd["title"] = ct["objet"]
        if upd:
            self.app.store.save_project(upd, self.pid)
            W.toast("Fiche du marché complétée à partir du document", 3)

    def run_ai(self, d):
        ok, why = self.app.sub.can("ai_analysis")
        if not ok:
            W.info("Analyse IA", why, [W.Btn(text="Abonnements",
                                             on_release=lambda *_: self.app.go("account", root_tab=True))])
            return
        client = self.app.ai_client()
        if not client.configured:
            W.info("Configuration requise", "Renseignez votre clé API ou le serveur Safqa dans l'onglet Compte.")
            return
        store = self.app.store
        doc = store.q1("SELECT * FROM documents WHERE id=?", (d["id"],))

        def work(progress):
            progress("Envoi du document (%d caractères)…" % (doc.get("char_count") or 0))
            return analysis.run_ai(client, doc, on_progress=lambda n: progress("Réponse : %d caractères" % n))

        def done(new_analysis):
            store.update("documents", d["id"], {"analysis": new_analysis, "ai_status": "ok"})
            store.bump_usage("ai_analysis")
            doc["analysis"] = new_analysis
            self._autofill(doc)
            ai_res = new_analysis.get("ai") or {}
            items = sum(len(ai_res.get(k, [])) for k in ("obligations", "deadlines", "penalties", "risks"))
            verified = sum(1 for k in ("obligations", "deadlines", "penalties", "risks")
                           for x in ai_res.get(k, []) if x.get("verified"))
            W.toast("Analyse IA : %d éléments, %d citations vérifiées" % (items, verified), 4)
            self.app.go("document", doc_id=d["id"], pid=self.pid)
        self.app.run_bg(work, done, "Analyse IA en cours (1 à 3 minutes)…")

    # ------------------------------------------------------------ obligations
    def tab_obligations(self):
        page, s = self.page, self.state
        all_f = []
        for d in s["documents"]:
            for f in unified_findings(d):
                if f["kind"] in ("obligation", "prohibition", "deadline", "penalty", "document", "financial"):
                    f = dict(f, doc=d.get("filename"))
                    all_f.append(f)
        filters = ["Tout", "Titulaire", "Maître d'ouvrage", "Délais", "Pénalités", "Documents", "Finances"]
        sel = W.spinner(filters, self.filter)
        sel.height = dp(40)
        sel.bind(text=lambda inst, v: (setattr(self, "filter", v), self.show("obligations")))
        page.add(sel)

        def keep(f):
            flt = self.filter
            if flt == "Tout":
                return True
            if flt in ("Titulaire", "Maître d'ouvrage"):
                return f.get("party") == flt and f["kind"] in ("obligation", "prohibition", "document")
            return {"Délais": "deadline", "Pénalités": "penalty", "Documents": "document",
                    "Finances": "financial"}[flt] == f["kind"]
        items = [f for f in all_f if keep(f)]
        page.add(W.Muted(text="%d élément(s) · chaque élément renvoie à l'article source" % len(items)))
        if not s["documents"]:
            page.add(W.Muted(text="Ajoutez un document dans l'onglet Documents."))
        for f in items[:150]:
            page.add(finding_card(f))
        if len(items) > 150:
            page.add(W.Muted(text="Affichage limité à 150 éléments : utilisez les filtres."))

    # ------------------------------------------------------------ ordres de service
    def tab_os(self):
        page, s = self.page, self.state
        sched = tr.schedule(s["project_full"], s["orders"], s["receptions"])
        c = W.Card()
        c.add_widget(W.Title(text="Planning contractuel"))
        c.add_widget(W.kv_row("Délai d'exécution", "%s jours" % (s["project"].get("delay_days") or "-")))
        c.add_widget(W.kv_row("Début", tr.fmt_date(sched["start"])))
        c.add_widget(W.kv_row("Arrêts cumulés", "%d j" % sched["suspended_days"]))
        if sched["extension_days"]:
            c.add_widget(W.kv_row("Prolongations", "%d j" % sched["extension_days"]))
        c.add_widget(W.kv_row("Fin contractuelle", tr.fmt_date(sched["end"]), bold=True))
        if sched["stopped"]:
            c.add_widget(W.WrapLabel(text="[color=#B54708][b]Chantier à l'arrêt[/b][/color]"))
        page.add(c)
        b = W.Btn(text="+ Enregistrer un ordre de service")
        b.bind(on_release=lambda *_: self.edit_os())
        page.add(b)
        for o in reversed(s["orders"]):
            oc = W.Card(accent={"commencement": C.success, "arret": C.danger, "reprise": C.info}.get(o.get("kind")))
            oc.add_widget(W.WrapLabel(text="[b]OS n° %s[/b] - %s" % (e(o.get("number") or "-"),
                                                                    e(tr.OS_LABELS.get(o.get("kind"), "")))))
            sub = "Notifié le %s" % tr.fmt_date(o.get("date"))
            if o.get("effective_date") and o.get("effective_date") != o.get("date"):
                sub += " · effet le %s" % tr.fmt_date(o["effective_date"])
            if o.get("days"):
                sub += " · %s jours" % o["days"]
            oc.add_widget(W.Muted(text=sub))
            if o.get("note"):
                oc.add_widget(W.WrapLabel(text=e(o["note"]), font_size=sp(13)))
            row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
            b1 = W.ghost("Modifier", height=dp(38))
            b1.bind(on_release=lambda *_, oo=o: self.edit_os(oo))
            b2 = W.danger_btn("Supprimer", height=dp(38))
            b2.bind(on_release=lambda *_, oo=o: self._delete("orders", oo["id"]))
            row.add_widget(b1)
            row.add_widget(b2)
            oc.add_widget(row)
            page.add(oc)

    def edit_os(self, o=None):
        o = o or {}
        nxt = str(len(self.state["orders"]) + 1)
        fields = [
            {"key": "kind", "label": "Type d'ordre de service", "choices": tr.OS_KINDS, "text": o.get("kind", "commencement")},
            {"key": "number", "label": "Numéro", "text": o.get("number", nxt)},
            {"key": "date", "label": "Date de notification (JJ/MM/AAAA)", "text": tr.fmt_date(o["date"]) if o.get("date") else ""},
            {"key": "effective_date", "label": "Date d'effet si différente", "text": tr.fmt_date(o["effective_date"]) if o.get("effective_date") else ""},
            {"key": "days", "label": "Jours de prolongation (si prolongation)", "text": o.get("days") or "", "filter": "int"},
            {"key": "note", "label": "Objet / observations", "text": o.get("note", ""), "multiline": True},
        ]

        def submit(v):
            d, err = _date_or_err(v["date"], "Date", True)
            if err:
                return err
            eff, err = _date_or_err(v["effective_date"], "Date d'effet")
            if err:
                return err
            data = {"project_id": self.pid, "kind": v["kind"], "number": v["number"], "date": d,
                    "effective_date": eff, "days": int(v["days"]) if v["days"] else None, "note": v["note"]}
            if o.get("id"):
                self.app.store.update("orders", o["id"], data)
            else:
                self.app.store.insert("orders", data)
                if v["kind"] == "commencement":
                    self.app.store.set_check(self.pid, "OS_COMMENCEMENT", True, d)
            self.refresh()
        W.form("Ordre de service", fields, submit)

    def _delete(self, table, row_id):
        def yes():
            self.app.store.delete(table, row_id)
            self.refresh()
        W.confirm("Supprimer", "Supprimer cet élément ?", yes, yes="Supprimer", danger=True)

    # ------------------------------------------------------------ quantités
    def tab_quantites(self):
        page, s = self.page, self.state
        q = tr.quantities_summary(s["items"], s["terms"])
        c = W.Card()
        c.add_widget(W.Title(text="Bordereau des prix - détail estimatif"))
        c.add_widget(W.kv_row("Montant initial HT", fmt_dh(q["initial_ht"])))
        c.add_widget(W.kv_row("Exécuté HT (cumul)", fmt_dh(q["executed_ht"])))
        c.add_widget(W.ProgressBarH(value=q["progress"], color=C.success))
        if q["initial_ht"]:
            col = C.danger if q["mass_variation_pct"] > (q["mass_increase_limit_pct"] or 10) else None
            c.add_widget(W.kv_row("Variation dans la masse", "%+.1f %%" % q["mass_variation_pct"], col, True))
        page.add(c)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        b1 = W.Btn(text="+ Prix", height=dp(44))
        b1.bind(on_release=lambda *_: self.edit_item())
        b2 = W.ghost("Importer CSV", height=dp(44))
        b2.bind(on_release=lambda *_: self.app.picker.pick(lambda p_, n: p_ and self._import_csv(p_)))
        row.add_widget(b1)
        row.add_widget(b2)
        page.add(row)
        ai_items = [it for d in s["documents"] for it in (((d.get("analysis") or {}).get("ai") or {}).get("bpde_items") or [])]
        if ai_items and not s["items"]:
            b3 = W.Btn(text="Importer %d prix extraits par l'IA" % len(ai_items), bg=C.accent, fg=C.text)
            b3.bind(on_release=lambda *_: self._import_items([
                {"number": it.get("number"), "designation": it.get("designation"), "unit": it.get("unit"),
                 "qty_contract": it.get("quantity") or 0, "unit_price_ht": it.get("unit_price_ht") or 0,
                 "qty_executed": 0} for it in ai_items]))
            page.add(b3)
        if not s["items"]:
            page.add(W.Muted(text="Format CSV : n° ; désignation ; unité ; quantité ; prix unitaire HT "
                                  "(une ligne par prix)."))
        for r in q["rows"]:
            it = r["item"]
            ic = W.Card(accent=C.danger if r["overrun"] else None)
            ic.add_widget(W.WrapLabel(text="[b]%s[/b]  %s" % (e(str(it.get("number") or "")), e(it.get("designation") or "")),
                                      font_size=sp(14)))
            ic.add_widget(W.Muted(text="%s %s prévus × %s HT = %s" % (
                _q(it.get("qty_contract")), e(it.get("unit") or ""), fmt_dh(it.get("unit_price_ht")),
                fmt_dh((it.get("qty_contract") or 0) * (it.get("unit_price_ht") or 0)))))
            ic.add_widget(W.ProgressBarH(value=r["progress"], color=C.danger if r["overrun"] else C.primary))
            txt = "Exécuté : [b]%s %s[/b] (%d %%) · %s" % (_q(it.get("qty_executed")), e(it.get("unit") or ""),
                                                          r["progress"] * 100, fmt_dh(r["amount_ht"]))
            if r["overrun"]:
                txt += "  [color=#D92D20][b]+%d %%[/b][/color]" % r["variance_pct"]
            ic.add_widget(W.WrapLabel(text=txt, font_size=sp(13)))
            rw = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
            b1 = W.Btn(text="Saisir quantité", height=dp(38))
            b1.bind(on_release=lambda *_, ii=it: self.edit_qty(ii))
            b2 = W.ghost("Modifier", height=dp(38))
            b2.bind(on_release=lambda *_, ii=it: self.edit_item(ii))
            rw.add_widget(b1)
            rw.add_widget(b2)
            ic.add_widget(rw)
            page.add(ic)

    def _import_csv(self, path):
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", "replace")
        except OSError as exc:
            W.info("Import CSV", str(exc))
            return
        items = tr.parse_bpde_csv(text)
        if not items:
            W.info("Import CSV", "Aucune ligne valide. Format : n° ; désignation ; unité ; quantité ; prix unitaire HT")
            return
        self._import_items(items)

    def _import_items(self, items):
        for it in items:
            it["project_id"] = self.pid
            self.app.store.insert("items", it)
        self.app.store.set_check(self.pid, "BPDE_SIGNE", True)
        W.toast("%d prix importés" % len(items))
        self.show("quantites")

    def edit_item(self, it=None):
        it = it or {}
        fields = [
            {"key": "number", "label": "N° de prix", "text": it.get("number", "")},
            {"key": "designation", "label": "Désignation", "text": it.get("designation", "")},
            {"key": "unit", "label": "Unité (m³, ml, m², U, Ft…)", "text": it.get("unit", "")},
            {"key": "qty_contract", "label": "Quantité du BPDE", "text": _q(it.get("qty_contract")) if it else ""},
            {"key": "unit_price_ht", "label": "Prix unitaire HT (DH)", "text": _q(it.get("unit_price_ht")) if it else ""},
        ]

        def submit(v):
            qty, pu = _num(v["qty_contract"]), _num(v["unit_price_ht"])
            if qty is None or pu is None:
                return "Quantité et prix unitaire requis"
            data = {"project_id": self.pid, "number": v["number"], "designation": v["designation"],
                    "unit": v["unit"], "qty_contract": qty, "unit_price_ht": pu}
            if it.get("id"):
                self.app.store.update("items", it["id"], data)
            else:
                data["qty_executed"] = 0
                self.app.store.insert("items", data)
            self.refresh()
        s = W.form("Prix du bordereau", fields, submit)
        if it.get("id"):
            s.add_button(W.danger_btn("Supprimer", on_release=lambda *_: (s.dismiss(), self._delete("items", it["id"]))))

    def edit_qty(self, it):
        def submit(v):
            q = _num(v["qty"])
            if q is None or q < 0:
                return "Quantité invalide"
            self.app.store.update("items", it["id"], {"qty_executed": q})
            self.refresh()
        W.form("Prix n° %s - quantité cumulée" % (it.get("number") or ""),
               [{"key": "qty", "label": "Quantité exécutée cumulée (%s), selon attachement" % (it.get("unit") or ""),
                 "text": _q(it.get("qty_executed"))}], submit)

    # ------------------------------------------------------------ décomptes
    def tab_decomptes(self):
        page, s = self.page, self.state
        b = W.Btn(text="+ Établir le décompte n° %d" % (len(s["decomptes"]) + 1))
        b.bind(on_release=lambda *_: self.new_decompte())
        page.add(b)
        if not s["items"]:
            page.add(W.Muted(text="Les décomptes sont calculés à partir des quantités cumulées de l'onglet Quantités."))
        for d in reversed(s["decomptes"]):
            st = tr.payment_status(d, s["terms"])
            accent = C.success if d.get("paid_date") else (C.danger if st["late"] else C.warning)
            c = W.Card(accent=accent)
            c.add_widget(W.WrapLabel(text="[b]Décompte %s n° %s[/b]" % ("définitif" if d.get("final") else "provisoire",
                                                                       d.get("number"))))
            c.add_widget(W.kv_row("Total TTC cumulé", fmt_dh(d.get("total_ttc"))))
            c.add_widget(W.kv_row("Retenue de garantie", "- " + fmt_dh(d.get("retenue"))))
            if d.get("penalties"):
                c.add_widget(W.kv_row("Pénalités", "- " + fmt_dh(d.get("penalties")), C.danger))
            c.add_widget(W.kv_row("Décomptes précédents", "- " + fmt_dh(d.get("previous_ttc"))))
            c.add_widget(W.kv_row("Net à payer", fmt_dh(d.get("net_ttc")), C.primary, True))
            if d.get("paid_date"):
                c.add_widget(W.Muted(text="Payé le %s (%s)%s" % (tr.fmt_date(d["paid_date"]), fmt_dh(d.get("paid_amount")),
                                                                ", %d j de retard" % st["late_days"] if st.get("late") else "")))
            elif d.get("submitted_date"):
                c.add_widget(W.WrapLabel(text="Constaté le %s · [b]%d j[/b] / %d j%s" % (
                    tr.fmt_date(d["submitted_date"]), st["days"], st["limit"],
                    "  [color=#D92D20][b]retard de paiement[/b][/color]" if st["late"] else ""), font_size=sp(13)))
            row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
            b1 = W.Btn(text="Paiement", height=dp(38))
            b1.bind(on_release=lambda *_, dd=d: self.edit_payment(dd))
            b2 = W.ghost("CSV", height=dp(38))
            b2.bind(on_release=lambda *_, dd=d: self.export_decompte(dd))
            b3 = W.danger_btn("Suppr.", height=dp(38))
            b3.bind(on_release=lambda *_, dd=d: self._delete("decomptes", dd["id"]))
            for x in (b1, b2, b3):
                row.add_widget(x)
            c.add_widget(row)
            page.add(c)

    def new_decompte(self):
        s = self.state
        sched = tr.schedule(s["project_full"], s["orders"], s["receptions"])
        pen = tr.penalty_estimate(s["project_full"], sched)
        fields = [
            {"key": "date", "label": "Date du décompte (JJ/MM/AAAA)", "text": date.today().strftime("%d/%m/%Y")},
            {"key": "revision", "label": "Révision des prix HT (cumul, DH)", "text": "0"},
            {"key": "penalties", "label": "Pénalités à déduire (DH)", "text": ("%.2f" % pen["amount"]).replace(".", ",")},
            {"key": "advance", "label": "Remboursement de l'avance (cumul, DH)", "text": "0"},
            {"key": "final", "label": "Décompte définitif", "check": True, "text": False},
        ]
        preview = W.WrapLabel(text="", font_size=sp(13))

        def compute(v):
            return tr.compute_decompte(s["project_full"], s["items"], s["decomptes"],
                                       revision_ht=_num(v["revision"]) or 0, penalties=_num(v["penalties"]) or 0,
                                       advance_recovery=_num(v["advance"]) or 0, final=v["final"])

        def submit(v):
            d, err = _date_or_err(v["date"], "Date", True)
            if err:
                return err
            res = compute(v)
            res.update(project_id=self.pid, date=d, status="émis")
            self.app.store.insert("decomptes", res)
            self.app.store.set_check(self.pid, "DECOMPTES", True)
            if v["final"]:
                self.app.store.set_check(self.pid, "DECOMPTE_DEF", True, d)
            W.toast("Décompte n° %d : net à payer %s" % (res["number"], fmt_dh(res["net_ttc"])), 3.5)
            self.refresh()
        sheet = W.form("Décompte n° %d" % (len(s["decomptes"]) + 1), fields, submit, extra=preview)

        def update_preview(*_):
            try:
                r = compute(sheet.values())
            except Exception:  # noqa: BLE001 - partial input while typing
                return
            preview.text = ("Travaux HT %s · TVA %s · TTC %s\nRetenue %s · Précédents %s\n[b]Net à payer : %s[/b]" % (
                fmt_dh(r["works_ht"]), fmt_dh(r["tva"]), fmt_dh(r["total_ttc"]), fmt_dh(r["retenue"]),
                fmt_dh(r["previous_ttc"]), fmt_dh(r["net_ttc"])))
        update_preview()
        for w in sheet.inner.walk():
            if isinstance(w, W.Field):
                w.bind(text=update_preview)

    def edit_payment(self, d):
        fields = [
            {"key": "submitted", "label": "Date de constatation / dépôt (JJ/MM/AAAA)",
             "text": tr.fmt_date(d["submitted_date"]) if d.get("submitted_date") else ""},
            {"key": "paid", "label": "Date de paiement", "text": tr.fmt_date(d["paid_date"]) if d.get("paid_date") else ""},
            {"key": "amount", "label": "Montant encaissé (DH)",
             "text": ("%.2f" % (d.get("paid_amount") or d.get("net_ttc") or 0)).replace(".", ",")},
        ]

        def submit(v):
            sd, err = _date_or_err(v["submitted"], "Constatation")
            if err:
                return err
            pd, err = _date_or_err(v["paid"], "Paiement")
            if err:
                return err
            self.app.store.update("decomptes", d["id"], {"submitted_date": sd, "paid_date": pd,
                                                         "paid_amount": _num(v["amount"]) if pd else None})
            self.refresh()
        W.form("Suivi du paiement", fields, submit)

    def export_decompte(self, d):
        ok, why = self.app.sub.can("export")
        if not ok:
            W.info("Export", why)
            return
        data = report.decompte_csv(self.state["project"], d).encode("utf-8-sig")
        name = "Decompte_%s_n%s.csv" % ((self.state["project"].get("ref") or "marche").replace("/", "-"), d.get("number"))
        where, uri = save_to_downloads(name, data, "text/csv", self.app.export_dir)
        W.info("Décompte exporté", "Enregistré dans : %s" % where,
               [W.ghost("Partager", on_release=lambda *_: share(uri, "text/csv", name))])

    # ------------------------------------------------------------ réceptions
    def tab_receptions(self):
        page, s = self.page, self.state
        rs = tr.reception_status(s["project_full"], s["receptions"])
        for kind, label in (("provisoire", "Réception provisoire"), ("definitive", "Réception définitive")):
            r = next((x for x in s["receptions"] if x.get("kind") == kind), None)
            c = W.Card(accent=C.success if r else C.border)
            c.add_widget(W.Title(text=label))
            if r:
                c.add_widget(W.kv_row("Date du PV", tr.fmt_date(r.get("date"))))
                if kind == "provisoire":
                    c.add_widget(W.kv_row("Réserves", "Oui" if r.get("with_reserves") else "Non"))
                    if r.get("with_reserves"):
                        c.add_widget(W.kv_row("Levée des réserves", tr.fmt_date(r.get("reserves_lifted_date")),
                                              None if r.get("reserves_lifted_date") else C.danger))
                    c.add_widget(W.kv_row("Délai de garantie", "%d mois" % rs["warranty_months"]))
                    c.add_widget(W.kv_row("Réception définitive attendue", tr.fmt_date(rs["warranty_end"]), bold=True))
                if r.get("note"):
                    c.add_widget(W.WrapLabel(text=e(r["note"]), font_size=sp(13)))
            else:
                c.add_widget(W.Muted(text="Non prononcée."))
                if kind == "definitive" and rs["warranty_end"]:
                    c.add_widget(W.Muted(text="Exigible à partir du %s." % tr.fmt_date(rs["warranty_end"])))
            b = W.ghost("Modifier" if r else "Enregistrer le PV", height=dp(40))
            b.bind(on_release=lambda *_, kk=kind, rr=r: self.edit_reception(kk, rr))
            c.add_widget(b)
            page.add(c)
        page.add(W.Muted(text="À la réception définitive : demandez la restitution de la retenue de garantie et "
                              "la mainlevée du cautionnement définitif."))

    def edit_reception(self, kind, r=None):
        r = r or {}
        fields = [{"key": "date", "label": "Date du PV (JJ/MM/AAAA)", "text": tr.fmt_date(r["date"]) if r.get("date") else ""}]
        if kind == "provisoire":
            fields += [
                {"key": "works_end_date", "label": "Date d'achèvement constatée (si différente)",
                 "text": tr.fmt_date(r["works_end_date"]) if r.get("works_end_date") else ""},
                {"key": "with_reserves", "label": "Prononcée avec réserves", "check": True, "text": r.get("with_reserves")},
                {"key": "lifted", "label": "Date de levée des réserves",
                 "text": tr.fmt_date(r["reserves_lifted_date"]) if r.get("reserves_lifted_date") else ""},
            ]
        fields.append({"key": "note", "label": "Observations", "text": r.get("note", ""), "multiline": True})

        def submit(v):
            d, err = _date_or_err(v["date"], "Date", True)
            if err:
                return err
            data = {"project_id": self.pid, "kind": kind, "date": d, "note": v.get("note")}
            if kind == "provisoire":
                we, err = _date_or_err(v.get("works_end_date"), "Achèvement")
                if err:
                    return err
                lf, err = _date_or_err(v.get("lifted"), "Levée")
                if err:
                    return err
                data.update(works_end_date=we, with_reserves=1 if v.get("with_reserves") else 0,
                            reserves_lifted_date=lf)
            if r.get("id"):
                self.app.store.update("receptions", r["id"], data)
            else:
                self.app.store.insert("receptions", data)
            self.app.store.set_check(self.pid, "PV_RECEP_PROV" if kind == "provisoire" else "PV_RECEP_DEF", True, d)
            if kind == "provisoire" and data.get("reserves_lifted_date"):
                self.app.store.set_check(self.pid, "LEVEE_RESERVES", True, data["reserves_lifted_date"])
            self.refresh()
        W.form("Réception " + kind, fields, submit)

    # ------------------------------------------------------------ risques
    def tab_risques(self):
        from ..risk import exposure
        page, s = self.page, self.state
        flags = s["flags"]
        c = W.Card()
        c.add_widget(W.Title(text="Tableau des risques"))
        counts = {k: sum(1 for f in flags if f["severity"] == k) for k in ("critique", "élevé", "moyen", "info")}
        c.add_widget(W.chip_row([W.Chip(text="%d %s" % (n, W.SEVERITY[k][2].lower()), fg=W.SEVERITY[k][0],
                                        bg=W.SEVERITY[k][1]) for k, n in counts.items() if n]))
        exp = exposure(flags)
        if exp["penalties"]:
            c.add_widget(W.kv_row("Pénalités encourues", fmt_dh(exp["penalties"]), C.danger, True))
        if exp["late_receivables"]:
            c.add_widget(W.kv_row("Créances payées en retard / impayées", fmt_dh(exp["late_receivables"]),
                                  C.warning, True))
        page.add(c)
        if not flags:
            page.add(W.Muted(text="Aucun risque détecté pour le moment."))
        for f in flags:
            page.add(flag_card(f))


def _q(v):
    if v is None:
        return ""
    v = float(v)
    return str(int(v)) if v.is_integer() else ("%.3f" % v).rstrip("0").rstrip(".").replace(".", ",")


def flag_card(f):
    fg, bg, label = W.SEVERITY.get(f["severity"], (C.muted, C.field, f["severity"]))
    c = W.Card(accent=fg)
    c.add_widget(W.chip_row([W.sev_chip(f["severity"]), W.Chip(text=f.get("category") or "", bg=C.field, fg=C.muted)]))
    c.add_widget(W.WrapLabel(text="[b]%s[/b]" % e(f["title"]), font_size=sp(14.5)))
    if f.get("detail"):
        c.add_widget(W.WrapLabel(text=e(f["detail"]), font_size=sp(13)))
    if f.get("action"):
        c.add_widget(W.WrapLabel(text="[color=#0B4F6C][b]Action :[/b][/color] " + e(f["action"]), font_size=sp(13)))
    if f.get("article_label"):
        c.add_widget(W.chip_row([W.cite_chip(f["article_label"], f.get("page"))]))
    if f.get("text"):
        c.add_widget(W.Muted(text="[i]« %s »[/i]" % e(_trim(f["text"], 260))))
    return c


def finding_card(f):
    kind = f["kind"]
    accent = {"penalty": C.danger, "deadline": C.info, "document": C.accent, "financial": C.success}.get(kind, C.primary)
    c = W.Card(accent=accent)
    chips = [W.Chip(text=KIND_LABELS.get(kind, kind))]
    if f.get("party") and f["party"] != "Non précisé":
        chips.append(W.Chip(text=f["party"], bg=C.field, fg=C.text))
    chips.append(W.Chip(text=f.get("source") or "", bg=C.field, fg=C.muted))
    c.add_widget(W.chip_row(chips))
    c.add_widget(W.WrapLabel(text=e(f.get("summary") or ""), font_size=sp(14)))
    if f.get("deadline"):
        c.add_widget(W.WrapLabel(text="[color=#175CD3]Échéance : %s[/color]" % e(f["deadline"]), font_size=sp(13)))
    if f.get("text") and f.get("text") != f.get("summary"):
        c.add_widget(W.Muted(text="[i]« %s »[/i]" % e(_trim(f["text"], 300))))
    cite = []
    if f.get("article_label"):
        cite.append(W.cite_chip(f["article_label"], f.get("page")))
    if f.get("source") == "IA":
        cite.append(W.Chip(text="citation vérifiée" if f.get("verified") else "à vérifier",
                           bg=W.SEVERITY["info"][1] if f.get("verified") else W.SEVERITY["moyen"][1],
                           fg=W.SEVERITY["info"][0] if f.get("verified") else W.SEVERITY["moyen"][0]))
    if cite:
        c.add_widget(W.chip_row(cite))
    return c


def _trim(t, n):
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


# ==========================================================================
# Document analysis view
# ==========================================================================

DOC_TABS = [("elements", "Éléments"), ("problemes", "Points d'attention"), ("resume", "Résumé IA"),
            ("articles", "Articles")]


class DocumentScreen(BaseScreen):
    title = "Analyse"
    back = True

    def build_body(self):
        self.tabs = W.TabStrip()
        self.tabs.setup(DOC_TABS)
        self.tabs.bind(on_select=lambda inst, k: self.show(k))
        self.root_box.add_widget(self.tabs)
        self.page = W.Page()
        self.root_box.add_widget(self.page)
        self.tab = "elements"
        self.kind = "Tout"

    def load(self, doc_id=None, pid=None, **kw):
        self.doc_id = doc_id
        self.pid = pid
        self.tab = "elements"
        self.kind = "Tout"
        self.refresh()

    def refresh(self):
        self.show(self.tab)

    def show(self, tab):
        self.tab = tab
        self.tabs.current = tab
        self.doc = self.app.store.q1("SELECT * FROM documents WHERE id=?", (self.doc_id,))
        if not self.doc:
            return
        self.bar.title = self.doc.get("filename") or "Document"
        self.bar.subtitle = "%s · %s page(s)" % (DOC_TYPES.get(self.doc.get("doc_type"), ""), self.doc.get("pages"))
        self.bar.set_actions([W.bar_action("Supprimer", self.delete)])
        self.page.clear()
        getattr(self, "tab_" + tab)()

    def delete(self):
        def yes():
            try:
                os.remove(self.doc.get("path") or "")
            except OSError:
                pass
            self.app.store.delete("documents", self.doc_id)
            self.app.back()
        W.confirm("Supprimer le document", "Le document et son analyse seront supprimés.", yes,
                  yes="Supprimer", danger=True)

    def tab_elements(self):
        page = self.page
        fnd = unified_findings(self.doc)
        if self.doc.get("scanned") and not (self.doc.get("analysis") or {}).get("ai"):
            c = W.Card(accent=C.warning)
            c.add_widget(W.WrapLabel(text="[b]PDF scanné[/b] : le texte est une image. Lancez l'analyse IA depuis "
                                          "l'onglet Documents du marché pour l'exploiter."))
            page.add(c)
        kinds = ["Tout"] + sorted(set(KIND_LABELS.get(f["kind"], f["kind"]) for f in fnd))
        sel = W.spinner(kinds, self.kind if self.kind in kinds else "Tout")
        sel.bind(text=lambda inst, v: (setattr(self, "kind", v), self.show("elements")))
        page.add(sel)
        items = [f for f in fnd if self.kind == "Tout" or KIND_LABELS.get(f["kind"], f["kind"]) == self.kind]
        page.add(W.Muted(text="%d élément(s)" % len(items)))
        for f in items[:200]:
            page.add(finding_card(f))

    def tab_problemes(self):
        page = self.page
        a = self.doc.get("analysis") or {}
        issues = list(a.get("issues", []))
        for r in a.get("ai_risks", []):
            issues.append({"severity": r.get("severity"), "title": r.get("title"), "detail": r.get("detail"),
                           "action": r.get("action"), "article_label": r.get("article_label"),
                           "page": r.get("page"), "text": r.get("quote"), "category": "IA"})
        if not issues:
            page.add(W.Muted(text="Aucun point d'attention détecté."))
        from ..risk import SEVERITY_ORDER
        for i in sorted(issues, key=lambda x: SEVERITY_ORDER.get(x.get("severity"), 9)):
            i.setdefault("category", "Règles")
            page.add(flag_card(i))

    def tab_resume(self):
        page = self.page
        ai_res = (self.doc.get("analysis") or {}).get("ai")
        if not ai_res:
            page.add(W.Muted(text="Aucune analyse IA pour ce document. Lancez-la depuis l'onglet Documents du marché."))
            return
        c = W.Card()
        ct = ai_res.get("contract") or {}
        for k, label in (("objet", "Objet"), ("maitre_ouvrage", "Maître d'ouvrage"), ("reference", "Référence"),
                         ("lieu", "Lieu")):
            if ct.get(k):
                c.add_widget(W.kv_row(label, e(ct[k])))
        c.add_widget(W.WrapLabel(text=e(ai_res.get("summary") or ""), font_size=sp(14)))
        page.add(c)

    def tab_articles(self):
        page = self.page
        arts = analysis.articles_of(self.doc)
        page.add(W.Muted(text="%d article(s) détecté(s)" % len(arts)))
        for a in arts:
            b = W.ghost("%s  ·  p.%s" % (a.label()[:60], a.page), height=dp(42), bold=False, font_size=sp(13))
            b.halign = "left"
            b.bind(size=lambda inst, s: setattr(inst, "text_size", (s[0] - dp(20), None)))
            b.bind(on_release=lambda *_, aa=a: W.info(aa.label(), "[i]Page %s[/i]\n\n%s" % (aa.page, e(aa.text))))
            page.add(b)
