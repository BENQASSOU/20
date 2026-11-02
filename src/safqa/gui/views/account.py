"""Compte & équipe: Safqa Cloud account, company space, team, security, sync."""

import time
import traceback

import flet as ft

from ... import cloud
from ...log import log
from .. import ui
from ..app import page_body

ROLE_CHOICES = [("member", "Collaborateur (lecture et saisie)"), ("viewer", "Lecture seule (client, associé…)"),
                ("admin", "Administrateur (gère l'équipe)")]
ROLE_LABELS = {"owner": "Propriétaire", "admin": "Administrateur", "member": "Collaborateur", "viewer": "Lecture seule"}


def call(app, message, fn, *args):
    """Network call with a progress dialog. Returns (result, error_message)."""
    busy = ui.Busy(app.page, message)
    try:
        return fn(*args), None
    except cloud.CloudError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        log("ERROR cloud " + traceback.format_exc())
        return None, "Erreur inattendue : %s" % exc
    finally:
        busy.close()


# --------------------------------------------------------------------------
# Screen
# --------------------------------------------------------------------------

def view(app, params):
    acc = app.account
    if not acc.connected:
        return "Compte & équipe", [], None, page_body(signed_out(app))
    return "Compte & équipe", [], None, page_body(signed_in(app))


def signed_out(app):
    acc = app.account
    perks = [(ft.Icons.LOCK_OUTLINE, "Sauvegarde chiffrée", "Vos marchés sont chiffrés (AES-256) et sauvegardés en continu."),
             (ft.Icons.DEVICES, "Plusieurs appareils", "Téléphone du chef de chantier, tablette du gérant, PC du bureau."),
             (ft.Icons.GROUPS_OUTLINED, "Travail en équipe", "Invitez vos collaborateurs avec des droits adaptés."),
             (ft.Icons.AUTO_AWESOME, "IA Claude incluse", "Analyses et questions IA sans clé API, selon votre formule.")]
    c = [ft.Container(ft.Column([
        ft.Row([ft.Icon(ft.Icons.CLOUD_OUTLINED, color="#FFFFFF", size=30),
                ui.txt("Safqa Cloud", 20, ft.FontWeight.W_700, "#FFFFFF")]),
        ui.txt("Travaillez à plusieurs sur vos marchés, en toute sécurité.", 13.5, color="#CFE3EA")], spacing=6),
        padding=16, border_radius=16,
        gradient=ft.LinearGradient(colors=[ui.PRIMARY, "#13708F"], begin=ft.Alignment.TOP_LEFT,
                                   end=ft.Alignment.BOTTOM_RIGHT))]
    c.append(ui.card([ft.Row([ft.Container(ft.Icon(i, size=18, color=ui.PRIMARY), bgcolor=ui.TINT, border_radius=10, padding=7),
                              ft.Column([ui.bold(t, 14), ui.muted(s, 12.5)], spacing=2, expand=True, tight=True)])
                      for i, t, s in perks]))
    c.append(ft.Row([ui.primary_btn("Créer un compte", lambda e: signup_form(app), ft.Icons.PERSON_ADD, expand=True)]))
    c.append(ft.Row([ui.outline_btn("J'ai déjà un compte", lambda e: login_form(app), expand=True)]))
    c.append(ui.card([ui.kv("Serveur", acc.url or "non configuré"),
                      ui.text_btn("Modifier l'adresse du serveur", lambda e: server_form(app))]))
    c.append(ui.muted("Sans compte, Safqa fonctionne entièrement sur ce téléphone. Vos données ne quittent l'appareil "
                      "que si vous vous connectez. Mots de passe protégés (scrypt), connexion HTTPS obligatoire, "
                      "double authentification disponible.", 11.5))
    return c


