"""Reusable Flet components for Safqa ERP."""

from datetime import date, datetime

import flet as ft

from ..textnum import fmt_dh, parse_decimal
from ..tracking import fmt_date, parse_date

PRIMARY = "#0B4F6C"
PRIMARY_DARK = "#083B51"
ACCENT = "#E8A33D"
BG = "#F3F5F8"
SURFACE = "#FFFFFF"
BORDER = "#E4E7EC"
TEXT = "#101828"
MUTED = "#667085"
SUCCESS = "#12B76A"
INFO = "#2E90FA"
WARNING = "#F79009"
DANGER = "#D92D20"
TINT = "#E6F1F5"

SEVERITY = {
    "critique": ("#B42318", "#FEE4E2", "Critique"),
    "élevé": ("#C4320A", "#FFEAD5", "Élevé"),
    "moyen": ("#B54708", "#FEF0C7", "Moyen"),
    "info": ("#175CD3", "#D1E9FF", "Info"),
}
STATUS_COLORS = {
    "en_cours": INFO, "suspendu": WARNING, "receptionne": SUCCESS, "clos": MUTED,
    "veille": MUTED, "etude": INFO, "soumis": ACCENT, "gagne": SUCCESS, "perdu": DANGER, "abandonne": MUTED,
    "engage": MUTED, "facture": WARNING, "paye": SUCCESS,
    "active": INFO, "mainlevee_demandee": WARNING, "liberee": SUCCESS,
}


def money(v, dec=2):
    return fmt_dh(v, dec)


def short_money(v):
    v = v or 0
    a = abs(v)
    if a >= 1e6:
        return ("%.2f M DH" % (v / 1e6)).replace(".", ",")
    if a >= 1e4:
        return ("%.0f k DH" % (v / 1e3))
    return fmt_dh(v, 0)


def pct(v, dec=0):
    return ("%." + str(dec) + "f %%") % (v or 0)


def num(text):
    if text in (None, ""):
        return None
    return parse_decimal(str(text))


def txt(value, size=14, weight=None, color=None, italic=False, max_lines=None, selectable=False, **kw):
    return ft.Text(value if value is not None else "", size=size, weight=weight, color=color or TEXT,
                   italic=italic, max_lines=max_lines,
                   overflow=ft.TextOverflow.ELLIPSIS if max_lines else None, selectable=selectable, **kw)


def muted(value, size=12.5, color=MUTED, **kw):
    return txt(value, size=size, color=color, **kw)


def bold(value, size=15, color=None, **kw):
    return txt(value, size=size, weight=ft.FontWeight.W_600, color=color, **kw)


def card(controls, padding=14, accent=None, on_click=None, bgcolor=SURFACE, spacing=8, margin=None):
    body = ft.Column(controls, spacing=spacing, tight=True)
    border = ft.Border.all(1, BORDER)
    if accent:
        border = ft.Border(left=ft.BorderSide(4, accent), top=ft.BorderSide(1, BORDER),
                           right=ft.BorderSide(1, BORDER), bottom=ft.BorderSide(1, BORDER))
    return ft.Container(content=body, padding=padding, bgcolor=bgcolor, border_radius=14, border=border,
                        on_click=on_click, ink=on_click is not None, margin=margin)


