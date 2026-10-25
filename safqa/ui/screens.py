"""Home (projects list), AI assistant chat and account/subscription screens."""

import re
from datetime import date

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput
from kivy.utils import escape_markup

from .. import __version__, billing, config, regulation, tracking as tr
from ..ai import MODELS, ask
from ..analysis import articles_of
from ..textnum import fmt_dh
from . import widgets as W
from .widgets import C


class BaseScreen(Screen):
    title = "Safqa"
    back = False

    def __init__(self, **kw):
        super().__init__(**kw)
        self.root_box = BoxLayout(orientation="vertical")
        self.bar = W.AppBar(title=self.title, back=self.back)
        self.bar.bind(on_back=lambda *_: App.get_running_app().back())
        self.root_box.add_widget(self.bar)
        self.build_body()
        self.add_widget(self.root_box)

    def build_body(self):
        self.page = W.Page()
        self.root_box.add_widget(self.page)

    @property
    def app(self):
        return App.get_running_app()

    def load(self, **kw):
        self.refresh()

    def refresh(self):
        pass


# ==========================================================================
# Home
# ==========================================================================

class HomeScreen(BaseScreen):
    title = "Safqa"

    def refresh(self):
        app = self.app
        st = app.sub.status()
        self.bar.subtitle = "Marchés publics de travaux · " + st["label"]
        self.bar.set_actions([W.bar_action("+ Marché", self.new_project)])
        p = self.page
        p.clear()
        projects = app.store.projects()
        states = [app.project_state(pr["id"]) for pr in projects]
        crit = sum(1 for s in states for f in s["flags"] if f["severity"] == "critique")
        high = sum(1 for s in states for f in s["flags"] if f["severity"] == "élevé")

        if not st["active"]:
            c = W.Card(accent=C.warning)
            c.add_widget(W.WrapLabel(text="[b]%s[/b]" % st["message"]))
            c.add_widget(W.Muted(text="L'analyse hors-ligne et le suivi restent disponibles pour 1 marché."))
            c.add_widget(W.Btn(text="Voir les abonnements", on_release=lambda *_: self.app.go("account", root_tab=True)))
            p.add(c)
        elif st["trial"]:
            p.add(W.Muted(text=st["message"]))

        kpi = BoxLayout(size_hint_y=None, height=dp(84), spacing=dp(10))
        for value, label, color in ((len(projects), "marchés actifs", C.primary),
                                    (crit, "alertes critiques", C.danger),
                                    (high, "alertes élevées", C.warning)):
            c = W.Card(padding=(dp(12), dp(10)))
            c.height = dp(84)
            c.size_hint_y = None
            c.add_widget(Label(text=str(value), font_size=sp(24), bold=True, color=color,
                               size_hint_y=None, height=dp(34), halign="left", text_size=(dp(100), None)))
            c.add_widget(W.Muted(text=label))
            kpi.add_widget(c)
        p.add(kpi)

        if not projects:
            c = W.Card()
            c.add_widget(W.Title(text="Bienvenue sur Safqa"))
            c.add_widget(W.WrapLabel(text=(
                "1. Créez votre marché (référence, maître d'ouvrage, montant).\n"
                "2. Chargez le CPS, le marché ou le CCAG-T (PDF, Word).\n"
                "3. Safqa extrait obligations, délais et pénalités avec la référence de l'article.\n"
                "4. Suivez vos ordres de service, quantités, décomptes et réceptions : "
                "les risques et documents manquants sont signalés automatiquement.")))
            c.add_widget(W.Btn(text="Créer mon premier marché", on_release=lambda *_: self.new_project()))
            p.add(c)
            return

        p.add(W.section("Mes marchés"))
        for s in states:
            p.add(self._project_card(s))

    def _project_card(self, s):
        pr = s["project_full"]
        sched = tr.schedule(pr, s["orders"], s["receptions"])
        nb_crit = sum(1 for f in s["flags"] if f["severity"] == "critique")
        nb_high = sum(1 for f in s["flags"] if f["severity"] == "élevé")
        accent = C.danger if nb_crit else (C.warning if nb_high else C.success)
        c = W.Card(accent=accent)
        c.add_widget(W.WrapLabel(text="[b]%s[/b]" % escape_markup(pr.get("title") or "Sans titre"),
                                 font_size=sp(15.5)))
        c.add_widget(W.Muted(text=escape_markup("N° %s · %s" % (pr.get("ref") or "-", pr.get("owner") or "-"))))
        if sched["start"]:
            c.add_widget(W.ProgressBarH(value=sched["progress"],
                                        color=C.danger if sched["late_days"] else C.primary))
            if sched["late_days"]:
                txt = "[color=#D92D20][b]Retard : %d jours[/b][/color] · fin prévue %s" % (
                    sched["late_days"], tr.fmt_date(sched["end"]))
            elif sched.get("finished"):
                txt = "Travaux achevés le %s" % tr.fmt_date(sched["finished"])
            else:
                txt = "Fin contractuelle %s · reste %d j" % (tr.fmt_date(sched["end"]), sched["remaining"])
            c.add_widget(W.WrapLabel(text=txt, font_size=sp(13)))
        else:
            c.add_widget(W.Muted(text="Travaux non démarrés (pas d'OS de commencement)"))
        chips = []
        if nb_crit:
            chips.append(W.Chip(text="%d critique(s)" % nb_crit, fg=W.SEVERITY["critique"][0], bg=W.SEVERITY["critique"][1]))
        if nb_high:
            chips.append(W.Chip(text="%d élevée(s)" % nb_high, fg=W.SEVERITY["élevé"][0], bg=W.SEVERITY["élevé"][1]))
        chips.append(W.Chip(text="%d doc." % len(s["documents"])))
        if pr.get("amount_ttc"):
            chips.append(W.Chip(text=fmt_dh(pr["amount_ttc"], 0), bg=C.field, fg=C.text))
        c.add_widget(W.chip_row(chips))
        open_btn = W.ghost("Ouvrir le marché", height=dp(40))
        open_btn.bind(on_release=lambda *_: self.app.go("project", pid=pr["id"]))
        c.add_widget(open_btn)
        return c

    def new_project(self):
        ok, why = self.app.sub.can("project", len(self.app.store.projects()))
        if not ok:
            W.info("Limite atteinte", why + "\n\nArchivez un marché terminé ou passez à la formule supérieure.",
                   [W.Btn(text="Abonnements", on_release=lambda *_: self.app.go("account", root_tab=True))])
            return
        self.app.go("project_form", pid=None)