def signed_in(app):
    acc = app.account
    me = acc.me
    user = me.get("user") or {}
    c = []
    if user.get("must_change_pw"):
        c.append(ui.card([ui.bold("Mot de passe temporaire", 14),
                          ui.muted("Choisissez votre propre mot de passe pour sécuriser votre compte."),
                          ui.primary_btn("Changer mon mot de passe", lambda e: password_form(app), ft.Icons.PASSWORD)],
                         accent=ui.WARNING))
    org = acc.org
    c.append(ui.card([
        ft.Row([ft.Container(ft.Icon(ft.Icons.ACCOUNT_CIRCLE, color=ui.PRIMARY, size=34)),
                ft.Column([ui.bold(user.get("name") or user.get("email") or "", 15), ui.muted(user.get("email") or "", 12.5)],
                          spacing=2, expand=True, tight=True)]),
        ui.kv("Espace entreprise", org["name"] if org else "aucun sur ce téléphone"),
        ui.kv("Votre rôle", ROLE_LABELS.get(acc.role, "-")),
        ui.kv("Formule", (org or {}).get("label") or "-"),
    ]))
    if not org:
        c.extend(choose_org(app))
        c.extend(security_section(app))
        return c
    c.append(sync_card(app))
    c.extend(team_section(app))
    c.extend(security_section(app))
    return c


# --------------------------------------------------------------------------
# Sign up / sign in
# --------------------------------------------------------------------------

def server_form(app):
    def save(v):
        url = (v["url"] or "").strip().rstrip("/")
        if url and not url.startswith("https://"):
            return "L'adresse doit commencer par https://"
        app.store.set("cloud_url", url)
        app.refresh()
    ui.form_dialog(app.page, "Serveur Safqa Cloud", [{"key": "url", "label": "Adresse", "value": app.account.url,
                                                     "hint": "https://safqa-cloud.onrender.com"}], save)


def _need_url(app):
    if not app.account.url:
        server_form(app)
        return True
    return False


def signup_form(app):
    if _need_url(app):
        return
    co = app.company()
    specs = [{"key": "name", "label": "Votre nom", "required": True},
             {"key": "email", "label": "E-mail professionnel", "required": True},
             {"key": "password", "label": "Mot de passe (10 caractères min., lettres et chiffres)", "type": "password",
              "required": True},
             {"key": "confirm", "label": "Confirmer le mot de passe", "type": "password", "required": True},
             {"key": "company", "label": "Nom de l'entreprise", "value": co.get("name") or "",
              "hint": "Laissez vide si vous rejoignez une équipe"},
             {"key": "terms", "label": "J'accepte les conditions d'utilisation et la politique de confidentialité "
                                       "(loi 09-08)", "type": "bool", "value": False}]

    def save(v):
        if v["password"] != v["confirm"]:
            return "Les mots de passe ne correspondent pas."
        if not v["terms"]:
            return "Acceptez les conditions pour créer votre compte."
        acc = app.account
        res, err = call(app, "Création du compte…", cloud.Cloud(acc.url).signup,
                        v["email"], v["password"], v["name"], v["company"] or "", cloud.device_name())
        if err:
            return err
        acc.save_login(acc.url, res)
        ui.snack(app.page, "Bienvenue sur Safqa Cloud")
        after_login(app)
    extra = ft.Row([ft.TextButton(content="Lire les conditions et la politique de confidentialité",
                                  url=app.account.url + "/confidentialite")], wrap=True)
    ui.form_dialog(app.page, "Créer un compte", specs, save, "Créer mon compte", extra=extra)


def login_form(app, email=""):
    if _need_url(app):
        return
    specs = [{"key": "email", "label": "E-mail", "required": True, "value": email},
             {"key": "password", "label": "Mot de passe", "type": "password", "required": True}]
    def save(v):
        acc = app.account
        res, err = call(app, "Connexion…", cloud.Cloud(acc.url).login, v["email"], v["password"], "",
                        cloud.device_name())
        if err == "mfa_required":
            ask_code(app, v)
            return None
        if err:
            return err
        acc.save_login(acc.url, res)
        after_login(app)
    extra = ft.Row([ft.TextButton(content="Mot de passe oublié ?", on_click=lambda e: forgot_form(app))])
    ui.form_dialog(app.page, "Connexion", specs, save, "Se connecter", extra=extra)


def ask_code(app, v):
    def save(c):
        acc = app.account
        res, err = call(app, "Vérification…", cloud.Cloud(acc.url).login, v["email"], v["password"], c["code"],
                        cloud.device_name())
        if err:
            return err
        acc.save_login(acc.url, res)
        after_login(app)
    ui.form_dialog(app.page, "Double authentification", [
        {"key": "code", "label": "Code à 6 chiffres de votre application", "type": "int", "required": True}],
        save, "Valider")


