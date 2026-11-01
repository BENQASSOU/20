"""Exercise every screen and every handler of the Flet interface headlessly."""

import os

import pytest

ft = pytest.importorskip("flet")

import ui_harness as H  # noqa: E402

from safqa import demo  # noqa: E402
from safqa.storage import Store  # noqa: E402


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    d = tmp_path_factory.mktemp("tpl")
    path = str(d / "safqa.db")
    st = Store(path)
    demo.load_demo(st)
    screens = H.all_screens(st)
    st.close()
    return path, screens


@pytest.fixture(autouse=True)
def headless(monkeypatch):
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    monkeypatch.setattr(ft, "FilePicker", H.FakeService)
    monkeypatch.setattr(ft, "Share", H.FakeService)
    old = os.environ.get("FLET_APP_STORAGE_DATA")
    yield
    if old is None:
        os.environ.pop("FLET_APP_STORAGE_DATA", None)
    else:
        os.environ["FLET_APP_STORAGE_DATA"] = old


def _report(ex):
    return "\n\n".join(ex.failures[:5])


def test_every_screen_and_handler_with_demo_data(template):
    path, screens = template
    ex = H.Explorer(path)
    for s in screens:
        ex.explore(s)
    assert ex.screens == len(screens)
    assert ex.invocations > 500
    assert not ex.failures, _report(ex)
    # Deleting the demo document or contract must never touch the bundled sample.
    assert os.path.exists(demo.SAMPLE_CPS)


def test_every_screen_with_empty_database():
    ex = H.Explorer(None, empty=True)
    for s in ([("/", t, {}) for t in range(5)] + [("/", 3, {"finance_tab": i}) for i in range(4)] +
              [("/module/%s" % m, 4, {}) for m in ("echeancier", "tiers", "assistant", "rapports",
                                                     "parametres", "abonnement", "diagnostic", "garanties")]):
        ex.explore(s)
    assert not ex.failures, _report(ex)


def test_deep_link_opens_form_once_and_stale_dialogs_close(template):
    path, _ = template
    ex = H.Explorer(path)
    page, app, d = ex.fresh(("/", 0, {}))
    from safqa.gui import app as appmod
    pid = app.store.projects()[0]["id"]

    class Dialogs:
        controls = page.dialogs
    page._dialogs = Dialogs()

    for tab in ("journal", "decomptes"):
        page.dialogs.clear()
        page.navigate("/marche/%s?tab=%s&new=1" % (pid, tab))
        forms = [x for x in page.dialogs if isinstance(x, ft.AlertDialog) and x.open]
        assert len(forms) == 1, tab
        appmod.build_views(app)  # a refresh must not open it a second time
        assert len([x for x in page.dialogs if isinstance(x, ft.AlertDialog)]) == 1
        page.navigate("/")  # leaving the screen closes it
        assert not forms[0].open
    app.store.close()
