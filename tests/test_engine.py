import os
from datetime import date, timedelta

import pytest

from safqa import analysis, billing, risk, rules
from safqa import tracking as tr
from safqa.segment import quote_in_text, split_articles
from safqa.textnum import fmt_dh, parse_decimal, words_to_int
from safqa.textract import extract, guess_doc_type

HERE = os.path.dirname(__file__)
CPS = os.path.join(HERE, "fixtures", "sample_cps.txt")


@pytest.fixture(scope="module")
def cps():
    doc = extract(CPS)
    arts = split_articles(doc)
    res = rules.extract(arts)
    resolved, conflicts = rules.resolve_terms(res["terms"])
    return doc, arts, res, resolved, conflicts


def test_french_numbers():
    assert words_to_int("trente") == 30
    assert words_to_int("quatre-vingt-dix") == 90
    assert words_to_int("soixante-quinze") == 75
    assert words_to_int("deux millions quatre cent cinquante mille") == 2450000
    assert words_to_int("cent vingt") == 120
    assert words_to_int("travaux") is None


def test_decimal_and_format():
    assert parse_decimal("2 450 000,00") == 2450000.0
    assert parse_decimal("1.234.567,89") == 1234567.89
    assert parse_decimal("12.5") == 12.5
    assert fmt_dh(1234567.891) == "1 234 567,89 DH"


def test_articles(cps):
    doc, arts, *_ = cps
    keys = [a.key for a in arts]
    assert "A10" in keys and "A17" in keys
    a10 = next(a for a in arts if a.key == "A10")
    assert "PENALITES POUR RETARD" in a10.title
    assert a10.text.startswith("A défaut")
    assert guess_doc_type(doc.text, "x.pdf") == "CPS"


def test_terms(cps):
    _, _, _, t, conflicts = cps
    assert t["execution_delay_days"]["value"] == 180
    assert t["execution_delay_days"]["article_key"] == "A5"
    assert t["penalty_rate_per_day"]["value"] == pytest.approx(0.001)
    assert t["penalty_cap_pct"]["value"] == 10
    assert t["penalty_cap_pct"]["article_key"] == "A10"
    assert t["retenue_rate_pct"]["value"] == 10
    assert t["retenue_cap_pct"]["value"] == 7
    assert t["caution_definitive_pct"]["value"] == 3
    assert t["caution_definitive_delay_days"]["value"] == 30
    assert t["warranty_months"]["value"] == 12
    assert t["payment_delay_days"]["value"] == 60
    assert t["price_type"]["value"] == "ferme"
    assert t["contract_amount_ttc"]["value"] == 2450000
    assert t["tva_pct"]["source"] == "défaut"
    assert conflicts == []


def test_findings_have_citations(cps):
    _, _, res, *_ = cps
    kinds = {f["kind"] for f in res["findings"]}
    assert {"obligation", "deadline", "penalty", "derogation", "risky_clause", "inconsistency"} <= kinds
    for f in res["findings"]:
        assert f["article_key"] and f["article_label"] and f["page"]
    der = [f for f in res["findings"] if f["kind"] == "derogation"]
    assert der[0]["value"]["ccag_articles"] == ["65"]
    other = [f for f in res["findings"] if f["kind"] == "penalty" and f["article_key"] == "A11"]
    assert "500 DH par absence" in other[0]["summary"]


def test_issues(cps):
    _, arts, res, t, conflicts = cps
    issues = rules.document_issues(arts, res["findings"], t, conflicts)
    titles = " | ".join(i["title"] for i in issues)
    assert "Montant en lettres" in titles
    assert "Plafond des pénalités supérieur" in titles
    assert "Dérogation à l'article 65" in titles


def test_conflict_detection():
    from safqa.textract import ExtractedDoc
    doc = ExtractedDoc(["ARTICLE 1 : DELAI D'EXECUTION\nLe délai d'exécution est fixé à six (6) mois.\n"
                        "ARTICLE 2 : PLANNING\nLe délai d'exécution des travaux est de 240 jours."], "txt")
    arts = split_articles(doc)
    res = rules.extract(arts)
    _, conflicts = rules.resolve_terms(res["terms"])
    assert conflicts and conflicts[0]["key"] == "execution_delay_days"


def test_quote_matching():
    assert quote_in_text("pénalité de 1/1000  du montant", "une Pénalité de 1/1000 du montant initial")
    assert not quote_in_text("pénalité de 2/1000", "une pénalité de 1/1000")


# --------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------

def _project(**kw):
    p = {"amount_ttc": 1000000.0, "delay_days": 100,
         "terms": {"penalty_rate_per_day": {"value": 0.001}, "penalty_cap_pct": {"value": 8},
                   "retenue_rate_pct": {"value": 10}, "retenue_cap_pct": {"value": 7}}}
    p.update(kw)
    return p


def test_schedule_with_stops_and_penalties():
    start = date(2026, 1, 1)
    orders = [{"kind": "commencement", "date": "2026-01-01"},
              {"kind": "arret", "date": "2026-02-01"},
              {"kind": "reprise", "date": "2026-02-11"}]
    p = _project()
    s = tr.schedule(p, orders, today=date(2026, 5, 1))
    assert s["start"] == start
    assert s["suspended_days"] == 10
    assert s["end"] == start + timedelta(days=110)
    assert s["late_days"] == (date(2026, 5, 1) - s["end"]).days
    pen = tr.penalty_estimate(p, s)
    assert pen["amount"] == pytest.approx(s["late_days"] * 0.001 * 1000000)
    late = tr.schedule(p, orders, today=date(2027, 1, 1))
    assert tr.penalty_estimate(p, late)["amount"] == 80000  # capped at 8 %


