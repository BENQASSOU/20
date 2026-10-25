"""Reusable widgets and dialogs (styled in theme.kv)."""

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ColorProperty, NumericProperty,
                             StringProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.utils import get_color_from_hex as hx


class C:
    primary = hx("#0B4F6C")
    primary_dark = hx("#083B51")
    accent = hx("#E8A33D")
    bg = hx("#F3F5F8")
    surface = hx("#FFFFFF")
    field = hx("#F2F4F7")
    border = hx("#E4E7EC")
    track = hx("#E4E7EC")
    text = hx("#101828")
    muted = hx("#667085")
    success = hx("#12B76A")
    info = hx("#2E90FA")
    warning = hx("#F79009")
    danger = hx("#D92D20")
    high = hx("#F04438")
    tint = hx("#E6F1F5")
    cite_bg = hx("#E0F2FE")
    cite_fg = hx("#075985")


SEVERITY = {
    "critique": (hx("#B42318"), hx("#FEE4E2"), "Critique"),
    "élevé": (hx("#C4320A"), hx("#FFEAD5"), "Élevé"),
    "moyen": (hx("#B54708"), hx("#FEF0C7"), "Moyen"),
    "info": (hx("#175CD3"), hx("#D1E9FF"), "Info"),
}


class WrapLabel(Label):
    pass


class Title(WrapLabel):
    pass


class Muted(WrapLabel):
    pass


class Card(BoxLayout):
    bg = ColorProperty(C.surface)
    accent = ColorProperty(None, allownone=True)


class Btn(Button):
    bg = ColorProperty(C.primary)
    fg = ColorProperty([1, 1, 1, 1])
    line = ColorProperty(None, allownone=True)


def ghost(text, **kw):
    kw.setdefault("bg", C.surface)
    kw.setdefault("fg", C.primary)
    kw.setdefault("line", C.border)
    return Btn(text=text, **kw)


def danger_btn(text, **kw):
    return Btn(text=text, bg=hx("#FEE4E2"), fg=hx("#B42318"), **kw)


class Chip(Label):
    bg = ColorProperty(C.tint)
    fg = ColorProperty(C.primary)


def sev_chip(severity):
    fg, bg, label = SEVERITY.get(severity, (C.muted, C.field, severity))
    return Chip(text=label, fg=fg, bg=bg)


def cite_chip(label, page=None):
    t = label or ""
    if len(t) > 38:
        t = t[:36] + "…"
    if page:
        t += "  ·  p.%s" % page
    return Chip(text=t, bg=C.cite_bg, fg=C.cite_fg)


class Field(BoxLayout):
    label = StringProperty("")
    text = StringProperty("")
    hint = StringProperty("")
    multiline = BooleanProperty(False)
    password = BooleanProperty(False)
    input_filter = StringProperty(None, allownone=True)


class ProgressBarH(BoxLayout):
    value = NumericProperty(0)
    color = ColorProperty(C.primary)


class AppBar(BoxLayout):
    title = StringProperty("")
    subtitle = StringProperty("")
    back = BooleanProperty(False)
    __events__ = ("on_back",)

    def on_back(self, *_):
        pass

    def set_actions(self, buttons):
        box = self.ids.actions
        box.clear_widgets()
        for b in buttons:
            box.add_widget(b)


def bar_action(text, callback):
    b = Btn(text=text, bg=(1, 1, 1, 0.16), fg=(1, 1, 1, 1), size_hint=(None, None),
            height=dp(36), font_size=sp(13))
    b.bind(texture_size=lambda inst, ts: setattr(inst, "width", ts[0] + dp(22)))
    b.bind(on_release=lambda *_: callback())
    return b


class NavBar(BoxLayout):
    current = StringProperty("")
    __events__ = ("on_select",)

    def setup(self, tabs):
        self.clear_widgets()
        self._btns = {}
        for key, label in tabs:
            b = Btn(text=label, bg=(0, 0, 0, 0), fg=C.muted, height=dp(60), font_size=sp(13))
            b.bind(on_release=lambda inst, k=key: self.dispatch("on_select", k))
            self._btns[key] = b
            self.add_widget(b)

    def on_current(self, *_):
        for k, b in getattr(self, "_btns", {}).items():
            b.fg = C.primary if k == self.current else C.muted

    def on_select(self, key):
        pass


class TabStrip(ScrollView):
    current = StringProperty("")
    __events__ = ("on_select",)

    def setup(self, tabs):
        row = self.ids.row
        row.clear_widgets()
        self._btns = {}
        for key, label in tabs:
            b = Btn(text=label, bg=(0, 0, 0, 0), fg=C.muted, size_hint_x=None, height=dp(46),
                    font_size=sp(13.5))
            b.bind(texture_size=lambda inst, ts: setattr(inst, "width", ts[0] + dp(26)))
            b.bind(on_release=lambda inst, k=key: self.dispatch("on_select", k))
            self._btns[key] = b
            row.add_widget(b)
        self.on_current()

    def on_current(self, *_):
        for k, b in getattr(self, "_btns", {}).items():
            active = k == self.current
            b.fg = C.primary if active else C.muted
            b.bg = C.tint if active else (0, 0, 0, 0)

    def on_select(self, key):
        pass


