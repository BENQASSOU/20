import io
import os
import sqlite3
from datetime import date

import pytest
from pypdf import PdfReader

from safqa import demo, erp, reports, selftest
from safqa.pdf import PDF, text_width, wrap
from safqa.storage import Store, restore_backup
from safqa.textnum import amount_in_words, int_to_words, words_to_int

TODAY = date(2026, 10, 29)


@pytest.fixture()
def store(tmp_path):
    st = Store(str(tmp_path / "t.db"))
    demo.load_demo(st, TODAY)
    yield st
    st.close()


@pytest.mark.parametrize("n,text", [
    (21, "vingt et un"), (71, "soixante et onze"), (80, "quatre-vingts"), (81, "quatre-vingt-un"),
    (200, "deux cents"), (201, "deux cent un"), (1000, "mille"), (80000, "quatre-vingt mille"),
    (200000, "deux cent mille"), (2450000, "deux millions quatre cent cinquante mille"),
])
def test_int_to_words(n, text):
    assert int_to_words(n) == text
    assert words_to_int(text) == n


def test_amount_in_words():
    assert amount_in_words(1) == "un dirham"
    assert amount_in_words(992440) == "neuf cent quatre-vingt-douze mille quatre cent quarante dirhams"
    assert amount_in_words(10.5).endswith("et cinquante centimes")


def test_pdf_valid_with_accents_and_pages():
    p = PDF("Rapport été", "Témara", "Société")
    p.para("Pénalité de retard : 1/1000 par jour — plafond « 8 % » ≤ 10 %")
    p.table([("A", 1, "l"), ("Montant", 1, "r")], [[str(i), "%d,00" % i] for i in range(120)])
    data = p.output()
    r = PdfReader(io.BytesIO(data))
    assert len(r.pages) >= 3
    text = r.pages[0].extract_text()
    assert "Pénalité" in text and "Témara" in text


def test_wrap_respects_width():
    for line in wrap("mot " * 200, 100, 10):
        assert text_width(line, 10) <= 100.5


def test_demo_portfolio_is_consistent(store):
    pf = erp.portfolio(store, TODAY)
    t = pf["totals"]
    assert t["projects"] == 3
    assert t["unpaid_ttc"] > 0 and t["guarantees"] > 0
    assert abs(t["backlog_ht"] - (t["contract_ht"] - t["invoiced_ht"])) < 1
    for row in pf["rows"]:
        assert row["state"]["finance"]["invoiced_ratio"] <= 1.0001
    assert pf["pipeline"]["win_rate"] == pytest.approx(2 / 3)
    assert len(pf["series"]) == 12


def test_risk_flags_from_erp_modules(store):
    titles = [f["title"] for s in erp.portfolio(store, TODAY)["states"] for f in s["flags"]]
    assert any("Cautionnement définitif non constitué" in t for t in titles)
    assert any(t.startswith("Dépassement budget") for t in titles)
    assert any("Facture fournisseur échue" in t for t in titles)


def test_cashflow_and_agenda(store):
    cf = erp.cashflow_forecast(store, TODAY)
    assert len(cf) == 6 and cf[0]["inflow"] > 0
    ev = erp.agenda(store, TODAY)
    kinds = {e["kind"] for e in ev}
    assert {"Appel d'offres", "Caution", "Paiement"} <= kinds
    assert ev == sorted(ev, key=lambda e: (e["date"], e["kind"]))


def test_reports_are_pdfs(store):
    pf = erp.portfolio(store, TODAY)
    co = store.get_json("company")
    s = pf["states"][0]
    for data in (reports.contract_report(s, co, TODAY), reports.decompte_pdf(s, s["decomptes"][-1], co),
                 reports.portfolio_pdf(store, co, TODAY), reports.treasury_pdf(store, co, TODAY),
                 reports.guarantees_pdf(store, co, TODAY), reports.analysis_pdf(s, co)):
        assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
        assert len(PdfReader(io.BytesIO(data)).pages) >= 1
    text = PdfReader(io.BytesIO(reports.decompte_pdf(s, s["decomptes"][-1], co))).pages[0].extract_text()
    assert "NET À PAYER" in text and "dirhams" in text
    assert reports.expenses_csv(store).startswith("﻿".encode("utf-8"))


def test_measurements_recompute(store):
    item = store.q("SELECT * FROM items ORDER BY id LIMIT 1")[0]
    before = item["qty_executed"]
    store.insert("measurements", {"project_id": item["project_id"], "item_id": item["id"], "qty": 10.0})
    assert store.recompute_item(item["id"]) == pytest.approx(before + 10)


def test_migration_adds_columns(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, ref TEXT, title TEXT, archived INTEGER DEFAULT 0,"
                 " updated_at TEXT)")
    conn.commit()
    conn.close()
    st = Store(path)
    cols = {r[1] for r in st.conn.execute("PRAGMA table_info(projects)")}
    assert {"status", "client_id", "category"} <= cols
    st.close()


def test_backup_restore(store, tmp_path):
    data = store.backup_bytes()
    target = str(tmp_path / "restored.db")
    restore_backup(target, data)
    st2 = Store(target)
    assert len(st2.projects()) == 3
    st2.close()
    with pytest.raises(ValueError):
        restore_backup(target, b"not a database")


def test_selftest(tmp_path):
    ok, lines = selftest.run(str(tmp_path))
    assert ok, "\n".join(lines)
    assert os.path.exists(tmp_path / "rapport.pdf")
