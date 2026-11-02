"""Safqa Cloud server: security, multi-company isolation, sync, back-office.

Runs on SQLite by default; set SAFQA_TEST_DATABASE_URL=postgresql://... to run
the same tests on PostgreSQL (done in CI)."""

import hashlib
import os
import sys
import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
os.environ.setdefault("SAFQA_NO_AUTOAPP", "1")

from fastapi.testclient import TestClient  # noqa: E402

from safqa_cloud import security as sec  # noqa: E402
from safqa_cloud.app import create_app  # noqa: E402
from safqa_cloud.config import Settings  # noqa: E402

PW = "Chantier-2026!"


@pytest.fixture()
def client(tmp_path):
    url = os.environ.get("SAFQA_TEST_DATABASE_URL") or "sqlite:///%s" % (tmp_path / "cloud.db")
    if url.startswith("postgres"):
        import psycopg
        with psycopg.connect(url, autocommit=True) as c:
            for t in ("users", "sessions", "orgs", "members", "invites", "devices", "records", "files",
                      "ai_usage", "reset_codes", "audit"):
                c.execute("DROP TABLE IF EXISTS %s" % t)
    settings = Settings(env="test", database_url=url, data_key="test-data-key-0123456789abcdef",
                        admin_emails="boss@safqa.ma", license_secret="lic-secret", anthropic_key="",
                        trust_proxy=False)
    app = create_app(settings)
    yield TestClient(app)
    app.state.db.close()


def signup(client, email=None, company="BTP Atlas", password=PW):
    email = email or "u%s@example.ma" % uuid.uuid4().hex[:8]
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "name": "Test",
                                              "company": company, "device": "pytest"})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"email": email, "token": data["token"], "h": {"authorization": "Bearer " + data["token"]},
            "orgs": data["orgs"]}


def test_signup_and_trial_plan(client):
    u = signup(client)
    assert u["orgs"][0]["role"] == "owner"
    assert u["orgs"][0]["label"] == "Essai Pro" and u["orgs"][0]["active"]
    me = client.get("/api/me", headers=u["h"]).json()
    assert me["user"]["email"] == u["email"]


@pytest.mark.parametrize("pw", ["court", "aaaaaaaaaaaa", "1234567890", "password123"])
def test_weak_passwords_rejected(client, pw):
    r = client.post("/api/auth/signup", json={"email": "weak@example.ma", "password": pw})
    assert r.status_code == 400


def test_duplicate_email_rejected(client):
    u = signup(client)
    r = client.post("/api/auth/signup", json={"email": u["email"].upper(), "password": PW})
    assert r.status_code == 409


def test_login_lockout_after_5_failures(client):
    u = signup(client)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": u["email"], "password": "mauvais-mot-2026"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": u["email"], "password": PW})
    assert r.status_code == 423


def test_unknown_email_same_answer(client):
    r = client.post("/api/auth/login", json={"email": "nobody@example.ma", "password": PW})
    assert r.status_code == 401 and "incorrect" in r.json()["detail"]


def test_bad_or_missing_token(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"authorization": "Bearer forged"}).status_code == 401


def test_logout_revokes_token(client):
    u = signup(client)
    assert client.post("/api/auth/logout", headers=u["h"]).status_code == 200
    assert client.get("/api/me", headers=u["h"]).status_code == 401


def test_companies_are_isolated(client):
    a, b = signup(client), signup(client, company="Autre SARL")
    org_a = a["orgs"][0]["id"]
    r = client.post("/api/orgs/%s/sync" % org_a, headers=b["h"], json={"since": 0, "changes": []})
    assert r.status_code == 404
    assert client.get("/api/orgs/%s/members" % org_a, headers=b["h"]).status_code == 404
    assert client.get("/api/orgs/%s/export" % org_a, headers=b["h"]).status_code == 404


def _dev(client, u, org):
    return client.post("/api/orgs/%s/devices" % org, headers=u["h"], json={"name": "tel"}).json()["device_no"]