# ==========================================================================
# Assistant (chat)
# ==========================================================================

CITE_RE = re.compile(r"\[(A\d+(?:_\d+)?|A0|P\d+)\]")


class ChatScreen(BaseScreen):
    title = "Assistant IA"

    def build_body(self):
        top = BoxLayout(size_hint_y=None, height=dp(56), padding=(dp(12), dp(6)), spacing=dp(8))
        self.picker = W.spinner([], "Choisir un marché")
        self.picker.bind(text=lambda *_: self._on_pick())
        top.add_widget(self.picker)
        self.root_box.add_widget(top)
        self.page = W.Page()
        self.root_box.add_widget(self.page)
        bottom = BoxLayout(size_hint_y=None, height=dp(64), padding=(dp(10), dp(8)), spacing=dp(8))
        self.input = TextInput(hint_text="Ex. : Quel est le plafond des pénalités ?", multiline=False,
                               font_size=sp(15), padding=(dp(12), dp(14)), background_normal="",
                               background_active="", background_color=C.surface, foreground_color=C.text,
                               cursor_color=C.primary)
        self.input.bind(on_text_validate=lambda *_: self.send())
        bottom.add_widget(self.input)
        send = W.Btn(text="Envoyer", size_hint_x=None, width=dp(96), height=dp(48))
        send.bind(on_release=lambda *_: self.send())
        bottom.add_widget(send)
        self.root_box.add_widget(bottom)
        self._projects = {}
        self.pid = None

    def load(self, pid=None, **kw):
        projects = self.app.store.projects()
        self._projects = {"%s · %s" % (p.get("ref") or p["id"], (p.get("title") or "")[:40]): p["id"] for p in projects}
        self.picker.values = list(self._projects)
        if pid:
            for k, v in self._projects.items():
                if v == pid:
                    self.picker.text = k
        elif self.pid not in self._projects.values() and projects:
            self.picker.text = list(self._projects)[0]
        self.refresh()

    def _on_pick(self):
        self.pid = self._projects.get(self.picker.text)
        self.refresh()

    def refresh(self):
        st = self.app.sub
        self.bar.subtitle = "%d question(s) restante(s) ce mois" % st.remaining("ai_question")
        p = self.page
        p.clear()
        if not self.pid:
            p.add(W.Muted(text="Créez un marché et chargez ses pièces pour poser vos questions."))
            return
        hist = self.app.store.chat_history(self.pid)
        if not hist:
            c = W.Card(bg=C.tint)
            c.add_widget(W.WrapLabel(text="[b]Posez vos questions sur ce marché[/b]"))
            for q in ("Quelles sont mes obligations avant le démarrage des travaux ?",
                      "Comment sont calculées les pénalités de retard ?",
                      "Quels documents dois-je fournir pour la réception provisoire ?",
                      "Le maître d'ouvrage paie en retard : que puis-je réclamer ?"):
                b = W.ghost(q, height=dp(40), font_size=sp(12.5), bold=False)
                b.text_size = (None, None)
                b.halign = "left"
                b.shorten = True
                b.bind(on_release=lambda inst, qq=q: self.send(qq))
                c.add_widget(b)
            p.add(c)
        labels = self._article_labels()
        for h in hist:
            p.add(self._bubble(h["role"], h["content"], labels))
        Clock.schedule_once(lambda dt: setattr(p, "scroll_y", 0), 0.05)

    def _article_labels(self):
        out = {}
        for d in self.app.store.documents(self.pid):
            for a in articles_of(d):
                out.setdefault(a.key, (a, d))
        return out

    def _bubble(self, role, content, labels):
        user = role == "user"
        c = W.Card(bg=C.primary if user else C.surface, padding=(dp(14), dp(10)))
        text = escape_markup(content)
        if not user:
            text = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", text)
            text = re.sub(r"^#{1,4}\s*(.+)$", r"[b]\1[/b]", text, flags=re.M)

            def rep(m):
                key = m.group(1)
                if key in labels:
                    a, _d = labels[key]
                    short = "Préambule" if a.number == "Préambule" else ("Art. %s" % a.number)
                    return "[ref=%s][color=#075985][b]%s[/b][/color][/ref]" % (key, short)
                return m.group(0)
            text = CITE_RE.sub(rep, text)
        lbl = W.WrapLabel(text=text, color=(1, 1, 1, 1) if user else C.text, font_size=sp(14.5))
        lbl.bind(on_ref_press=lambda inst, ref: self._show_article(ref, labels))
        c.add_widget(lbl)
        row = BoxLayout(size_hint_y=None)
        c.bind(height=lambda *_: setattr(row, "height", c.height))
        if user:
            row.add_widget(Label(size_hint_x=0.15))
            row.add_widget(c)
        else:
            row.add_widget(c)
            row.add_widget(Label(size_hint_x=0.04))
        return row

    def _show_article(self, key, labels):
        if key in labels:
            a, d = labels[key]
            W.info(a.label(), "[i]%s · page %s[/i]\n\n%s" % (escape_markup(d.get("filename", "")), a.page,
                                                            escape_markup(a.text)))

    def send(self, text=None):
        q = (text or self.input.text).strip()
        if not q or not self.pid:
            return
        ok, why = self.app.sub.can("ai_question")
        if not ok:
            W.info("Assistant IA", why, [W.Btn(text="Abonnements",
                                               on_release=lambda *_: self.app.go("account", root_tab=True))])
            return
        client = self.app.ai_client()
        if not client.configured:
            W.info("Configuration requise", "Renseignez votre clé API ou le serveur Safqa dans l'onglet Compte.")
            return
        self.input.text = ""
        store = self.app.store
        history = store.chat_history(self.pid)
        store.add_chat(self.pid, "user", q)
        self.refresh()
        state = self.app.project_state(self.pid)
        docs = [("%s - %s" % (d.get("doc_type"), d.get("filename")), articles_of(d)) for d in state["documents"]]
        context = project_context(state)

        def work(progress):
            return ask(client, q, docs, context, history,
                       on_progress=lambda n: progress("%d caractères reçus" % n))

        def done(res):
            text, info = res
            store.add_chat(self.pid, "assistant", text)
            store.bump_usage("ai_question")
            self.refresh()

        def fail(msg):
            store.add_chat(self.pid, "assistant", "Erreur : " + msg)
            self.refresh()
        self.app.run_bg(work, done, busy_text="Safqa analyse votre question…", on_error=fail)


