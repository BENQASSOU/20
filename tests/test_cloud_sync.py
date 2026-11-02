"""End to end: two phones of the same company synchronise through a real
Safqa Cloud server (HTTP, SQLite backend)."""

import os
import socket
import sys
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")
uvicorn = pytest.importorskip("uvicorn")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
os.environ.setdefault("SAFQA_NO_AUTOAPP", "1")

from safqa import billing, cloud, demo  # noqa: E402
from safqa.storage import Store  # noqa: E402
from safqa_cloud.app import create_app  # noqa: E402
from safqa_cloud.config import Settings  # noqa: E402

PW = "Chantier-2026!"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    d = tmp_path_factory.mktemp("srv")
    app = create_app(Settings(env="test", database_url="sqlite:///%s" % (d / "c.db"),
                              data_key="e2e-key-0123456789abcdef", trust_proxy=False))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield "http://127.0.0.1:%d" % port
    srv.should_exit = True
    th.join(5)


def phone(tmp_path, name):
    st = Store(str(tmp_path / name / "safqa.db"))
    return st, cloud.Account(st), str(tmp_path / name / "documents")


def test_two_phones_share_a_company(server, tmp_path):
    # Phone A: demo data, creates the account and the company space.
    a, acc_a, docs_a = phone(tmp_path, "a")
    demo.load_demo(a)
    os.makedirs(docs_a, exist_ok=True)
    doc = a.q("SELECT id, path FROM documents")[0]
    pdf = os.path.join(docs_a, "cps.pdf")
    with open(pdf, "wb") as fh:
        fh.write(b"%PDF-1.4 CPS de test " * 50)
    a.update("documents", doc["id"], {"path": pdf})
    c = cloud.Cloud(server)
    acc_a.save_login(server, c.signup("chef@btp.ma", PW, "Chef", "BTP Atlas", "A"))
    org = acc_a.me["orgs"][0]["id"]
    cloud.attach(a, acc_a, org, "push")
    res = cloud.synchronize(a, acc_a, docs_a)
    assert res["sent"] > 100 and res["files_up"] == 1
    assert billing.Subscription(a).status()["label"] == "Essai Pro"

    # Phone B: a colleague joins with an invitation code.
    b, acc_b, docs_b = phone(tmp_path, "b")
    code = cloud.Cloud(server, acc_a.token).invite(org, "member")["code"]
    acc_b.save_login(server, cloud.Cloud(server).signup("conducteur@btp.ma", PW, "Conducteur", "", "B"))
    acc_b.save_me(cloud.Cloud(server, acc_b.token).accept(code))
    cloud.attach(b, acc_b, org, "replace", backup_dir=str(tmp_path / "b" / "backups"))
    res = cloud.synchronize(b, acc_b, docs_b)
    assert a.sync_pending() == 0 and res["received"] > 100
    assert [p["ref"] for p in b.projects()] == [p["ref"] for p in a.projects()]
    assert b.get_json("company") == a.get_json("company")
    assert res["files_down"] == 1
    bdoc = b.get_row("documents", doc["id"])
    assert open(bdoc["path"], "rb").read().startswith(b"%PDF-1.4 CPS")

    # B records an expense and edits a project; A creates a tier. No id collision.
    pid = b.projects()[0]["id"]
    eid = b.insert("expenses", {"project_id": pid, "label": "Gasoil chantier", "amount_ht": 1500, "date": "2026-11-02"})
    b.save_project({"title": "Titre modifié sur B"}, pid)
    tid = a.insert("tiers", {"kind": "fournisseur", "name": "Ciments du Maroc"})
    assert eid != tid and eid >= 10 ** 9 * acc_b.device_no(org) and tid >= 10 ** 9 * acc_a.device_no(org)
    cloud.synchronize(b, acc_b, docs_b)
    cloud.synchronize(a, acc_a, docs_a)
    cloud.synchronize(b, acc_b, docs_b)
    assert a.get_row("expenses", eid)["label"] == "Gasoil chantier"
    assert a.project(pid)["title"] == "Titre modifié sur B"
    assert b.get_row("tiers", tid)["name"] == "Ciments du Maroc"

    # Deletion on A reaches B; checklist rows (composite key) too.
    a.set_check(pid, "ASSURANCES", True)
    a.delete("expenses", eid)
    cloud.synchronize(a, acc_a, docs_a)
    cloud.synchronize(b, acc_b, docs_b)
    assert b.get_row("expenses", eid) is None
    assert any(c["code"] == "ASSURANCES" and c["present"] for c in b.checklist(pid))
    assert a.sync_pending() == 0 and b.sync_pending() == 0

    # Secrets never leave the phone.
    a.set("api_key", "sk-ant-secret")
    a.set("license_key", "SAFQA-PRO-X")
    cloud.synchronize(a, acc_a, docs_a)
    cloud.synchronize(b, acc_b, docs_b)
    assert b.get("api_key") is None and b.get("license_key") is None


def test_viewer_receives_but_never_sends(server, tmp_path):
    a, acc_a, docs_a = phone(tmp_path, "owner")
    acc_a.save_login(server, cloud.Cloud(server).signup("own@ex.ma", PW, "O", "Lecture SARL", "A"))
    org = acc_a.me["orgs"][0]["id"]
    cloud.attach(a, acc_a, org, "push")
    a.insert("tiers", {"kind": "client", "name": "Commune de Salé"})
    cloud.synchronize(a, acc_a, docs_a)
    v, acc_v, docs_v = phone(tmp_path, "viewer")
    code = cloud.Cloud(server, acc_a.token).invite(org, "viewer")["code"]
    acc_v.save_login(server, cloud.Cloud(server).signup("view@ex.ma", PW, "V", "", "V"))
    acc_v.save_me(cloud.Cloud(server, acc_v.token).accept(code))
    cloud.attach(v, acc_v, org, "replace")
    cloud.synchronize(v, acc_v, docs_v)
    assert v.tiers()[0]["name"] == "Commune de Salé"
    v.insert("tiers", {"kind": "client", "name": "Modif locale"})
    cloud.synchronize(v, acc_v, docs_v)          # does not fail, does not send
    cloud.synchronize(a, acc_a, docs_a)
    assert [t["name"] for t in a.tiers()] == ["Commune de Salé"]


def test_https_is_required_for_remote_servers():
    with pytest.raises(cloud.CloudError):
        cloud.Cloud("http://safqa.example.com").me()