def forgot_form(app):
    acc = app.account

    def save(v):
        res, err = call(app, "Envoi…", cloud.Cloud(acc.url).reset_request, v["email"])
        if err:
            return err
        if not res.get("email"):
            ui.info(app.page, "Mot de passe oublié", res.get("message") or "")
            return None
        confirm_reset(app, v["email"])
    ui.form_dialog(app.page, "Mot de passe oublié", [{"key": "email", "label": "E-mail du compte", "required": True}],
                   save, "Recevoir un code")


def confirm_reset(app, email):
    acc = app.account

    def save(v):
        if v["new"] != v["confirm"]:
            return "Les mots de passe ne correspondent pas."
        _res, err = call(app, "Réinitialisation…", cloud.Cloud(acc.url).reset_confirm, email, str(v["code"]), v["new"])
        if err:
            return err
        ui.snack(app.page, "Mot de passe modifié : connectez-vous")
        login_form(app, email)
    ui.form_dialog(app.page, "Nouveau mot de passe", [
        {"key": "code", "label": "Code reçu par e-mail", "required": True},
        {"key": "new", "label": "Nouveau mot de passe", "type": "password", "required": True},
        {"key": "confirm", "label": "Confirmer", "type": "password", "required": True}], save, "Valider")


def after_login(app):
    acc = app.account
    orgs = acc.me.get("orgs") or []
    app.go("/module/compte")
    if (acc.me.get("user") or {}).get("must_change_pw"):
        password_form(app)
    elif len(orgs) == 1 and not acc.org_id:
        bind_org(app, orgs[0])
    else:
        app.refresh()


# --------------------------------------------------------------------------
# Company space on this phone
# --------------------------------------------------------------------------

def choose_org(app):
    acc = app.account
    c = [ui.section("Choisir l'espace entreprise de ce téléphone")]
    for o in acc.me.get("orgs") or []:
        c.append(ui.list_row(o["name"], "%s · %s" % (o.get("role_label") or o["role"], o.get("label") or ""),
                             icon=ft.Icons.APARTMENT, on_click=lambda e, o=o: bind_org(app, o)))
    c.append(ft.Row([ui.outline_btn("Créer un espace entreprise", lambda e: create_org_form(app), expand=True)]))
    c.append(ft.Row([ui.outline_btn("Rejoindre avec un code d'invitation", lambda e: join_form(app), expand=True)]))
    return c


def bind_org(app, org):
    """First use of a company space on this phone: send or receive the data."""
    acc = app.account
    store = app.store
    local_empty = store.is_empty()

    def go(mode):
        res, err = call(app, "Préparation de l'espace…", cloud.attach, store, acc, org["id"], mode,
                        app.dir + "/sauvegardes")
        if err:
            ui.info(app.page, "Safqa Cloud", err)
            return
        app.go("/module/compte")
        app.sync_now(manual=True)

    if local_empty:
        go("replace")
        return
    if org.get("role") == "viewer":
        ui.confirm(app.page, "Données de ce téléphone",
                   "Vous avez un accès en lecture seule : les données de l'espace « %s » remplaceront celles de ce "
                   "téléphone (une sauvegarde est conservée)." % org["name"], lambda: go("replace"), "Continuer",
                   danger=False)
        return
    holder = {}

    def pick(mode):
        def h(e):
            ui.close(app.page, holder.get("dlg"))
            go(mode)
        return h
    holder["dlg"] = ui.info(app.page, "Données de ce téléphone", ft.Column([
        ui.txt("Ce téléphone contient déjà des marchés. Que voulez-vous faire avec l'espace « %s » ?" % org["name"]),
        ui.list_row("Envoyer mes données dans l'espace", "Pour le premier appareil d'une nouvelle entreprise",
                    icon=ft.Icons.CLOUD_UPLOAD, on_click=pick("push")),
        ui.list_row("Utiliser les données de l'espace", "Remplace les données de ce téléphone (sauvegarde conservée)",
                    icon=ft.Icons.CLOUD_DOWNLOAD, on_click=pick("replace"))], tight=True, spacing=10))