def project_context(state):
    p = state["project_full"]
    sched = tr.schedule(p, state["orders"], state["receptions"])
    fin = tr.financial_summary(p, state["items"], state["decomptes"], sched)
    lines = [
        "Marché : %s (n° %s), maître d'ouvrage : %s" % (p.get("title"), p.get("ref"), p.get("owner")),
        "Montant TTC : %s" % fmt_dh(p.get("amount_ttc")),
        "Date du jour : %s" % date.today().strftime("%d/%m/%Y"),
        "Début des travaux : %s ; fin contractuelle : %s ; jours d'arrêt : %s ; retard : %s jours" % (
            tr.fmt_date(sched["start"]), tr.fmt_date(sched["end"]), sched["suspended_days"], sched["late_days"]),
        "Travaux exécutés HT : %s (%d %%) ; payé TTC : %s ; impayé : %s ; pénalités estimées : %s" % (
            fmt_dh(fin["executed_ht"]), fin["progress"] * 100, fmt_dh(fin["paid_ttc"]),
            fmt_dh(fin["unpaid_ttc"]), fmt_dh(fin["penalties_est"])),
    ]
    for o in state["orders"]:
        lines.append("OS n° %s (%s) du %s %s" % (o.get("number"), tr.OS_LABELS.get(o.get("kind")),
                                                 tr.fmt_date(o.get("date")), o.get("note") or ""))
    for r in state["receptions"]:
        lines.append("Réception %s le %s%s" % (r.get("kind"), tr.fmt_date(r.get("date")),
                                               " avec réserves" if r.get("with_reserves") else ""))
    for f in state["flags"][:12]:
        lines.append("Alerte (%s) : %s - %s" % (f["severity"], f["title"], f["detail"]))
    return "\n".join(lines)