class Page(ScrollView):
    """Scrollable vertical page; add widgets with .add()."""

    @property
    def body(self):
        return self.ids.body

    def clear(self):
        self.ids.body.clear_widgets()
        self.scroll_y = 1

    def add(self, *widgets):
        for w in widgets:
            self.ids.body.add_widget(w)
        return widgets[-1] if widgets else None


def hrow(*widgets, spacing=8, height=None):
    row = BoxLayout(size_hint_y=None, spacing=dp(spacing))
    if height is None:
        row.height = dp(44)
    else:
        row.height = height
    for w in widgets:
        row.add_widget(w)
    return row


def chip_row(chips):
    row = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(6))
    for c in chips:
        row.add_widget(c)
    row.add_widget(Label())
    return row


def kv_row(key, value, value_color=None, bold=False):
    row = BoxLayout(size_hint_y=None, spacing=dp(8))
    k = WrapLabel(text=key, color=C.muted, font_size=sp(13), size_hint_x=0.48)
    v = WrapLabel(text=value, font_size=sp(14), bold=bold, halign="right",
                  color=value_color or C.text, size_hint_x=0.52)
    row.add_widget(k)
    row.add_widget(v)
    row.bind(minimum_height=row.setter("height"))
    k.bind(height=lambda *_: setattr(row, "height", max(k.height, v.height)))
    v.bind(height=lambda *_: setattr(row, "height", max(k.height, v.height)))
    return row


def section(title):
    return WrapLabel(text=title, font_size=sp(15.5), bold=True, color=C.primary_dark,
                     padding=(0, dp(6)))


class StyledSpinnerOption(SpinnerOption):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.background_normal = ""
        self.background_color = C.surface
        self.color = C.text
        self.height = dp(44)


class Select(Spinner):
    pass


def spinner(values, text=None, **kw):
    return Select(text=text or (values[0] if values else ""), values=values,
                  option_cls=StyledSpinnerOption, **kw)


def check(active=False, on_change=None):
    cb = CheckBox(active=active, size_hint=(None, None), size=(dp(36), dp(36)),
                  color=C.primary)
    if on_change:
        cb.bind(active=lambda inst, v: on_change(v))
    return cb


def check_row(cb, markup_text, font_size=None):
    """Checkbox + wrapped label, vertically centred."""
    from kivy.uix.anchorlayout import AnchorLayout
    row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
    box = AnchorLayout(size_hint_x=None, width=dp(36))
    box.add_widget(cb)
    holder = AnchorLayout(anchor_y="center")
    lbl = WrapLabel(text=markup_text, font_size=font_size or sp(14))
    holder.add_widget(lbl)
    row.add_widget(box)
    row.add_widget(holder)
    lbl.bind(height=lambda inst, h: setattr(row, "height", max(dp(40), h + dp(10))))
    return row


# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------

class Sheet(ModalView):
    """Bottom-sheet style dialog with a scrollable body."""

    def __init__(self, title, **kw):
        kw.setdefault("size_hint", (1, None))
        kw.setdefault("pos_hint", {"bottom": 1})
        kw.setdefault("background", "")
        kw.setdefault("background_color", (0, 0, 0, 0))
        kw.setdefault("overlay_color", (0, 0, 0, 0.45))
        super().__init__(**kw)
        self.card = Card(padding=(dp(18), dp(16)), spacing=dp(10))
        self.card.add_widget(WrapLabel(text=title, font_size=sp(18), bold=True))
        self.scroll = ScrollView(do_scroll_x=False, size_hint_y=None)
        self.inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        self.inner.bind(minimum_height=self.inner.setter("height"))
        self.scroll.add_widget(self.inner)
        self.card.add_widget(self.scroll)
        self.buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.card.add_widget(self.buttons)
        self.add_widget(self.card)
        self.inner.bind(height=self._resize)
        Window.bind(size=self._resize)
        self._resize()

    def _resize(self, *_):
        max_h = Window.height * 0.86
        chrome = dp(130)
        self.scroll.height = min(self.inner.height, max_h - chrome)
        self.height = self.scroll.height + chrome

    def add(self, *widgets):
        for w in widgets:
            self.inner.add_widget(w)

    def add_button(self, widget):
        self.buttons.add_widget(widget)

    def on_dismiss(self):
        Window.unbind(size=self._resize)


def info(title, text, buttons=None):
    s = Sheet(title)
    s.add(WrapLabel(text=text, font_size=sp(14)))
    for b in buttons or []:
        s.add_button(b)
    s.add_button(Btn(text="Fermer", on_release=lambda *_: s.dismiss()))
    s.open()
    return s