def create_org_form(app):
    acc = app.account

    def save(v):
        res, err = call(app, "Création…", acc.client().create_org, v["name"], v.get("ice") or "")
        if err:
            return err
        acc.save_me(res)
        org = next((o for o in res["orgs"] if o["id"] == res["id"]), None)
        if org:
            bind_org(app, org)
    ui.form_dialog(app.page, "Nouvel espace entreprise", [
        {"key": "name", "label": "Raison sociale", "required": True, "value": app.company().get("name") or ""},
        {"key": "ice", "label": "ICE", "value": app.company().get("ice") or ""}], save, "Créer")


def join_form(app):
    acc = app.account

    def save(v):
        res, err = call(app, "Vérification du code…", acc.client().accept, v["code"])
        if err:
            return err
        acc.save_me(res)
        org = next((o for o in res["orgs"] if o["id"] == res["org_id"]), None)
        if org:
            bind_org(app, org)
    ui.form_dialog(app.page, "Rejoindre une entreprise", [
        {"key": "code", "label": "Code d'invitation", "required": True, "hint": "XXXX-XXXX-XXXX"}], save, "Rejoindre")


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------

def sync_card(app):
    st = app.sync_status
    pending = app.store.sync_pending()
    last = app.store.get("sync_last") or ""
    if st.get("state") == "running":
        icon, color, label = ft.Icons.CLOUD_SYNC, ui.INFO, "Synchronisation en cours…"
    elif st.get("error"):
        icon, color, label = ft.Icons.CLOUD_OFF, ui.DANGER, st["error"]
    elif pending:
        icon, color, label = ft.Icons.CLOUD_UPLOAD, ui.WARNING, "%d modification(s) en attente d'envoi" % pending
    else:
        icon, color, label = ft.Icons.CLOUD_DONE, ui.SUCCESS, "À jour"
    rows = [ft.Row([ft.Icon(icon, color=color), ui.txt(label, 14, ft.FontWeight.W_600, expand=True)]),
            ui.kv("Dernière synchronisation", _fmt_ts(last))]
    if app.account.role == "viewer":
        rows.append(ui.muted("Accès en lecture seule : vos modifications locales ne sont pas envoyées."))
    rows.append(ui.primary_btn("Synchroniser maintenant", lambda e: app.sync_now(manual=True), ft.Icons.SYNC))
    return ui.card(rows)


