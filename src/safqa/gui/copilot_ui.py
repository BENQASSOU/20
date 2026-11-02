"""Safqa IA in the interface: recommendation cards, letter editor,
animated answers."""

import asyncio
import traceback

import flet as ft

from .. import copilot, erp
from ..log import log
from . import nav, ui

SEV_ICON = {"critique": ft.Icons.PRIORITY_HIGH, "élevé": ft.Icons.WARNING_AMBER_ROUNDED,
            "moyen": ft.Icons.LIGHTBULB_OUTLINE, "info": ft.Icons.INFO_OUTLINE}


# --------------------------------------------------------------------------
# Recommendations
# --------------------------------------------------------------------------

def run_action(app, ins, action):
    label, kind, arg = action
    pid = ins.get("pid")
    if kind == "route":
        app.go(arg)
    elif kind == "letter":
        letter_dialog(app, pid, arg)
    elif kind == "paid":
        d = app.store.get_row("decomptes", arg)
        if d:
            nav.mark_decompte_paid(app, d)


def insight_card(app, ins, show_project=True):
    color = ui.SEVERITY.get(ins["severity"], (ui.INFO,))[0]
    btns = []
    for i, a in enumerate(ins["actions"]):
        handler = (lambda e, a=a: run_action(app, ins, a))
        if i == 0:
            btns.append(ft.FilledButton(content=a[0], on_click=handler, height=36,
                                        style=ft.ButtonStyle(bgcolor=color, shape=ft.RoundedRectangleBorder(radius=10))))
        else:
            btns.append(ft.OutlinedButton(content=a[0], on_click=handler, height=36,
                                          style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))))
    detail = ins["detail"] if show_project else ins["detail"].split(" · ", 1)[-1]
    return ft.Container(
        ft.Column([
            ft.Row([ft.Container(ft.Icon(SEV_ICON.get(ins["severity"], ft.Icons.LIGHTBULB_OUTLINE), size=18,
                                         color=color), bgcolor=ui._tint(color), border_radius=10, padding=7),
                    ft.Column([ui.txt(ins["title"], 14, ft.FontWeight.W_600, max_lines=2),
                               ui.muted(detail, 12.5, max_lines=3)], spacing=2, expand=True, tight=True)],
                   vertical_alignment=ft.CrossAxisAlignment.START, spacing=10),
            ft.Row(btns, wrap=True, spacing=8, run_spacing=6)], spacing=10, tight=True),
        bgcolor="#FFFFFF", border_radius=14, padding=12, border=ft.Border(left=ft.BorderSide(4, color)),
        ink=True, on_click=lambda e: app.go("/marche/%s" % ins["pid"]) if ins.get("pid") else None,
        animate=ft.Animation(250, ft.AnimationCurve.EASE_OUT))


def insights_section(app, pid=None, limit=4):
    """'Safqa IA recommande' block, for the dashboard or one contract."""
    try:
        items = copilot.insights(app.store, app.company(), limit=limit, pid=pid)
    except Exception:  # noqa: BLE001 - never break a screen for a suggestion
        log("ERROR insights " + traceback.format_exc())
        return []
    head = ft.Row([ft.Container(ft.Icon(ft.Icons.AUTO_AWESOME, size=16, color="#FFFFFF"), padding=6,
                                border_radius=8, gradient=ft.LinearGradient(colors=[ui.ACCENT, "#D9480F"])),
                   ui.txt("Safqa IA recommande", 15, ft.FontWeight.W_700, expand=True),
                   ui.text_btn("Poser une question", lambda e: app.go("/module/assistant%s" % (
                       ("?pid=%s" % pid) if pid else "")))], spacing=8)
    if not items:
        return [head, ui.card([ui.muted("Aucune action urgente : vos délais, paiements et cautions sont à jour.")])]
    return [head] + [insight_card(app, i, show_project=pid is None) for i in items[:limit]]


# --------------------------------------------------------------------------
# Letters
# --------------------------------------------------------------------------