def test_sync_between_two_devices_and_encryption_at_rest(client):
    owner = signup(client)
    org = owner["orgs"][0]["id"]
    d1, d2 = _dev(client, owner, org), _dev(client, owner, org)
    assert d1 != d2
    changes = [{"t": "projects", "id": "1000000001", "d": {"id": 1000000001, "title": "Voirie Témara", "ref": "12/2026"}},
               {"t": "decomptes", "id": "1000000002", "d": {"id": 1000000002, "project_id": 1000000001, "net_ttc": 990000}}]
    r = client.post("/api/orgs/%s/sync" % org, headers=owner["h"], json={"device_no": d1, "since": 0, "changes": changes})
    assert r.status_code == 200 and r.json()["changes"] == []          # own changes not echoed
    pull = client.post("/api/orgs/%s/sync" % org, headers=owner["h"], json={"device_no": d2, "since": 0}).json()
    got = {(c["t"], c["id"]): c for c in pull["changes"]}
    assert got[("projects", "1000000001")]["d"]["title"] == "Voirie Témara"
    seq = pull["seq"]
    # delete propagates
    client.post("/api/orgs/%s/sync" % org, headers=owner["h"],
                json={"device_no": d1, "since": seq, "changes": [{"t": "projects", "id": "1000000001", "deleted": True}]})
    pull2 = client.post("/api/orgs/%s/sync" % org, headers=owner["h"], json={"device_no": d2, "since": seq}).json()
    assert pull2["changes"] == [{"t": "projects", "id": "1000000001", "deleted": True}]
    # stored encrypted: the plaintext never reaches the database
    db = client.app.state.db
    with db.tx() as c:
        payloads = [r["payload"] for r in c.all("SELECT payload FROM records WHERE payload IS NOT NULL")]
    assert payloads and all(p.startswith("v1:") and "990000" not in p for p in payloads)


def test_unknown_table_rejected(client):
    u = signup(client)
    org = u["orgs"][0]["id"]
    r = client.post("/api/orgs/%s/sync" % org, headers=u["h"],
                    json={"since": 0, "changes": [{"t": "users", "id": "1", "d": {}}]})
    assert r.status_code == 400


def test_invites_roles_and_viewer_is_read_only(client):
    owner, staff, viewer = signup(client), signup(client, company=""), signup(client, company="")
    org = owner["orgs"][0]["id"]
    code = client.post("/api/orgs/%s/invites" % org, headers=owner["h"], json={"role": "member"}).json()["code"]
    r = client.post("/api/invites/accept", headers=staff["h"], json={"code": code})
    assert r.status_code == 200 and r.json()["orgs"][0]["role"] == "member"
    assert client.post("/api/invites/accept", headers=viewer["h"], json={"code": code}).status_code == 400  # single use
    vcode = client.post("/api/orgs/%s/invites" % org, headers=owner["h"], json={"role": "viewer"}).json()["code"]
    client.post("/api/invites/accept", headers=viewer["h"], json={"code": vcode})
    push = {"since": 0, "changes": [{"t": "tiers", "id": "5", "d": {"id": 5, "name": "Ciments du Maroc"}}]}
    assert client.post("/api/orgs/%s/sync" % org, headers=staff["h"], json=push).status_code == 200
    assert client.post("/api/orgs/%s/sync" % org, headers=viewer["h"], json=push).status_code == 403
    pulled = client.post("/api/orgs/%s/sync" % org, headers=viewer["h"], json={"since": 0}).json()
    assert pulled["changes"][0]["d"]["name"] == "Ciments du Maroc"
    # a member cannot invite or change roles
    assert client.post("/api/orgs/%s/invites" % org, headers=staff["h"], json={"role": "member"}).status_code == 403
    members = client.get("/api/orgs/%s/members" % org, headers=owner["h"]).json()["members"]
    staff_id = [m["id"] for m in members if m["email"] == staff["email"]][0]
    owner_id = [m["id"] for m in members if m["email"] == owner["email"]][0]
    assert client.patch("/api/orgs/%s/members/%s" % (org, owner_id), headers=staff["h"],
                        json={"role": "viewer"}).status_code == 403
    # last owner cannot leave
    assert client.delete("/api/orgs/%s/members/%s" % (org, owner_id), headers=owner["h"]).status_code == 400
    assert client.delete("/api/orgs/%s/members/%s" % (org, staff_id), headers=owner["h"]).status_code == 200
    assert client.post("/api/orgs/%s/sync" % org, headers=staff["h"], json={"since": 0}).status_code == 404