# ==========================================================================
# Account / subscription
# ==========================================================================

class AccountScreen(BaseScreen):
    title = "Compte & abonnement"

    def refresh(self):
        app = self.app
        st = app.sub.status()
        store = app.store
        self.bar.subtitle = st["label"]
        p = self.page
        p.clear()

        c = W.Card(accent=C.success if st["active"] else C.warning)
        c.add_widget(W.Title(text="Formule : %s" % st["label"]))
        c.add_widget(W.WrapLabel(text=st["message"]))
        lim = st["limits"]
        c.add_widget(W.kv_row("Analyses IA ce mois", "%d / %d" % (store.usage("ai_analysis"), lim["ai_analyses"])))
        c.add_widget(W.kv_row("Questions IA ce mois", "%d / %d" % (store.usage("ai_question"), lim["ai_questions"])))
        c.add_widget(W.kv_row("Marchés actifs", "%d / %s" % (len(store.projects()),
                                                             "illimité" if lim["max_projects"] >= 1000 else lim["max_projects"])))
        p.add(c)

        p.add(W.section("Abonnements"))
        for code, plan in billing.PLANS.items():
            pc = W.Card(accent=C.accent if code == "PRO" else None)
            pc.add_widget(W.WrapLabel(text="[b]%s[/b]   [color=#0B4F6C][b]%d DH[/b][/color] / mois" % (
                plan["name"], plan["price_dh"]), font_size=sp(16)))
            pc.add_widget(W.Muted(text=plan["pitch"]))
            pc.add_widget(W.WrapLabel(text="\n".join("•  " + f for f in plan["features"]), font_size=sp(13.5)))
            b = W.ghost("Souscrire - %s" % plan["name"], height=dp(40))
            b.bind(on_release=lambda inst, pl=plan: self.subscribe(pl))
            pc.add_widget(b)
            p.add(pc)

        kc = W.Card()
        kc.add_widget(W.Title(text="Clé d'activation"))
        self.key_field = W.Field(label="Clé reçue après paiement", hint="SAFQA-PRO-20271231-SOCIETE-XXXXXXXXXX",
                                 text=store.get("license_key", "") or "")
        kc.add_widget(self.key_field)
        b = W.Btn(text="Activer")
        b.bind(on_release=lambda *_: self.activate())
        kc.add_widget(b)
        p.add(kc)

        ac = W.Card()
        ac.add_widget(W.Title(text="Intelligence artificielle"))
        mode = store.get("ai_mode", "proxy" if config.DEFAULT_PROXY_URL else "direct")
        ac.add_widget(W.Muted(text="Mode « Serveur Safqa » : l'IA est incluse dans l'abonnement. "
                                   "Mode « Clé API » : utilisez votre propre clé Anthropic."))
        self.mode = W.spinner(["Serveur Safqa", "Clé API personnelle"],
                              "Serveur Safqa" if mode == "proxy" else "Clé API personnelle")
        ac.add_widget(self.mode)
        self.proxy_field = W.Field(label="Adresse du serveur Safqa", hint="https://api.votre-domaine.ma",
                                   text=store.get("proxy_url", config.DEFAULT_PROXY_URL) or "")
        ac.add_widget(self.proxy_field)
        self.api_field = W.Field(label="Clé API Anthropic", hint="sk-ant-…", password=True,
                                 text=store.get("api_key", "") or "")
        ac.add_widget(self.api_field)
        model = store.get("ai_model", MODELS[0][0])
        self.model = W.spinner([m[1] for m in MODELS], dict(MODELS).get(model, MODELS[0][1]))
        ac.add_widget(W.Muted(text="Modèle"))
        ac.add_widget(self.model)
        b = W.Btn(text="Enregistrer les paramètres IA")
        b.bind(on_release=lambda *_: self.save_ai())
        ac.add_widget(b)
        p.add(ac)

        about = W.Card()
        about.add_widget(W.Title(text="À propos"))
        about.add_widget(W.WrapLabel(text="Safqa %s - assistant des marchés publics de travaux au Maroc." % __version__))
        about.add_widget(W.Muted(text="Textes de référence : " + " ; ".join(regulation.TEXTS[k] for k in
                                                                             ("DECRET_MP", "CCAG_T", "DELAIS_PAIEMENT"))))
        about.add_widget(W.Muted(text=regulation.DISCLAIMER))
        about.add_widget(W.Muted(text="Vos documents restent sur votre téléphone. Avec l'IA, le texte des pièces "
                                      "est envoyé au service d'IA uniquement au moment de l'analyse."))
        p.add(about)

    def subscribe(self, plan):
        W.info("Souscrire - %s (%d DH/mois)" % (plan["name"], plan["price_dh"]),
               "%s\n\nWhatsApp : %s\nE-mail : %s" % (config.PAYMENT_INFO, config.SALES_WHATSAPP, config.SALES_EMAIL),
               [W.ghost("WhatsApp", on_release=lambda *_: _open_whatsapp(plan))])

    def activate(self):
        ok, msg = self.app.sub.activate(self.key_field.text)
        W.toast(msg)
        if ok:
            self.refresh()

    def save_ai(self):
        s = self.app.store
        s.set("ai_mode", "proxy" if self.mode.text == "Serveur Safqa" else "direct")
        s.set("proxy_url", self.proxy_field.text.strip())
        s.set("api_key", self.api_field.text.strip())
        inv = {label: mid for mid, label in MODELS}
        s.set("ai_model", inv.get(self.model.text, MODELS[0][0]))
        W.toast("Paramètres enregistrés")


def _open_whatsapp(plan):
    from urllib.parse import quote
    from ..platform_android import open_url
    num = re.sub(r"\D", "", config.SALES_WHATSAPP)
    open_url("https://wa.me/%s?text=%s" % (num, quote("Bonjour, je souhaite souscrire à Safqa %s." % plan["name"])))