def section(title, action=None):
    row = [txt(title, 16, ft.FontWeight.W_700, PRIMARY_DARK, expand=True)]
    if action:
        row.append(action)
    return ft.Container(ft.Row(row, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding(2, 10, 2, 0))


def pill(label, fg=PRIMARY, bg=TINT, size=11.5):
    return ft.Container(txt(label, size, ft.FontWeight.W_600, fg), bgcolor=bg, border_radius=20,
                        padding=ft.Padding(9, 3, 9, 3))


def status_pill(code, label):
    color = STATUS_COLORS.get(code, MUTED)
    return pill(label, color, _tint(color))


def sev_pill(severity):
    fg, bg, lbl = SEVERITY.get(severity, (MUTED, "#F2F4F7", severity))
    return pill(lbl, fg, bg)


def cite_pill(label, page=None):
    t = label or ""
    if len(t) > 40:
        t = t[:38] + "…"
    if page:
        t += " · p.%s" % page
    return pill(t, "#075985", "#E0F2FE", 11)


def _tint(hexcolor, alpha=0.14):
    c = hexcolor.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (int(255 - (255 - x) * alpha) for x in (r, g, b))
    return "#%02X%02X%02X" % (r, g, b)


def pills_row(items):
    return ft.Row([i for i in items if i is not None], spacing=6, wrap=True, run_spacing=6)


def kv(key, value, color=None, strong=False):
    return ft.Row([muted(key, 13, expand=True),
                   txt(value, 13.5, ft.FontWeight.W_600 if strong else None, color, text_align=ft.TextAlign.RIGHT)],
                  vertical_alignment=ft.CrossAxisAlignment.START)


def progress(value, color=PRIMARY, height=7):
    return ft.ProgressBar(value=max(0.0, min(1.0, value or 0)), color=color, bgcolor="#E4E7EC",
                          bar_height=height, border_radius=6)


def kpi(label, value, icon, color=PRIMARY, sub=None, on_click=None):
    head = ft.Row([ft.Container(ft.Icon(icon, size=18, color=color), bgcolor=_tint(color), border_radius=10,
                                padding=7),
                   muted(label, 12, expand=True, max_lines=2)], spacing=8)
    items = [head, txt(value, 18, ft.FontWeight.W_700, TEXT, max_lines=1)]
    if sub:
        items.append(muted(sub, 11.5, max_lines=1))
    return ft.Container(card(items, padding=12, on_click=on_click, spacing=6), col={"xs": 6, "md": 4, "lg": 2})


def kpi_grid(items):
    return ft.ResponsiveRow(items, spacing=10, run_spacing=10)


def empty(message, icon=ft.Icons.INBOX_OUTLINED, action=None):
    items = [ft.Icon(icon, size=40, color="#98A2B3"), muted(message, 13.5, text_align=ft.TextAlign.CENTER)]
    if action:
        items.append(action)
    return ft.Container(ft.Column(items, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                        padding=30, alignment=ft.Alignment.CENTER)


def primary_btn(label, on_click, icon=None, expand=False):
    return ft.FilledButton(content=label, icon=icon, on_click=on_click, expand=expand,
                           style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))


def tonal_btn(label, on_click, icon=None, expand=False):
    return ft.FilledTonalButton(content=label, icon=icon, on_click=on_click, expand=expand,
                                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))


def outline_btn(label, on_click, icon=None, expand=False, color=None):
    return ft.OutlinedButton(content=label, icon=icon, on_click=on_click, expand=expand,
                             style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10), color=color))


def text_btn(label, on_click, icon=None, color=None):
    return ft.TextButton(content=label, icon=icon, on_click=on_click, style=ft.ButtonStyle(color=color))


# --------------------------------------------------------------------------
# Charts (pure Flet containers, no extension needed)
# --------------------------------------------------------------------------

def bar_chart(series, colors, legend, height=150, fmt=short_money):
    """Grouped vertical bars. series: [(label, v1, v2, ...)]."""
    if not series:
        return empty("Pas encore de données")
    vmax = max([max(s[1:]) for s in series] + [1])
    groups = []
    for s in series:
        bars = []
        for v, c in zip(s[1:], colors):
            h = max(2, height * (v / vmax)) if v > 0 else 2
            bars.append(ft.Container(width=8, height=h, bgcolor=c if v > 0 else "#EAECF0",
                                     border_radius=ft.BorderRadius(3, 3, 0, 0), tooltip=fmt(v)))
        groups.append(ft.Column([ft.Row(bars, spacing=2, vertical_alignment=ft.CrossAxisAlignment.END,
                                        alignment=ft.MainAxisAlignment.CENTER),
                                 txt(s[0].split(" ")[0], 9.5, color=MUTED)],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3, expand=True,
                                alignment=ft.MainAxisAlignment.END))
    leg = ft.Row([ft.Row([ft.Container(width=10, height=10, bgcolor=c, border_radius=3), muted(n, 11.5)], spacing=5)
                  for c, n in zip(colors, legend)], spacing=14)
    return ft.Column([ft.Container(ft.Row(groups, spacing=2, vertical_alignment=ft.CrossAxisAlignment.END),
                                   height=height + 22), leg], spacing=6)


def hbar(label, value, total, color=PRIMARY, right=None):
    ratio = (value / total) if total else 0
    return ft.Column([ft.Row([txt(label, 13, expand=True, max_lines=1), muted(right or short_money(value), 12.5)]),
                      progress(ratio, color, 8)], spacing=4)


def budget_bar(label, actual, budget):
    ratio = (actual / budget) if budget else (1.0 if actual else 0)
    color = DANGER if ratio > 1.0 else (WARNING if ratio > 0.9 else SUCCESS)
    return ft.Column([ft.Row([txt(label, 13, expand=True), muted("%s / %s" % (short_money(actual), short_money(budget)), 12)]),
                      progress(min(ratio, 1.0), color, 8),
                      muted(("Consommé %d %%" % (ratio * 100)) if budget else "Hors budget", 11,
                            color=color if ratio > 1 else MUTED)], spacing=3)