def _fmt_ts(ts):
    if not ts:
        return "jamais"
    try:
        return time.strftime("%d/%m/%Y à %H:%M", time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return ts


# --------------------------------------------------------------------------
# Team
# --------------------------------------------------------------------------

def team_section(app):
    acc = app.account
    box = ft.Column([ui.muted("Chargement de l'équipe…")], spacing=8)
    head = ui.section("Équipe", ui.text_btn("Inviter", lambda e: invite_form(app)) if acc.role in ("owner", "admin") else None)

    async def load():
        import asyncio
        try:
            res = await asyncio.to_thread(acc.client().members, acc.org_id)
        except cloud.CloudError as exc:
            box.controls = [ui.muted(str(exc))]
        else:
            box.controls = [member_row(app, m) for m in res.get("members", [])]
        try:
            box.update()
        except Exception:  # noqa: BLE001 - screen left
            pass
    if acc.url:
        app.task(load)
    return [head, ui.card([box])]


def member_row(app, m):
    acc = app.account
    items = []
    if acc.role in ("owner", "admin") and not m.get("me"):
        for code, label in ROLE_CHOICES + ([("owner", "Propriétaire")] if acc.role == "owner" else []):
            if code != m["role"]:
                items.append(ft.PopupMenuItem(content="Rôle : " + ROLE_LABELS[code],
                                              on_click=lambda e, c=code: member_action(app, m, "role", c)))
        if acc.role == "owner":
            items.append(ft.PopupMenuItem(content="Réinitialiser le mot de passe",
                                          on_click=lambda e: member_action(app, m, "reset")))
        items.append(ft.PopupMenuItem(content="Retirer de l'équipe", on_click=lambda e: member_action(app, m, "remove")))
    trailing = ft.PopupMenuButton(items=items, icon=ft.Icons.MORE_VERT) if items else None
    pills = [ui.pill(ROLE_LABELS.get(m["role"], m["role"]), ui.PRIMARY, ui.TINT)]
    if m.get("totp_enabled"):
        pills.append(ui.pill("2FA", ui.SUCCESS, "#ECFDF3"))
    return ui.list_row((m.get("name") or m["email"]) + (" (vous)" if m.get("me") else ""), m["email"],
                       icon=ft.Icons.PERSON_OUTLINE, pills=pills, trailing=trailing)


def member_action(app, m, action, role=None):
    acc = app.account
    client = acc.client()
    if action == "role":
        _r, err = call(app, "Mise à jour…", client.set_role, acc.org_id, m["id"], role)
        ui.snack(app.page, err or "Rôle mis à jour", error=bool(err))
        app.refresh()
    elif action == "reset":
        def go():
            res, err = call(app, "Réinitialisation…", client.reset_member_password, acc.org_id, m["id"])
            if err:
                ui.info(app.page, "Erreur", err)
                return
            ui.info(app.page, "Mot de passe temporaire",
                    ft.Column([ui.txt("Communiquez ce mot de passe à %s par un canal sûr. Il devra le changer à la "
                                      "prochaine connexion." % m["email"]),
                               ui.txt(res["temporary_password"], 20, ft.FontWeight.W_700, selectable=True)], tight=True))
        ui.confirm(app.page, "Réinitialiser", "Créer un mot de passe temporaire pour %s ?" % m["email"], go, "Réinitialiser")
    elif action == "remove":
        def go():
            _r, err = call(app, "Retrait…", client.remove_member, acc.org_id, m["id"])
            ui.snack(app.page, err or "Membre retiré", error=bool(err))
            app.refresh()
        ui.confirm(app.page, "Retirer", "%s n'aura plus accès aux données de l'entreprise." % m["email"], go, "Retirer")


def invite_form(app):
    acc = app.account

    def save(v):
        res, err = call(app, "Création de l'invitation…", acc.client().invite, acc.org_id, v["role"])
        if err:
            return err
        show_code(app, res)
    ui.form_dialog(app.page, "Inviter un collaborateur", [
        {"key": "role", "label": "Droits", "type": "select", "value": "member", "required": True,
         "options": ROLE_CHOICES}], save, "Créer le code")


def show_code(app, res):
    org = app.account.org or {}
    text = ("Rejoignez l'espace « %s » sur Safqa ERP : installez l'application, créez votre compte (Plus › Compte & "
            "équipe) puis « Rejoindre avec un code » : %s (valable %d jours)." % (org.get("name"), res["code"],
                                                                                 res.get("expires_days", 7)))

    async def share(e):
        try:
            await app.share.share_text(text)
        except Exception:  # noqa: BLE001 - fall back to the clipboard
            await app.clipboard.set(text)
            ui.snack(app.page, "Message copié")

    async def copy(e):
        await app.clipboard.set(res["code"])
        ui.snack(app.page, "Code copié")
    ui.info(app.page, "Code d'invitation", ft.Column([
        ui.txt(res["code"], 22, ft.FontWeight.W_700, ui.PRIMARY, selectable=True),
        ui.muted("Utilisable une seule fois, valable %d jours, droits : %s. Envoyez-le à votre collaborateur "
                 "(WhatsApp, e-mail…)." % (res.get("expires_days", 7), ROLE_LABELS.get(res["role"])))],
        tight=True, spacing=10),
        [ft.TextButton(content="Copier", icon=ft.Icons.COPY, on_click=copy),
         ft.TextButton(content="Envoyer", icon=ft.Icons.SHARE, on_click=share)])


# --------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------

def security_section(app):
    acc = app.account
    user = acc.me.get("user") or {}
    rows = [ui.list_row("Changer mon mot de passe", None, icon=ft.Icons.PASSWORD, on_click=lambda e: password_form(app)),
            ui.list_row("Double authentification", "Activée" if user.get("totp_enabled") else
                        "Recommandée : un code de votre téléphone en plus du mot de passe",
                        icon=ft.Icons.VERIFIED_USER_OUTLINED, icon_color=ui.SUCCESS if user.get("totp_enabled") else ui.WARNING,
                        on_click=lambda e: totp_flow(app))]
    if acc.org_id and acc.role in ("owner", "admin"):
        rows.append(ui.list_row("Rejoindre une autre entreprise", None, icon=ft.Icons.GROUP_ADD_OUTLINED,
                                on_click=lambda e: join_form(app)))
    if acc.org_id and acc.role == "owner":
        rows.append(ui.list_row("Exporter les données de l'entreprise", "Fichier complet (JSON) - loi 09-08",
                                icon=ft.Icons.DOWNLOAD_OUTLINED, on_click=lambda e: export_org(app)))
    rows.append(ui.list_row("Se déconnecter", "Les données restent sur ce téléphone", icon=ft.Icons.LOGOUT,
                            icon_color=ui.DANGER, on_click=lambda e: logout(app)))
    return [ui.section("Sécurité"), ui.card(rows)]


def export_org(app):
    acc = app.account
    data, err = call(app, "Export en cours…", acc.client().export, acc.org_id)
    if err:
        ui.info(app.page, "Export", err)
        return
    app.export(data, "safqa-export-%s.json" % time.strftime("%Y%m%d"), "application/json", "Export des données")


def password_form(app):
    acc = app.account

    def save(v):
        if v["new"] != v["confirm"]:
            return "Les mots de passe ne correspondent pas."
        _r, err = call(app, "Mise à jour…", acc.client().change_password, v["current"], v["new"])
        if err:
            return err
        me, _e = call(app, "Actualisation…", acc.client().me)
        if me:
            acc.save_me(me)
        ui.snack(app.page, "Mot de passe modifié. Vos autres appareils sont déconnectés.")
        app.refresh()
    ui.form_dialog(app.page, "Changer mon mot de passe", [
        {"key": "current", "label": "Mot de passe actuel (ou temporaire)", "type": "password", "required": True},
        {"key": "new", "label": "Nouveau mot de passe", "type": "password", "required": True},
        {"key": "confirm", "label": "Confirmer", "type": "password", "required": True}], save)


def totp_flow(app):
    acc = app.account
    if (acc.me.get("user") or {}).get("totp_enabled"):
        def save(v):
            _r, err = call(app, "Désactivation…", acc.client().totp_disable, v["password"], str(v["code"]))
            if err:
                return err
            _refresh_me(app)
        ui.form_dialog(app.page, "Désactiver la double authentification", [
            {"key": "password", "label": "Mot de passe", "type": "password", "required": True},
            {"key": "code", "label": "Code actuel", "required": True}], save, "Désactiver")
        return
    res, err = call(app, "Préparation…", acc.client().totp_setup)
    if err:
        ui.info(app.page, "Erreur", err)
        return
    secret = " ".join(res["secret"][i:i + 4] for i in range(0, len(res["secret"]), 4))

    def save(v):
        _r, err = call(app, "Activation…", acc.client().totp_enable, str(v["code"]))
        if err:
            return err
        ui.snack(app.page, "Double authentification activée")
        _refresh_me(app)
    ui.form_dialog(app.page, "Double authentification", [
        {"key": "code", "label": "Code à 6 chiffres affiché par l'application", "required": True}], save, "Activer",
        extra=ft.Column([ui.txt("1. Installez Google Authenticator ou Microsoft Authenticator.\n"
                                "2. Ajoutez un compte avec cette clé (saisie manuelle, basé sur l'heure) :", 13),
                         ui.txt(secret, 17, ft.FontWeight.W_700, ui.PRIMARY, selectable=True),
                         ui.txt("3. Tapez le code affiché.", 13)], tight=True, spacing=6))


def _refresh_me(app):
    me, _e = call(app, "Actualisation…", app.account.client().me)
    if me:
        app.account.save_me(me)
    app.refresh()


def logout(app):
    acc = app.account

    def go():
        try:
            acc.client().logout()
        except cloud.CloudError:
            pass
        acc.forget()
        ui.snack(app.page, "Déconnecté")
        app.refresh()
    pending = app.store.sync_pending()
    msg = "Vous pourrez vous reconnecter à tout moment."
    if pending:
        msg = "%d modification(s) n'ont pas encore été envoyées et resteront sur ce téléphone. " % pending + msg
    ui.confirm(app.page, "Se déconnecter", msg, go, "Se déconnecter")
