"""Built-in Safqa IA: answers with citations, recommendations, letters."""

import pytest

from safqa import copilot, demo, erp
from safqa.storage import Store


@pytest.fixture(scope="module")
def demo_store(tmp_path_factory):
    st = Store(str(tmp_path_factory.mktemp("cop") / "safqa.db"))
    demo.load_demo(st)
    yield st
    st.close()


def main_state(st):
    for p in st.projects():
        s = erp.project_state(st, p["id"])
        if s["documents"] and s["decomptes"]:
            return s
    raise AssertionError("no demo project with documents")


def test_late_interest_is_simple_interest():
    assert copilot.late_interest(365000, 10, 5) == pytest.approx(500.0)
    assert copilot.late_interest(1000, -3, 5) == 0


def test_answer_payment_question_cites_the_payment_clause(demo_store):
    s = main_state(demo_store)
    ans = copilot.answer(s, "Le maître d'ouvrage paie en retard : combien puis-je réclamer ?")
    assert "intérêts moratoires" in ans
    key = s["terms"]["payment_delay_days"]["article_key"]
    assert "[%s]" % key in ans
    assert "**Délais**" not in ans   # "en retard" is about payment here


@pytest.mark.parametrize("question,expected", [
    ("Comment sont calculées les pénalités de retard ?", "Pénalités de retard"),
    ("Quand se termine mon délai d'exécution ?", "Délais"),
    ("Quels documents me manquent ?", "Documents"),
    ("Quelle est ma marge prévisionnelle ?", "Rentabilité"),
    ("Quand récupérer ma caution ?", "Cautions"),
])
def test_answer_intents(demo_store, question, expected):
    assert expected in copilot.answer(main_state(demo_store), question)


def test_answer_retrieves_clause_by_plural_and_apostrophe(demo_store):
    s = main_state(demo_store)
    ans = copilot.answer(s, "Que dit le CPS sur l'assurance ?")
    assert "ASSURANCES" in ans.upper().split("CE QUE DIT VOTRE MARCHÉ")[1]


def test_unknown_question_gives_guidance(demo_store):
    ans = copilot.answer(main_state(demo_store), "xyzzy")
    assert "Reformulez" in ans


def test_insights_are_actionable_and_sorted(demo_store):
    items = copilot.insights(demo_store)
    assert items
    assert all(i["actions"] for i in items)
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    kinds = {a[1] for i in items for a in i["actions"]}
    assert "letter" in kinds
    pid = items[0]["pid"]
    assert all(i["pid"] == pid for i in copilot.insights(demo_store, pid=pid))


@pytest.mark.parametrize("kind", [k for k, _ in copilot.LETTERS])
def test_every_letter_renders_and_exports(demo_store, kind):
    s = main_state(demo_store)
    subject, text = copilot.letter(kind, s, {"name": "BTP Atlas", "city": "Rabat", "manager": "M. Alami"})
    assert subject in text and "BTP Atlas" in text and "M. Alami" in text
    assert s["project_full"]["ref"] in text
    pdf = copilot.letter_pdf(subject, text)
    assert pdf.startswith(b"%PDF")


def test_payment_letter_lists_overdue_decompte(demo_store):
    s = main_state(demo_store)
    _, text = copilot.letter("relance_paiement", s, {})
    assert "jours de retard" in text and "2-16-344" in text