def confirm(title, text, on_yes, yes="Confirmer", danger=False):
    s = Sheet(title)
    s.add(WrapLabel(text=text))
    s.add_button(ghost("Annuler", on_release=lambda *_: s.dismiss()))
    btn = (danger_btn if danger else Btn)(yes)
    btn.bind(on_release=lambda *_: (s.dismiss(), on_yes()))
    s.add_button(btn)
    s.open()


def form(title, fields, on_submit, submit="Enregistrer", extra=None):
    """fields: list of dicts {key, label, text, hint, filter, multiline, choices, check}.

    on_submit(values) may return an error string to keep the dialog open."""
    s = Sheet(title)
    widgets = {}
    for f in fields:
        if f.get("choices"):
            s.add(Label(text=f["label"], size_hint_y=None, height=dp(18), font_size=sp(12.5),
                        color=C.muted, halign="left", text_size=(Window.width - dp(40), None)))
            labels = [c[1] for c in f["choices"]]
            current = dict(f["choices"]).get(f.get("text"), labels[0])
            w = spinner(labels, current)
            w._choices = f["choices"]
        elif f.get("check"):
            w = check(bool(f.get("text")))
            widgets[f["key"]] = w
            s.add(check_row(w, f["label"]))
            continue
        else:
            w = Field(label=f["label"], text=str(f.get("text") or ""), hint=f.get("hint", ""),
                      multiline=bool(f.get("multiline")), input_filter=f.get("filter"),
                      password=bool(f.get("password")))
        widgets[f["key"]] = w
        s.add(w)
    if extra:
        s.add(extra)
    err = WrapLabel(text="", color=C.danger, font_size=sp(13))
    s.add(err)

    def values():
        out = {}
        for k, w in widgets.items():
            if isinstance(w, Spinner):
                inv = {lbl: key for key, lbl in w._choices}
                out[k] = inv.get(w.text)
            elif isinstance(w, CheckBox):
                out[k] = w.active
            else:
                out[k] = w.text.strip()
        return out

    def submit_(*_):
        res = on_submit(values())
        if isinstance(res, str) and res:
            err.text = res
        else:
            s.dismiss()

    s.add_button(ghost("Annuler", on_release=lambda *_: s.dismiss()))
    s.add_button(Btn(text=submit, on_release=submit_))
    s.values = values
    s.open()
    return s


def toast(text, duration=2.6):
    lbl = Label(text=text, color=(1, 1, 1, 1), font_size=sp(14), size_hint=(None, None),
                halign="center", valign="middle")
    lbl.text_size = (min(Window.width - dp(48), dp(520)), None)
    lbl.texture_update()
    lbl.size = (lbl.texture_size[0] + dp(28), lbl.texture_size[1] + dp(20))
    from kivy.graphics import Color, RoundedRectangle
    with lbl.canvas.before:
        Color(0.06, 0.09, 0.16, 0.92)
        rr = RoundedRectangle(pos=lbl.pos, size=lbl.size, radius=[dp(12)])
    lbl.bind(pos=lambda *_: setattr(rr, "pos", lbl.pos), size=lambda *_: setattr(rr, "size", lbl.size))
    lbl.pos = ((Window.width - lbl.width) / 2, dp(84))
    Window.add_widget(lbl)
    lbl.opacity = 0
    Animation(opacity=1, d=0.15).start(lbl)

    def hide(dt):
        a = Animation(opacity=0, d=0.3)
        a.bind(on_complete=lambda *_: Window.remove_widget(lbl))
        a.start(lbl)
    Clock.schedule_once(hide, duration)


class Busy(ModalView):
    """Blocking progress dialog for long operations."""

    def __init__(self, text, **kw):
        super().__init__(size_hint=(0.86, None), height=dp(150), auto_dismiss=False,
                         background="", background_color=(0, 0, 0, 0), **kw)
        card = Card(padding=(dp(18), dp(18)), spacing=dp(12))
        self.lbl = WrapLabel(text=text, font_size=sp(15), bold=True)
        self.sub = WrapLabel(text="", font_size=sp(12.5), color=C.muted)
        self.bar = ProgressBarH(value=0.05, color=C.accent)
        card.add_widget(self.lbl)
        card.add_widget(self.sub)
        card.add_widget(self.bar)
        self.add_widget(card)
        self._ev = Clock.schedule_interval(self._pulse, 0.08)
        self._t = 0

    def _pulse(self, dt):
        self._t += dt
        if self.bar.value < 0.92:
            self.bar.value += (0.95 - self.bar.value) * 0.004

    def set(self, text=None, sub=None):
        if text is not None:
            self.lbl.text = text
        if sub is not None:
            self.sub.text = sub

    def close(self):
        self._ev.cancel()
        self.dismiss()