def test_owner_resets_member_password(client):
    owner, staff = signup(client), signup(client, company="")
    org = owner["orgs"][0]["id"]
    code = client.post("/api/orgs/%s/invites" % org, headers=owner["h"], json={"role": "member"}).json()["code"]
    client.post("/api/invites/accept", headers=staff["h"], json={"code": code})
    sid = [m["id"] for m in client.get("/api/orgs/%s/members" % org, headers=owner["h"]).json()["members"]
           if m["email"] == staff["email"]][0]
    temp = client.post("/api/orgs/%s/members/%s/reset-password" % (org, sid), headers=owner["h"]).json()["temporary_password"]
    assert client.get("/api/me", headers=staff["h"]).status_code == 401           # old sessions revoked
    r = client.post("/api/auth/login", json={"email": staff["email"], "password": temp})
    assert r.status_code == 200 and r.json()["user"]["must_change_pw"]


def test_password_change_revokes_other_sessions(client):
    u = signup(client)
    other = client.post("/api/auth/login", json={"email": u["email"], "password": PW}).json()["token"]
    r = client.post("/api/auth/password", headers=u["h"], json={"current": PW, "new": "Nouveau-Pass-77"})
    assert r.status_code == 200
    assert client.get("/api/me", headers={"authorization": "Bearer " + other}).status_code == 401
    assert client.get("/api/me", headers=u["h"]).status_code == 200