def letter_dialog(app, pid=None, kind=None):
    store = app.store
    projects = store.projects()
    if not projects:
        ui.info(app.page, "Courriers", "Créez d'abord un marché.")
        return
    ids = [p["id"] for p in projects]
    state = {"pid": pid if pid in ids else ids[0], "kind": kind or copilot.LETTERS[0][0]}
    body = ft.TextField(multiline=True, min_lines=12, max_lines=22, border_radius=10, text_size=13)
    note = ft.TextField(label="Précisions (facultatif)", hint_text="Motif, faits, références…", border_radius=10,
                        multiline=True, min_lines=1, max_lines=3)
    holder = {}

    def regenerate(e=None):
        s = erp.project_state(store, state["pid"])
        if not s:
            return
        subject, text = copilot.letter(state["kind"], s, app.company(), note=note.value or "")
        state["subject"] = subject
        body.value = text
        _upd(body)

    def pick_kind(e):
        state["kind"] = e.control.value
        regenerate()

    def pick_project(e):
        state["pid"] = int(e.control.value)
        regenerate()

    async def copy(e):
        try:
            await app.clipboard.set(body.value or "")
            ui.snack(app.page, "Courrier copié")
        except Exception as exc:  # noqa: BLE001
            ui.snack(app.page, "Copie impossible : %s" % exc, error=True)

    def pdf(e):
        data = copilot.letter_pdf(state.get("subject") or "Courrier", body.value or "", app.company())
        ui.close(app.page, holder.get("dlg"))
        app.export(data, "%s.pdf" % (state.get("subject") or "Courrier")[:60].replace("/", "-"), "application/pdf",
                   "Courrier")

    async def improve(e):
        client = app.ai_client()
        if not client.configured:
            ui.info(app.page, "Claude", "Renseignez une clé API dans Plus › Paramètres pour réécrire le courrier "
                                        "avec Claude. Le modèle actuel est déjà prêt à l'emploi.")
            return
        system = [{"type": "text", "text": "Tu es juriste en marchés publics de travaux au Maroc. Améliore ce courrier "
                                           "adressé au maître d'ouvrage : ton ferme et courtois, références exactes "
                                           "(CCAG-T, décret 2-16-344), sans inventer de faits. Réponds uniquement "
                                           "par le courrier final."}]
        msgs = [{"role": "user", "content": body.value or ""}]
        res = await app.run("Claude rédige le courrier…", client.message, system, msgs, 4000)
        if res and res[0].strip():
            body.value = res[0].strip()
            _upd(body)

    kinds = ft.Dropdown(label="Type de courrier", value=state["kind"], on_select=pick_kind, expand=True,
                        options=[ft.DropdownOption(key=k, text=lbl) for k, lbl in copilot.LETTERS])
    proj = ft.Dropdown(label="Marché", value=str(state["pid"]), on_select=pick_project, expand=True,
                       options=[ft.DropdownOption(key=str(p["id"]), text="%s - %s" % (p.get("ref") or "", (p.get("title") or "")[:38]))
                                for p in projects])
    note.on_blur = regenerate
    regenerate()
    content = ft.Column([ft.Row([kinds]), ft.Row([proj]), note,
                         ft.Row([ft.TextButton(content="Régénérer", icon=ft.Icons.REFRESH, on_click=regenerate),
                                 ft.TextButton(content="Améliorer avec Claude", icon=ft.Icons.AUTO_AWESOME,
                                               on_click=improve)], wrap=True, spacing=4),
                         body], tight=True, spacing=10)
    dlg = ft.AlertDialog(title=ui.txt("Courrier", 18, ft.FontWeight.W_700), scrollable=True,
                         content=ft.Container(content, width=520),
                         actions=[ft.TextButton(content="Fermer", on_click=lambda e: ui.close(app.page, dlg)),
                                  ft.OutlinedButton(content="Copier", icon=ft.Icons.COPY, on_click=copy),
                                  ft.FilledButton(content="PDF / Partager", icon=ft.Icons.SHARE, on_click=pdf)],
                         actions_alignment=ft.MainAxisAlignment.END)
    holder["dlg"] = dlg
    app.page.show_dialog(dlg)
    return dlg


def _upd(c):
    try:
        c.update()
    except Exception:  # noqa: BLE001 - not mounted yet
        pass


# --------------------------------------------------------------------------
# Typing effect for answers
# --------------------------------------------------------------------------

def animate_markdown(app, md, text, step=18, delay=0.012):
    """Reveal an answer progressively, like a live assistant."""
    async def go():
        try:
            for i in range(step, len(text) + step, step):
                md.value = text[:i]
                md.update()
                await asyncio.sleep(delay)
        except Exception:  # noqa: BLE001 - screen changed meanwhile
            pass
        md.value = text
    md.value = ""
    app.task(go)