def ring(value, label, color=PRIMARY, size=74):
    return ft.Column([ft.Stack([ft.ProgressRing(value=max(0.0, min(1.0, value or 0)), stroke_width=8, color=color,
                                                bgcolor="#E4E7EC", width=size, height=size),
                                ft.Container(txt("%d%%" % ((value or 0) * 100), 15, ft.FontWeight.W_700), width=size,
                                             height=size, alignment=ft.Alignment.CENTER)]),
                      muted(label, 11.5, text_align=ft.TextAlign.CENTER)],
                     horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4)


# --------------------------------------------------------------------------
# Forms
# --------------------------------------------------------------------------

class Form:
    """Builds form fields from specs and returns typed values.

    spec keys: key, label, type (text|multiline|number|int|date|select|bool|password),
    value, options [(key, label)], required, hint, suffix."""

    def __init__(self, page, specs):
        self.page = page
        self.specs = specs
        self.controls = {}
        self.widgets = []
        for s in specs:
            self.widgets.append(self._build(s))

    def _build(self, s):
        t = s.get("type", "text")
        value = s.get("value")
        label = s["label"] + (" *" if s.get("required") else "")
        if t == "select":
            opts = [ft.DropdownOption(key=str(k), text=lbl) for k, lbl in s.get("options", [])]
            c = ft.Dropdown(label=label, options=opts, value=None if value in (None, "") else str(value),
                            expand=True, enable_filter=len(opts) > 8, editable=len(opts) > 8, menu_height=320)
            self.controls[s["key"]] = c
            return ft.Row([c])
        if t == "bool":
            c = ft.Switch(label=s["label"], value=bool(value))
            self.controls[s["key"]] = c
            return c
        if t == "date":
            c = ft.TextField(label=label, value=fmt_date(value) if value else "", hint_text="JJ/MM/AAAA",
                             keyboard_type=ft.KeyboardType.DATETIME, border_radius=10, expand=True)

            def open_picker(e, field=c):
                current = parse_date(field.value) or date.today()

                def picked(ev):
                    if ev.control.value:
                        field.value = ev.control.value.strftime("%d/%m/%Y")
                        field.update()
                self.page.show_dialog(ft.DatePicker(value=datetime(current.year, current.month, current.day),
                                                    first_date=datetime(2000, 1, 1), last_date=datetime(2100, 12, 31),
                                                    on_change=picked))
            c.suffix_icon = None
            self.controls[s["key"]] = c
            return ft.Row([c, ft.IconButton(ft.Icons.CALENDAR_MONTH, on_click=open_picker, icon_color=PRIMARY)],
                          spacing=4)
        kb = None
        if t in ("number", "int"):
            kb = ft.KeyboardType.NUMBER
        if t == "number" and isinstance(value, (int, float)):
            value = ("%.2f" % value).rstrip("0").rstrip(".").replace(".", ",")
        c = ft.TextField(label=label, value="" if value is None else str(value), hint_text=s.get("hint"),
                         multiline=t == "multiline", min_lines=3 if t == "multiline" else None,
                         max_lines=6 if t == "multiline" else 1, keyboard_type=kb, border_radius=10,
                         password=t == "password", can_reveal_password=t == "password",
                         suffix=s.get("suffix"), expand=True)
        self.controls[s["key"]] = c
        return ft.Row([c])

    def values(self):
        """Returns (values, error)."""
        out = {}
        for s in self.specs:
            c = self.controls[s["key"]]
            t = s.get("type", "text")
            if t == "bool":
                out[s["key"]] = bool(c.value)
                continue
            raw = (c.value or "").strip() if isinstance(c.value, str) or c.value is None else c.value
            if s.get("required") and raw in ("", None):
                return None, "Champ obligatoire : %s" % s["label"]
            if t in ("number", "int"):
                if raw in ("", None):
                    out[s["key"]] = None
                    continue
                v = num(raw)
                if v is None:
                    return None, "Nombre invalide : %s" % s["label"]
                out[s["key"]] = int(v) if t == "int" else v
            elif t == "date":
                if not raw:
                    out[s["key"]] = None
                    continue
                d = parse_date(raw)
                if not d:
                    return None, "Date invalide (JJ/MM/AAAA) : %s" % s["label"]
                out[s["key"]] = d.isoformat()
            elif t == "select":
                key = raw if raw not in ("", None) else None
                # keys are ints for foreign keys
                if key is not None and s.get("int_keys"):
                    key = int(key)
                out[s["key"]] = key
            else:
                out[s["key"]] = raw
        return out, None


