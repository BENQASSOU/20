"""On-device self-test: exercises the engine end to end without the UI.

Triggered in CI with `adb shell setprop debug.safqa.selftest 1` (or the
DEBUG_SAFQA_SELFTEST environment variable on a PC) and also available from
Paramètres > Diagnostic.  Results go to the log (tag SAFQA)."""

import os
import tempfile
import time
import traceback

from . import demo, erp, reports
from .log import log
from .storage import Store


def run(work_dir=None):
    """Returns (ok, lines)."""
    lines = []
    ok = True
    work_dir = work_dir or tempfile.mkdtemp(prefix="safqa_selftest_")

    def step(name, fn):
        nonlocal ok
        t0 = time.time()
        try:
            detail = fn()
            lines.append("OK   %-28s %5.0f ms  %s" % (name, (time.time() - t0) * 1000, detail or ""))
        except Exception:  # noqa: BLE001 - report every failure
            ok = False
            lines.append("FAIL %-28s\n%s" % (name, traceback.format_exc()))

    state = {}

    def open_store():
        state["store"] = Store(os.path.join(work_dir, "selftest.db"))
        return work_dir

    def load():
        r = demo.load_demo(state["store"])
        return "%d marchés" % len(r["projects"])

    def portfolio():
        pf = erp.portfolio(state["store"])
        state["pf"] = pf
        return "%d alertes" % sum(r["critical"] + r["high"] for r in pf["rows"])

    def analysis_check():
        s = state["pf"]["states"][0]
        n = sum(len((d.get("analysis") or {}).get("findings", [])) for d in s["documents"])
        if not n:
            raise AssertionError("aucun élément extrait du CPS de démonstration")
        return "%d éléments extraits" % n

    def pdfs():
        st, s = state["store"], state["pf"]["states"][0]
        co = st.get_json("company", {})
        sizes = [len(reports.contract_report(s, co)), len(reports.decompte_pdf(s, s["decomptes"][-1], co)),
                 len(reports.portfolio_pdf(st, co)), len(reports.treasury_pdf(st, co)),
                 len(reports.guarantees_pdf(st, co)), len(reports.analysis_pdf(s, co))]
        path = os.path.join(work_dir, "rapport.pdf")
        with open(path, "wb") as fh:
            fh.write(reports.contract_report(s, co))
        return "%d PDF, %d octets" % (len(sizes), sum(sizes))

    def agenda():
        return "%d échéances" % len(erp.agenda(state["store"]))

    def cashflow():
        return "%d mois" % len(erp.cashflow_forecast(state["store"]))

    def backup():
        return "%d octets" % len(state["store"].backup_bytes())

    for name, fn in [("base de données", open_store), ("données de démonstration", load),
                     ("tableau de bord", portfolio), ("analyse du CPS", analysis_check),
                     ("rapports PDF", pdfs), ("échéancier", agenda), ("trésorerie", cashflow),
                     ("sauvegarde", backup)]:
        step(name, fn)
    if "store" in state:
        state["store"].close()
    for ln in lines:
        log("SELFTEST " + ln)
    log("SELFTEST %s" % ("PASSED" if ok else "FAILED"))
    return ok, lines