def test_open_stop_extends_deadline():
    orders = [{"kind": "commencement", "date": "2026-01-01"}, {"kind": "arret", "date": "2026-03-01"}]
    s = tr.schedule(_project(), orders, today=date(2026, 4, 30))
    assert s["stopped"] and s["suspended_days"] == 60 and s["late_days"] == 0


def test_months_delay():
    p = _project(delay_days=None, delay_months=6)
    s = tr.schedule(p, [{"kind": "commencement", "date": "2026-01-31"}], today=date(2026, 3, 1))
    assert s["end"] == date(2026, 7, 31)


def test_decompte_retenue_cap():
    p = _project()
    items = [{"number": "1", "qty_executed": 10, "unit_price_ht": 50000}]  # 500 000 HT
    d1 = tr.compute_decompte(p, items, [])
    assert d1["total_ttc"] == pytest.approx(600000)
    assert d1["retenue"] == pytest.approx(60000)
    items[0]["qty_executed"] = 15  # 900 000 TTC -> 10 % = 90 000 > cap 70 000
    d2 = tr.compute_decompte(p, items, [d1])
    assert d2["retenue"] == pytest.approx(70000)
    assert d2["net_ttc"] == pytest.approx((900000 - 70000) - d1["net_cumul_ttc"])
    assert d2["number"] == 2


def test_payment_delay():
    d = {"submitted_date": "2026-01-01", "net_ttc": 1000}
    st = tr.payment_status(d, {}, today=date(2026, 3, 15))
    assert st["late"] and st["days"] == 73 and st["limit"] == 60


def test_bpde_csv():
    items = tr.parse_bpde_csv("N;Désignation;U;Qté;PU\n1;Déblais;m3;1 200;45,50\n2;Béton;m3;80;1200\n")
    assert len(items) == 2 and items[0]["qty_contract"] == 1200 and items[0]["unit_price_ht"] == 45.5


def test_reception_warranty():
    p = _project(terms={"warranty_months": {"value": 12}})
    rs = tr.reception_status(p, [{"kind": "provisoire", "date": "2025-01-15"}], today=date(2026, 2, 1))
    assert rs["warranty_end"] == date(2026, 1, 15) and rs["final_due"]


# --------------------------------------------------------------------------
# Risk engine
# --------------------------------------------------------------------------

def test_risk_flags():
    today = date(2026, 6, 1)
    p = _project(approval_notif_date="2026-01-01", terms={
        "penalty_rate_per_day": {"value": 0.001}, "penalty_cap_pct": {"value": 8},
        "payment_delay_days": {"value": 60}, "mass_increase_pct": {"value": 10}})
    orders = [{"kind": "commencement", "date": "2026-01-10"}]
    items = [{"number": "1", "designation": "Béton", "unit": "m3", "qty_contract": 100,
              "qty_executed": 150, "unit_price_ht": 1000}]
    decs = [{"number": 1, "submitted_date": "2026-03-01", "net_ttc": 50000, "status": "émis"}]
    flags = risk.evaluate(p, [], [], orders, items, decs, [], today)
    titles = [f["title"] for f in flags]
    assert any("Cautionnement définitif non constitué" in t for t in titles)
    assert any(t.startswith("Retard d'exécution") for t in titles)
    assert any("Dépassement prix n° 1" in t for t in titles)
    assert any("Augmentation dans la masse" in t for t in titles)
    assert any("impayé" in t for t in titles)
    assert flags[0]["severity"] == "critique"
    exp = risk.exposure(flags)
    assert exp["late_receivables"] == 50000 and exp["penalties"] > 0


# --------------------------------------------------------------------------
# Ingestion and licences
# --------------------------------------------------------------------------

def test_ingest_and_project_terms():
    d = analysis.ingest(CPS)
    assert d["doc_type"] == "CPS" and d["articles"] and d["analysis"]["issues"]
    terms = analysis.project_terms([d])
    assert terms["penalty_rate_per_day"]["source"] == "CPS"


def test_docx_extraction(tmp_path):
    import zipfile
    body = ("<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>"
            "<w:p><w:r><w:t>ARTICLE 1 : DELAI D'EXECUTION</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Le délai d'exécution est fixé à trois (3) mois.</w:t></w:r></w:p>"
            "</w:body></w:document>")
    path = tmp_path / "cps.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", body)
    d = analysis.ingest(str(path))
    assert d["analysis"]["terms"]["execution_delay_days"]["value"] == 90


def test_license_keys():
    secret = b"test-secret"
    exp = date.today() + timedelta(days=30)
    key = billing.make_key("pro", exp, "Btp Atlas sarl", secret)
    ok, plan, expiry, _ = billing.check_key(key, secret=secret)
    assert ok and plan == "PRO" and expiry == exp
    assert not billing.check_key(key.replace("PRO", "ENTREPRISE"), secret=secret)[0]
    old = billing.make_key("ESSENTIEL", date(2020, 1, 1), "X1Y", secret)
    assert not billing.check_key(old, secret=secret)[0]