def form_dialog(page, title, specs, on_save, save_label="Enregistrer", extra=None, on_delete=None):
    """Modal form. on_save(values) may return an error string to keep it open."""
    form = Form(page, specs)
    err = txt("", 13, color=DANGER)
    controls = list(form.widgets)
    if extra:
        controls.append(extra)
    controls.append(err)

    def save(e):
        vals, problem = form.values()
        if problem:
            err.value = problem
            err.update()
            return
        res = on_save(vals)
        if isinstance(res, str) and res:
            err.value = res
            err.update()
            return
        page.pop_dialog()

    actions = []
    if on_delete:
        actions.append(ft.TextButton(content="Supprimer", style=ft.ButtonStyle(color=DANGER),
                                     on_click=lambda e: (page.pop_dialog(), confirm(page, "Supprimer", "Confirmer la suppression ?", on_delete))))
    actions += [ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ft.FilledButton(content=save_label, on_click=save)]
    dlg = ft.AlertDialog(title=txt(title, 18, ft.FontWeight.W_700), scrollable=True,
                         content=ft.Container(ft.Column(controls, tight=True, spacing=12), width=440),
                         actions=actions, actions_alignment=ft.MainAxisAlignment.END)
    page.show_dialog(dlg)
    return form


def confirm(page, title, message, on_yes, yes="Confirmer", danger=True):
    def ok(e):
        page.pop_dialog()
        on_yes()
    page.show_dialog(ft.AlertDialog(title=txt(title, 18, ft.FontWeight.W_700), content=txt(message),
                                    actions=[ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                                             ft.FilledButton(content=yes, on_click=ok,
                                                             style=ft.ButtonStyle(bgcolor=DANGER if danger else None))]))


def info(page, title, content, actions=None):
    body = content if isinstance(content, ft.Control) else txt(content, selectable=True)
    page.show_dialog(ft.AlertDialog(title=txt(title, 18, ft.FontWeight.W_700), scrollable=True,
                                    content=ft.Container(body, width=440),
                                    actions=(actions or []) + [ft.TextButton(content="Fermer",
                                                                             on_click=lambda e: page.pop_dialog())]))


def snack(page, message, error=False):
    page.show_dialog(ft.SnackBar(content=txt(message, 14, color="#FFFFFF"), bgcolor=DANGER if error else "#1D2939",
                                 behavior=ft.SnackBarBehavior.FLOATING, duration=3500))


class Busy:
    """Modal progress dialog for long operations."""

    def __init__(self, page, message):
        self.page = page
        self.label = txt(message, 15, ft.FontWeight.W_600)
        self.sub = muted("", 12.5)
        self.dlg = ft.AlertDialog(modal=True, content=ft.Container(ft.Row([
            ft.ProgressRing(width=28, height=28, stroke_width=3),
            ft.Column([self.label, self.sub], tight=True, spacing=4, expand=True)], spacing=16), width=380))
        page.show_dialog(self.dlg)

    def set(self, sub):
        self.sub.value = sub
        try:
            self.sub.update()
        except Exception:  # noqa: BLE001 - dialog may be closing
            pass

    def close(self):
        try:
            self.page.pop_dialog()
        except Exception:  # noqa: BLE001
            pass


def list_row(title, subtitle=None, right=None, right_sub=None, icon=None, icon_color=PRIMARY, on_click=None,
             pills=None):
    left = []
    if icon:
        left.append(ft.Container(ft.Icon(icon, size=20, color=icon_color), bgcolor=_tint(icon_color),
                                 border_radius=10, padding=8))
    mid = [txt(title, 14, ft.FontWeight.W_600, max_lines=2)]
    if subtitle:
        mid.append(muted(subtitle, 12.5, max_lines=2))
    if pills:
        mid.append(pills_row(pills))
    cols = left + [ft.Column(mid, spacing=3, expand=True, tight=True)]
    if right is not None:
        r = [txt(right, 13.5, ft.FontWeight.W_600, text_align=ft.TextAlign.RIGHT)]
        if right_sub:
            r.append(muted(right_sub, 11.5, text_align=ft.TextAlign.RIGHT))
        cols.append(ft.Column(r, spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, tight=True))
    return ft.Container(ft.Row(cols, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding(12, 10, 12, 10), bgcolor=SURFACE, border_radius=12,
                        border=ft.Border.all(1, BORDER), on_click=on_click, ink=on_click is not None)


def days_label(days):
    if days is None:
        return ""
    if days < 0:
        return "En retard de %d j" % -days
    if days == 0:
        return "Aujourd'hui"
    if days == 1:
        return "Demain"
    return "Dans %d j" % days