def test_two_factor_login(client):
    u = signup(client)
    secret = client.post("/api/auth/2fa/setup", headers=u["h"]).json()["secret"]
    assert client.post("/api/auth/2fa/enable", headers=u["h"], json={"code": "000000"}).status_code == 400
    assert client.post("/api/auth/2fa/enable", headers=u["h"], json={"code": sec.totp_now(secret)}).status_code == 200
    r = client.post("/api/auth/login", json={"email": u["email"], "password": PW})
    assert r.status_code == 401 and r.json()["detail"] == "mfa_required"
    bad = "%06d" % ((int(sec.totp_now(secret)) + 1) % 1000000)
    assert client.post("/api/auth/login", json={"email": u["email"], "password": PW, "code": bad}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": u["email"], "password": PW, "code": sec.totp_now(secret)})
    assert ok.status_code == 200


def test_files_roundtrip_integrity_and_encryption(client):
    u = signup(client)
    org = u["orgs"][0]["id"]
    data = b"%PDF-1.4 CPS AO 12/2026 " * 100
    sha = hashlib.sha256(data).hexdigest()
    assert client.post("/api/orgs/%s/files/check" % org, headers=u["h"], json={"shas": [sha]}).json()["missing"] == [sha]
    assert client.put("/api/orgs/%s/files/%s" % (org, "0" * 64), headers=u["h"], content=data).status_code == 400
    assert client.put("/api/orgs/%s/files/%s" % (org, sha), headers=u["h"], content=data).status_code == 200
    assert client.post("/api/orgs/%s/files/check" % org, headers=u["h"], json={"shas": [sha]}).json()["missing"] == []
    assert client.get("/api/orgs/%s/files/%s" % (org, sha), headers=u["h"]).content == data
    with client.app.state.db.tx() as c:
        stored = bytes(c.one("SELECT data FROM files")["data"])
    assert b"CPS AO" not in stored


def test_admin_requires_two_factor(client):
    boss = signup(client, email="boss@safqa.ma")
    assert client.get("/api/admin/stats", headers=boss["h"]).status_code == 403
    secret = client.post("/api/auth/2fa/setup", headers=boss["h"]).json()["secret"]
    client.post("/api/auth/2fa/enable", headers=boss["h"], json={"code": sec.totp_now(secret)})
    stats = client.get("/api/admin/stats", headers=boss["h"])
    assert stats.status_code == 200 and stats.json()["users"] >= 1
    other = signup(client)
    assert client.get("/api/admin/stats", headers=other["h"]).status_code == 403
    # plan change is seen by the company
    org = other["orgs"][0]["id"]
    assert client.post("/api/admin/orgs/%s/plan" % org, headers=boss["h"],
                       json={"plan": "ENTREPRISE", "until": "2099-12-31"}).status_code == 200
    me = client.get("/api/me", headers=other["h"]).json()
    assert me["orgs"][0]["label"] == "Entreprise"
    # disabling a user cuts access immediately
    uid = client.get("/api/me", headers=other["h"]).json()["user"]["id"]
    client.post("/api/admin/users/%s/disable" % uid, headers=boss["h"])
    assert client.get("/api/me", headers=other["h"]).status_code == 401
    assert client.get("/api/admin/audit", headers=boss["h"]).json()["events"]
    key = client.post("/api/admin/license", headers=boss["h"],
                      json={"plan": "PRO", "until": "2099-01-31", "customer": "ATLAS"}).json()["key"]
    assert key.startswith("SAFQA-PRO-20990131-ATLAS-")


def test_licence_key_activation(client):
    from safqa import billing
    u = signup(client)
    org = u["orgs"][0]["id"]
    key = billing.make_key("ESSENTIEL", "20991231", "ATLAS", secret=b"lic-secret")
    me = client.post("/api/orgs/%s/license" % org, headers=u["h"], json={"key": key}).json()
    assert me["orgs"][0]["label"] == "Essentiel"
    forged = key[:-3] + "AAA"
    assert client.post("/api/orgs/%s/license" % org, headers=u["h"], json={"key": forged}).status_code == 400


def test_owner_can_export_and_delete_company(client):
    u = signup(client)
    org = u["orgs"][0]["id"]
    client.post("/api/orgs/%s/sync" % org, headers=u["h"],
                json={"since": 0, "changes": [{"t": "tiers", "id": "1", "d": {"id": 1, "name": "LPEE"}}]})
    exp = client.get("/api/orgs/%s/export" % org, headers=u["h"]).json()
    assert exp["data"]["tiers"][0]["name"] == "LPEE"
    assert client.post("/api/orgs/%s/delete" % org, headers=u["h"], json={"password": "faux"}).status_code == 400
    assert client.post("/api/orgs/%s/delete" % org, headers=u["h"], json={"password": PW}).status_code == 200
    assert client.get("/api/me", headers=u["h"]).json()["orgs"] == []


def test_ai_relay_needs_server_key(client):
    u = signup(client)
    r = client.post("/ai/v1/messages", headers={**u["h"], "x-safqa-org": str(u["orgs"][0]["id"])},
                    json={"model": "claude-opus-5-5", "messages": []})
    assert r.status_code == 503


def test_security_headers_and_admin_page(client):
    r = client.get("/admin")
    assert r.status_code == 200 and "Back-office" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert client.get("/healthz").json()["ok"]
    assert "09-08" in client.get("/confidentialite").text


def test_production_refuses_weak_configuration():
    with pytest.raises(RuntimeError):
        create_app(Settings(env="production", database_url="sqlite:///x.db", data_key="short"))


def test_totp_matches_rfc_6238_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"     # "12345678901234567890"
    assert sec.totp_now(secret, at=59) == "287082"
    assert sec.totp_now(secret, at=1111111109) == "081804"


def test_failed_login_is_recorded_in_audit(client):
    u = signup(client)
    client.post("/api/auth/login", json={"email": u["email"], "password": "mauvais-mot-2026"})
    with client.app.state.db.tx() as c:
        assert c.value("SELECT COUNT(*) AS n FROM audit WHERE action='login_failed'") == 1
        assert c.value("SELECT failed_logins FROM users WHERE email=?", (u["email"],)) == 1


def test_password_reset_by_email_code(client, monkeypatch):
    client.app.state.settings.smtp["host"] = "smtp.invalid"        # mail sending fails silently in tests
    monkeypatch.setattr(sec, "new_digits", lambda n=6: "123456")
    u = signup(client)
    assert client.post("/api/auth/reset/request", json={"email": u["email"]}).json()["email"]
    bad = client.post("/api/auth/reset/confirm", json={"email": u["email"], "code": "000000", "new": "Autre-Pass-2026"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/reset/confirm", json={"email": u["email"], "code": "123456", "new": "Autre-Pass-2026"})
    assert ok.status_code == 200
    assert client.get("/api/me", headers=u["h"]).status_code == 401              # sessions revoked
    assert client.post("/api/auth/login", json={"email": u["email"], "password": "Autre-Pass-2026"}).status_code == 200
    again = client.post("/api/auth/reset/confirm", json={"email": u["email"], "code": "123456", "new": "Encore-Pass-2026"})
    assert again.status_code == 400                                               # single use
