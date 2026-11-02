"""Safqa Cloud - accounts, companies, secure sync, AI relay and back-office.

Run locally:   uvicorn safqa_cloud.app:app --reload
Production:    see DEPLOIEMENT.md (Render blueprint or Docker Compose).
"""

import json
import logging
import os
import smtplib
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import security as sec
from .config import Settings
from .db import DB, Busy

try:                                    # plan definitions shared with the app
    from safqa import billing
except ImportError:                     # pragma: no cover - packaged without the app
    billing = None

log = logging.getLogger("safqa_cloud")
HERE = os.path.dirname(os.path.abspath(__file__))

SYNC_TABLES = {"projects", "documents", "checklist", "orders", "items", "decomptes", "receptions", "chat",
               "tiers", "tenders", "expenses", "budget_lines", "guarantees", "journal", "tasks",
               "measurements", "settings"}
ROLES = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
ROLE_LABELS = {"viewer": "Lecture seule", "member": "Collaborateur", "admin": "Administrateur", "owner": "Propriétaire"}
MAX_ROW = 4 * 1024 * 1024
MAX_FILE = 30 * 1024 * 1024
MAX_BODY = 40 * 1024 * 1024
PULL_PAGE = 1000
ALLOWED_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"}
API_URL = "https://api.anthropic.com"


def now():
    return int(time.time())


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------

def plan_info(org, today=None):
    today = today or date.today()
    plan, until = (org.get("plan") or "").upper(), org.get("plan_until")
    try:
        until_d = datetime.strptime(until, "%Y-%m-%d").date() if until else None
    except ValueError:
        until_d = None
    plans = billing.PLANS if billing else {}
    active = bool(plan) and (until_d is None or until_d >= today)
    if plan == "TRIAL" and active:
        lim, label = plans.get("PRO", {}), "Essai Pro"
    elif plan in plans and active:
        lim, label = plans[plan], plans[plan]["name"]
    else:
        lim, label, active = (billing.FREE_LIMITS if billing else {}), "Gratuit", False
    return {"plan": plan if active else "FREE", "label": label, "until": until, "active": active,
            "limits": {k: lim.get(k) for k in ("max_projects", "ai_analyses", "ai_questions", "export")}}


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------

class Signup(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)
    name: str = Field("", max_length=120)
    company: str = Field("", max_length=160)
    device: str = Field("", max_length=120)


class Login(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)
    code: str = Field("", max_length=10)
    device: str = Field("", max_length=120)


class PasswordChange(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class ResetRequest(BaseModel):
    email: str = Field(max_length=200)


class ResetConfirm(BaseModel):
    email: str = Field(max_length=200)
    code: str = Field(max_length=12)
    new: str = Field(max_length=200)


class Code(BaseModel):
    code: str = Field(max_length=40)
    password: str = Field("", max_length=200)


class OrgIn(BaseModel):
    name: str = Field(max_length=160)
    ice: str = Field("", max_length=30)


class RoleIn(BaseModel):
    role: str


class InviteIn(BaseModel):
    role: str = "member"
    days: int = 7


class LicenseIn(BaseModel):
    key: str = Field(max_length=80)


class DeviceIn(BaseModel):
    name: str = Field("", max_length=120)


class Change(BaseModel):
    t: str
    id: str = Field(max_length=120)
    d: Optional[Dict[str, Any]] = None
    deleted: bool = False


class SyncIn(BaseModel):
    device_no: int = 0
    since: int = 0
    changes: List[Change] = []


class ShaList(BaseModel):
    shas: List[str] = []


class PlanIn(BaseModel):
    plan: str
    until: Optional[str] = None


class LicenseMake(BaseModel):
    plan: str
    until: str
    customer: str


class DeleteIn(BaseModel):
    password: str = Field(max_length=200)


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------

def create_app(settings=None):
    settings = settings or Settings()
    problems = settings.check()
    if problems:
        raise RuntimeError("Configuration incomplète :\n- " + "\n- ".join(problems))
    db = DB(settings.database_url)
    vault = sec.Vault(settings.data_key)
    limiter = sec.RateLimiter()
    api = FastAPI(title="Safqa Cloud", version="1.0", docs_url=None, redoc_url=None, openapi_url=None)
    api.state.db, api.state.settings = db, settings

    @api.exception_handler(Busy)
    async def busy(request, exc):
        return JSONResponse({"detail": "Serveur très sollicité : réessayez dans quelques secondes."},
                            status_code=503, headers={"Retry-After": "5"})

    # ------------------------------------------------------------ middleware
    @api.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY:
            return JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)
        if not limiter.allow("ip:" + client_ip(request), 600, 60):
            return JSONResponse({"detail": "Trop de requêtes. Réessayez dans une minute."}, status_code=429)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        resp.headers["Cache-Control"] = resp.headers.get("Cache-Control", "no-store")
        if request.url.path.startswith(("/admin", "/confidentialite")):
            resp.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return resp

    def client_ip(request):
        if settings.trust_proxy:
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()[:64]
        return (request.client.host if request.client else "?")[:64]

    def audit(c, action, request=None, user_id=None, org_id=None, detail=None):
        c.execute("INSERT INTO audit(ts, user_id, org_id, action, ip, detail) VALUES (?,?,?,?,?,?)",
                  (now(), user_id, org_id, action, client_ip(request) if request else None,
                   json.dumps(detail, ensure_ascii=False)[:2000] if detail is not None else None))

    # ------------------------------------------------------------ auth helpers
    def auth(request: Request):
        h = request.headers.get("authorization", "")
        token = h[7:].strip() if h.lower().startswith("bearer ") else ""
        if not token or len(token) > 200:
            raise HTTPException(401, "Session expirée : reconnectez-vous.")
        t = now()
        with db.tx() as c:
            s = c.one("SELECT s.id AS sid, s.mfa, s.last_seen, s.expires_at, s.created_at AS s_created, u.* "
                      "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
                      (sec.token_hash(token),))
            if not s or s["expires_at"] < t or s["last_seen"] < t - settings.idle_days * 86400:
                if s:
                    c.execute("DELETE FROM sessions WHERE id=?", (s["sid"],))
                raise HTTPException(401, "Session expirée : reconnectez-vous.")
            if s["disabled"]:
                raise HTTPException(403, "Compte désactivé. Contactez le support.")
            if s["last_seen"] < t - 300:
                c.execute("UPDATE sessions SET last_seen=? WHERE id=?", (t, s["sid"]))
        return s

    def open_session(c, user, request, device, mfa):
        token = sec.new_token()
        t = now()
        c.execute("INSERT INTO sessions(user_id, token_hash, device, ip, mfa, created_at, last_seen, expires_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", (user["id"], sec.token_hash(token), (device or "")[:120],
                                               client_ip(request), 1 if mfa else 0, t, t,
                                               t + settings.session_days * 86400))
        c.execute("UPDATE users SET last_login=?, failed_logins=0, locked_until=0 WHERE id=?", (t, user["id"]))
        return token

    def membership(c, org_id, user, min_role="viewer"):
        m = c.one("SELECT m.role, o.* FROM members m JOIN orgs o ON o.id = m.org_id "
                  "WHERE m.org_id=? AND m.user_id=?", (org_id, user["id"]))
        if not m:
            raise HTTPException(404, "Entreprise introuvable.")
        if m["disabled"]:
            raise HTTPException(403, "Cet espace entreprise est suspendu. Contactez le support.")
        if ROLES[m["role"]] < ROLES[min_role]:
            raise HTTPException(403, "Droits insuffisants pour cette action.")
        return m

    def admin(user=Depends(auth)):
        if not user["is_admin"]:
            raise HTTPException(403, "Réservé à l'équipe Safqa.")
        if not user["totp_enabled"] or not user["mfa"]:
            raise HTTPException(403, "La double authentification est obligatoire pour le back-office.")
        return user

    def norm_email(e):
        e = (e or "").strip().lower()
        if "@" not in e or "." not in e.split("@")[-1] or len(e) > 200 or " " in e:
            raise HTTPException(400, "Adresse e-mail invalide.")
        return e

    def me_payload(c, user):
        orgs = c.all("SELECT m.role, o.id, o.name, o.ice, o.plan, o.plan_until, o.disabled FROM members m "
                     "JOIN orgs o ON o.id = m.org_id WHERE m.user_id=? ORDER BY o.id", (user["id"],))
        return {"user": {"id": user["id"], "email": user["email"], "name": user["name"],
                         "totp_enabled": bool(user["totp_enabled"]), "is_admin": bool(user["is_admin"]),
                         "must_change_pw": bool(user["must_change_pw"])},
                "orgs": [dict(id=o["id"], name=o["name"], ice=o["ice"], role=o["role"],
                              role_label=ROLE_LABELS[o["role"]], disabled=bool(o["disabled"]), **plan_info(o))
                         for o in orgs],
                "ai": bool(settings.anthropic_key)}

    def create_org(c, name, user, ice=""):
        name = (name or "").strip()
        if len(name) < 2:
            raise HTTPException(400, "Indiquez le nom de l'entreprise.")
        until = (date.today() + timedelta(days=settings.trial_days)).isoformat()
        oid = c.value("INSERT INTO orgs(name, ice, plan, plan_until, created_at) VALUES (?,?,?,?,?) RETURNING id",
                      (name[:160], (ice or "")[:30], "TRIAL", until, now()))
        c.execute("INSERT INTO members(org_id, user_id, role, created_at) VALUES (?,?,?,?)",
                  (oid, user["id"], "owner", now()))
        return oid

    def send_mail(to, subject, body):
        cfg = settings.smtp
        if not cfg["host"]:
            return False

        def go():
            try:
                msg = EmailMessage()
                msg["From"], msg["To"], msg["Subject"] = cfg["sender"], to, subject
                msg.set_content(body)
                with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
                    s.starttls()
                    if cfg["user"]:
                        s.login(cfg["user"], cfg["password"])
                    s.send_message(msg)
            except Exception:  # noqa: BLE001 - never leak to the client
                log.exception("mail")
        threading.Thread(target=go, daemon=True).start()
        return True

    # ------------------------------------------------------------ health & admin page
    @api.get("/healthz")
    def health():
        with db.tx() as c:
            c.value("SELECT 1 AS ok")
        return {"ok": True, "db": db.kind, "ai": bool(settings.anthropic_key)}

    @api.get("/")
    def root():
        return {"service": settings.public_name, "status": "ok"}

    @api.get("/admin")
    def admin_page():
        return FileResponse(os.path.join(HERE, "static", "admin.html"), headers={"Cache-Control": "no-store"})

    @api.get("/confidentialite")
    def privacy():
        return FileResponse(os.path.join(HERE, "static", "confidentialite.html"))

    @api.get("/admin/admin.js")
    def admin_js():
        return FileResponse(os.path.join(HERE, "static", "admin.js"), media_type="application/javascript")

    @api.get("/admin/admin.css")
    def admin_css():
        return FileResponse(os.path.join(HERE, "static", "admin.css"), media_type="text/css")

    # ------------------------------------------------------------ accounts
    @api.post("/api/auth/signup")
    def signup(body: Signup, request: Request):
        if not settings.allow_signup:
            raise HTTPException(403, "Les inscriptions sont fermées. Contactez Safqa.")
        if not limiter.allow("signup:" + client_ip(request), 10, 3600):
            raise HTTPException(429, "Trop d'inscriptions depuis cette connexion. Réessayez plus tard.")
        email = norm_email(body.email)
        problem = sec.password_problem(body.password, email)
        if problem:
            raise HTTPException(400, problem)
        pw = sec.hash_password(body.password)
        with db.tx() as c:
            if c.one("SELECT id FROM users WHERE email=?", (email,)):
                raise HTTPException(409, "Un compte existe déjà avec cette adresse. Connectez-vous.")
            uid = c.value("INSERT INTO users(email, name, pw_hash, is_admin, created_at) VALUES (?,?,?,?,?) "
                          "RETURNING id", (email, body.name.strip()[:120], pw,
                                           1 if email in settings.admin_emails else 0, now()))
            user = c.one("SELECT * FROM users WHERE id=?", (uid,))
            if body.company.strip():
                create_org(c, body.company, user)
            token = open_session(c, user, request, body.device, False)
            audit(c, "signup", request, uid)
            return {"token": token, **me_payload(c, user)}

    @api.post("/api/auth/login")
    def login(body: Login, request: Request):
        email = (body.email or "").strip().lower()
        if not limiter.allow("login:" + client_ip(request), 30, 300):
            raise HTTPException(429, "Trop de tentatives. Réessayez dans quelques minutes.")
        # Failures are recorded (counter, lockout, audit) and committed *before*
        # the error is raised: raising inside the transaction would roll them back.
        error = None
        with db.tx() as c:
            user = c.one("SELECT * FROM users WHERE email=?", (email,))
        # Slow, memory-hard check done without holding a database connection.
        if user:
            pw_ok = sec.verify_password(body.password, user["pw_hash"])
        else:
            sec.burn_time(body.password)
            pw_ok = False
        code_ok = bool(user) and user["totp_enabled"] and bool(body.code) and \
            sec.totp_verify(user["totp_secret"], body.code)
        with db.tx() as c:
            t = now()
            if user:
                user = c.one("SELECT * FROM users WHERE id=?", (user["id"],))   # fresh counters
            if not user:
                audit(c, "login_failed", request, detail={"email": email[:80]})
                error = HTTPException(401, "E-mail ou mot de passe incorrect.")
            elif user["locked_until"] > t:
                error = HTTPException(423, "Compte verrouillé après plusieurs erreurs. Réessayez dans %d min."
                                      % max(1, (user["locked_until"] - t) // 60))
            elif not pw_ok or (user["totp_enabled"] and body.code and not code_ok):
                fails = user["failed_logins"] + 1
                lock = t + 15 * 60 if fails >= 5 else 0
                c.execute("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?",
                          (0 if lock else fails, lock, user["id"]))
                audit(c, "login_failed" if not pw_ok else "mfa_failed", request, user["id"],
                      detail={"locked": bool(lock)})
                error = HTTPException(401, "E-mail ou mot de passe incorrect." if not pw_ok
                                      else "Code de vérification incorrect.")
            elif user["disabled"]:
                error = HTTPException(403, "Compte désactivé. Contactez le support.")
            elif user["totp_enabled"] and not body.code:
                error = HTTPException(401, "mfa_required")
            else:
                token = open_session(c, user, request, body.device, bool(user["totp_enabled"]))
                audit(c, "login", request, user["id"], detail={"device": body.device[:60]})
                result = {"token": token, **me_payload(c, user)}
        if error:
            raise error
        return result

    @api.post("/api/auth/logout")
    def logout(request: Request, user=Depends(auth)):
        with db.tx() as c:
            c.execute("DELETE FROM sessions WHERE id=?", (user["sid"],))
        return {"ok": True}

    @api.get("/api/me")
    def me(user=Depends(auth)):
        with db.tx() as c:
            return me_payload(c, user)

    @api.post("/api/auth/password")
    def change_password(body: PasswordChange, request: Request, user=Depends(auth)):
        if not sec.verify_password(body.current, user["pw_hash"]):
            raise HTTPException(400, "Mot de passe actuel incorrect.")
        problem = sec.password_problem(body.new, user["email"])
        if problem:
            raise HTTPException(400, problem)
        with db.tx() as c:
            c.execute("UPDATE users SET pw_hash=?, must_change_pw=0 WHERE id=?", (sec.hash_password(body.new), user["id"]))
            c.execute("DELETE FROM sessions WHERE user_id=? AND id<>?", (user["id"], user["sid"]))
            audit(c, "password_changed", request, user["id"])
        return {"ok": True}

    @api.post("/api/auth/reset/request")
    def reset_request(body: ResetRequest, request: Request):
        email = (body.email or "").strip().lower()
        if not limiter.allow("reset:" + client_ip(request), 5, 3600):
            raise HTTPException(429, "Trop de demandes. Réessayez plus tard.")
        with db.tx() as c:
            user = c.one("SELECT * FROM users WHERE email=?", (email,))
            if user and not user["disabled"] and settings.smtp["host"]:
                code = sec.new_digits(6)
                c.execute("UPDATE reset_codes SET used=1 WHERE user_id=?", (user["id"],))
                c.execute("INSERT INTO reset_codes(user_id, code_hash, expires_at) VALUES (?,?,?)",
                          (user["id"], sec.token_hash(code), now() + 900))
                send_mail(email, "Safqa - code de réinitialisation",
                                 "Votre code Safqa : %s\nIl expire dans 15 minutes.\n"
                                 "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message." % code)
                audit(c, "reset_requested", request, user["id"])
        return {"ok": True, "email": bool(settings.smtp["host"]),
                "message": "Si ce compte existe, un code a été envoyé par e-mail." if settings.smtp["host"] else
                "Demandez au propriétaire de votre espace entreprise (ou au support Safqa) de réinitialiser "
                "votre mot de passe."}

    @api.post("/api/auth/reset/confirm")
    def reset_confirm(body: ResetConfirm, request: Request):
        email = (body.email or "").strip().lower()
        with db.tx() as c:
            user = c.one("SELECT * FROM users WHERE email=?", (email,))
            rc = user and c.one("SELECT * FROM reset_codes WHERE user_id=? AND used=0 ORDER BY id DESC LIMIT 1",
                                (user["id"],))
            if not rc or rc["expires_at"] < now() or rc["attempts"] >= 5:
                raise HTTPException(400, "Code invalide ou expiré.")
            if sec.token_hash(body.code.strip()) != rc["code_hash"]:
                c.execute("UPDATE reset_codes SET attempts=attempts+1 WHERE id=?", (rc["id"],))
                wrong = True
            else:
                wrong = False
        if wrong:
            raise HTTPException(400, "Code invalide ou expiré.")
        with db.tx() as c:
            rc = c.one("SELECT * FROM reset_codes WHERE id=? AND used=0", (rc["id"],))
            if not rc:
                raise HTTPException(400, "Code invalide ou expiré.")
            problem = sec.password_problem(body.new, email)
            if problem:
                raise HTTPException(400, problem)
            c.execute("UPDATE reset_codes SET used=1 WHERE id=?", (rc["id"],))
            c.execute("UPDATE users SET pw_hash=?, failed_logins=0, locked_until=0, must_change_pw=0 WHERE id=?",
                      (sec.hash_password(body.new), user["id"]))
            c.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            audit(c, "password_reset", request, user["id"])
        return {"ok": True}

    @api.post("/api/auth/2fa/setup")
    def totp_setup(user=Depends(auth)):
        if user["totp_enabled"]:
            raise HTTPException(400, "La double authentification est déjà active.")
        secret = sec.totp_secret()
        with db.tx() as c:
            c.execute("UPDATE users SET totp_secret=? WHERE id=?", (secret, user["id"]))
        return {"secret": secret, "uri": sec.totp_uri(secret, user["email"])}

    @api.post("/api/auth/2fa/enable")
    def totp_enable(body: Code, request: Request, user=Depends(auth)):
        if not user["totp_secret"] or not sec.totp_verify(user["totp_secret"], body.code):
            raise HTTPException(400, "Code incorrect : vérifiez l'heure de votre téléphone et réessayez.")
        with db.tx() as c:
            c.execute("UPDATE users SET totp_enabled=1 WHERE id=?", (user["id"],))
            c.execute("UPDATE sessions SET mfa=1 WHERE id=?", (user["sid"],))
            c.execute("DELETE FROM sessions WHERE user_id=? AND id<>?", (user["id"], user["sid"]))
            audit(c, "mfa_enabled", request, user["id"])
        return {"ok": True}

    @api.post("/api/auth/2fa/disable")
    def totp_disable(body: Code, request: Request, user=Depends(auth)):
        if not sec.verify_password(body.password, user["pw_hash"]) or not sec.totp_verify(user["totp_secret"], body.code):
            raise HTTPException(400, "Mot de passe ou code incorrect.")
        if user["is_admin"]:
            raise HTTPException(400, "La double authentification est obligatoire pour les administrateurs.")
        with db.tx() as c:
            c.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE id=?", (user["id"],))
            audit(c, "mfa_disabled", request, user["id"])
        return {"ok": True}

    @api.get("/api/auth/sessions")
    def sessions(user=Depends(auth)):
        with db.tx() as c:
            rows = c.all("SELECT id, device, ip, created_at, last_seen FROM sessions WHERE user_id=? "
                         "ORDER BY last_seen DESC", (user["id"],))
        for r in rows:
            r["current"] = r["id"] == user["sid"]
        return {"sessions": rows}

    @api.delete("/api/auth/sessions/{sid}")
    def revoke_session(sid: int, request: Request, user=Depends(auth)):
        with db.tx() as c:
            c.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (sid, user["id"]))
            audit(c, "session_revoked", request, user["id"])
        return {"ok": True}

    # ------------------------------------------------------------ companies
    @api.post("/api/orgs")
    def new_org(body: OrgIn, request: Request, user=Depends(auth)):
        with db.tx() as c:
            if (c.value("SELECT COUNT(*) AS n FROM members WHERE user_id=? AND role='owner'", (user["id"],)) or 0) >= 5:
                raise HTTPException(400, "Nombre maximal d'espaces entreprise atteint.")
            oid = create_org(c, body.name, user, body.ice)
            audit(c, "org_created", request, user["id"], oid)
            return {"id": oid, **me_payload(c, user)}

    @api.patch("/api/orgs/{org_id}")
    def edit_org(org_id: int, body: OrgIn, request: Request, user=Depends(auth)):
        with db.tx() as c:
            membership(c, org_id, user, "admin")
            c.execute("UPDATE orgs SET name=?, ice=? WHERE id=?", (body.name.strip()[:160], body.ice[:30], org_id))
            audit(c, "org_updated", request, user["id"], org_id)
        return {"ok": True}

    @api.get("/api/orgs/{org_id}/members")
    def members(org_id: int, user=Depends(auth)):
        with db.tx() as c:
            membership(c, org_id, user)
            rows = c.all("SELECT u.id, u.email, u.name, u.last_login, u.totp_enabled, m.role FROM members m "
                         "JOIN users u ON u.id = m.user_id WHERE m.org_id=? ORDER BY m.created_at", (org_id,))
        for r in rows:
            r["role_label"] = ROLE_LABELS[r["role"]]
            r["me"] = r["id"] == user["id"]
        return {"members": rows, "roles": ROLE_LABELS}

    @api.patch("/api/orgs/{org_id}/members/{uid}")
    def set_role(org_id: int, uid: int, body: RoleIn, request: Request, user=Depends(auth)):
        if body.role not in ROLES:
            raise HTTPException(400, "Rôle inconnu.")
        with db.tx() as c:
            m = membership(c, org_id, user, "admin")
            target = c.one("SELECT role FROM members WHERE org_id=? AND user_id=?", (org_id, uid))
            if not target:
                raise HTTPException(404, "Membre introuvable.")
            if (body.role == "owner" or target["role"] == "owner") and m["role"] != "owner":
                raise HTTPException(403, "Seul le propriétaire peut modifier ce rôle.")
            if target["role"] == "owner" and body.role != "owner":
                owners = c.value("SELECT COUNT(*) AS n FROM members WHERE org_id=? AND role='owner'", (org_id,))
                if owners <= 1:
                    raise HTTPException(400, "L'espace doit garder au moins un propriétaire.")
            c.execute("UPDATE members SET role=? WHERE org_id=? AND user_id=?", (body.role, org_id, uid))
            audit(c, "role_changed", request, user["id"], org_id, {"user": uid, "role": body.role})
        return {"ok": True}

    @api.delete("/api/orgs/{org_id}/members/{uid}")
    def remove_member(org_id: int, uid: int, request: Request, user=Depends(auth)):
        with db.tx() as c:
            m = membership(c, org_id, user, "viewer" if uid == user["id"] else "admin")
            target = c.one("SELECT role FROM members WHERE org_id=? AND user_id=?", (org_id, uid))
            if not target:
                raise HTTPException(404, "Membre introuvable.")
            if target["role"] == "owner":
                owners = c.value("SELECT COUNT(*) AS n FROM members WHERE org_id=? AND role='owner'", (org_id,))
                if owners <= 1:
                    raise HTTPException(400, "Le dernier propriétaire ne peut pas quitter l'espace.")
                if m["role"] != "owner":
                    raise HTTPException(403, "Seul un propriétaire peut retirer un propriétaire.")
            c.execute("DELETE FROM members WHERE org_id=? AND user_id=?", (org_id, uid))
            audit(c, "member_removed", request, user["id"], org_id, {"user": uid})
        return {"ok": True}

    @api.post("/api/orgs/{org_id}/members/{uid}/reset-password")
    def owner_reset(org_id: int, uid: int, request: Request, user=Depends(auth)):
        with db.tx() as c:
            membership(c, org_id, user, "owner")
            if not c.one("SELECT 1 AS x FROM members WHERE org_id=? AND user_id=?", (org_id, uid)) or uid == user["id"]:
                raise HTTPException(404, "Membre introuvable.")
            temp = sec.new_code(4) + "-" + sec.new_code(4) + "-" + sec.new_digits(2)
            c.execute("UPDATE users SET pw_hash=?, must_change_pw=1, failed_logins=0, locked_until=0 WHERE id=?",
                      (sec.hash_password(temp), uid))
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            audit(c, "member_password_reset", request, user["id"], org_id, {"user": uid})
        return {"temporary_password": temp}

    @api.post("/api/orgs/{org_id}/invites")
    def invite(org_id: int, body: InviteIn, request: Request, user=Depends(auth)):
        if body.role not in ROLES or body.role == "owner":
            raise HTTPException(400, "Rôle d'invitation invalide.")
        code = sec.new_code(4) + "-" + sec.new_code(4) + "-" + sec.new_code(4)
        days = max(1, min(30, body.days))
        with db.tx() as c:
            membership(c, org_id, user, "admin")
            c.execute("INSERT INTO invites(org_id, code_hash, role, created_by, expires_at) VALUES (?,?,?,?,?)",
                      (org_id, sec.token_hash(code), body.role, user["id"], now() + days * 86400))
            audit(c, "invite_created", request, user["id"], org_id, {"role": body.role})
        return {"code": code, "role": body.role, "expires_days": days}

    @api.post("/api/invites/accept")
    def accept(body: Code, request: Request, user=Depends(auth)):
        if not limiter.allow("invite:%s" % user["id"], 10, 3600):
            raise HTTPException(429, "Trop de tentatives.")
        code = body.code.strip().upper()
        with db.tx() as c:
            inv = c.one("SELECT * FROM invites WHERE code_hash=?", (sec.token_hash(code),))
            if not inv or inv["used_by"] or inv["expires_at"] < now():
                raise HTTPException(400, "Code d'invitation invalide ou expiré.")
            if not c.one("SELECT 1 AS x FROM members WHERE org_id=? AND user_id=?", (inv["org_id"], user["id"])):
                c.execute("INSERT INTO members(org_id, user_id, role, created_at) VALUES (?,?,?,?)",
                          (inv["org_id"], user["id"], inv["role"], now()))
            c.execute("UPDATE invites SET used_by=?, used_at=? WHERE id=?", (user["id"], now(), inv["id"]))
            audit(c, "invite_accepted", request, user["id"], inv["org_id"])
            return {"org_id": inv["org_id"], **me_payload(c, user)}

    @api.post("/api/orgs/{org_id}/license")
    def activate(org_id: int, body: LicenseIn, request: Request, user=Depends(auth)):
        if not billing or not settings.license_secret:
            raise HTTPException(400, "Activation par clé non configurée sur ce serveur.")
        ok, plan, expiry, msg = billing.check_key(body.key, secret=settings.license_secret.encode())
        if not ok:
            raise HTTPException(400, msg)
        with db.tx() as c:
            membership(c, org_id, user, "admin")
            c.execute("UPDATE orgs SET plan=?, plan_until=? WHERE id=?", (plan, expiry.isoformat(), org_id))
            audit(c, "license_activated", request, user["id"], org_id, {"plan": plan, "until": expiry.isoformat()})
            return me_payload(c, user)

    @api.post("/api/orgs/{org_id}/devices")
    def register_device(org_id: int, body: DeviceIn, user=Depends(auth)):
        with db.tx() as c:
            membership(c, org_id, user)
            no = c.value("UPDATE orgs SET device_seq = device_seq + 1 WHERE id=? RETURNING device_seq", (org_id,))
            c.execute("INSERT INTO devices(org_id, user_id, device_no, name, created_at) VALUES (?,?,?,?,?)",
                      (org_id, user["id"], no, body.name[:120], now()))
            rows = c.value("SELECT COUNT(*) AS n FROM records WHERE org_id=? AND deleted=0", (org_id,))
        return {"device_no": no, "rows": rows}

    # ------------------------------------------------------------ sync
    @api.post("/api/orgs/{org_id}/sync")
    def sync(org_id: int, body: SyncIn, user=Depends(auth)):
        if len(body.changes) > 2000:
            raise HTTPException(413, "Trop de modifications en une fois.")
        with db.tx() as c:
            m = membership(c, org_id, user)
            if body.changes:
                if ROLES[m["role"]] < ROLES["member"]:
                    raise HTTPException(403, "Accès en lecture seule : vos modifications ne sont pas envoyées.")
                seq = c.value("UPDATE orgs SET seq = seq + ? WHERE id=? RETURNING seq", (len(body.changes), org_id))
                first = seq - len(body.changes) + 1
                t = now()
                for i, ch in enumerate(body.changes):
                    if ch.t not in SYNC_TABLES:
                        raise HTTPException(400, "Table inconnue : %s" % ch.t[:40])
                    payload = None
                    if not ch.deleted:
                        raw = json.dumps(ch.d or {}, ensure_ascii=False, separators=(",", ":"))
                        if len(raw) > MAX_ROW:
                            raise HTTPException(413, "Enregistrement trop volumineux (%s)." % ch.t)
                        payload = vault.seal_text(raw, "%s|%s|%s" % (org_id, ch.t, ch.id))
                    c.execute("INSERT INTO records(org_id, tbl, rid, seq, deleted, payload, updated_at, updated_by, device_no) "
                              "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT (org_id, tbl, rid) DO UPDATE SET "
                              "seq=excluded.seq, deleted=excluded.deleted, payload=excluded.payload, "
                              "updated_at=excluded.updated_at, updated_by=excluded.updated_by, device_no=excluded.device_no",
                              (org_id, ch.t, ch.id, first + i, 1 if ch.deleted else 0, payload, t, user["id"],
                               body.device_no))
            rows = c.all("SELECT tbl, rid, seq, deleted, payload, device_no FROM records WHERE org_id=? AND seq>? "
                         "ORDER BY seq LIMIT ?", (org_id, body.since, PULL_PAGE))
            if body.device_no:
                c.execute("UPDATE devices SET last_sync=? WHERE org_id=? AND device_no=?",
                          (now(), org_id, body.device_no))
        out, last = [], body.since
        for r in rows:
            last = r["seq"]
            if body.device_no and r["device_no"] == body.device_no:
                continue
            item = {"t": r["tbl"], "id": r["rid"], "deleted": bool(r["deleted"])}
            if not r["deleted"]:
                item["d"] = json.loads(vault.open_text(r["payload"], "%s|%s|%s" % (org_id, r["tbl"], r["rid"])))
            out.append(item)
        return {"changes": out, "seq": last, "more": len(rows) == PULL_PAGE, "plan": plan_info(m),
                "role": m["role"]}

    # ------------------------------------------------------------ files (CPS, PDF...)
    def check_sha(sha):
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise HTTPException(400, "Empreinte invalide.")

    @api.post("/api/orgs/{org_id}/files/check")
    def files_check(org_id: int, body: ShaList, user=Depends(auth)):
        shas = [s for s in body.shas[:500]]
        for s in shas:
            check_sha(s)
        with db.tx() as c:
            membership(c, org_id, user)
            have = {r["sha"] for r in c.all("SELECT sha FROM files WHERE org_id=?", (org_id,))} if shas else set()
        return {"missing": [s for s in shas if s not in have]}

    @api.put("/api/orgs/{org_id}/files/{sha}")
    async def file_put(org_id: int, sha: str, request: Request, user=Depends(auth)):
        check_sha(sha)
        data = await request.body()
        if len(data) > MAX_FILE:
            raise HTTPException(413, "Fichier trop volumineux (30 Mo maximum).")
        import hashlib
        if hashlib.sha256(data).hexdigest() != sha:
            raise HTTPException(400, "Fichier corrompu pendant l'envoi.")
        blob = vault.seal(data, "%s|file|%s" % (org_id, sha))
        with db.tx() as c:
            m = membership(c, org_id, user, "member")
            if c.one("SELECT 1 AS x FROM files WHERE org_id=? AND sha=?", (org_id, sha)):
                return {"ok": True}
            if m["storage_bytes"] + len(data) > settings.storage_mb * 1024 * 1024:
                raise HTTPException(507, "Espace de stockage de l'entreprise plein.")
            c.execute("INSERT INTO files(org_id, sha, size, data, created_at) VALUES (?,?,?,?,?)",
                      (org_id, sha, len(data), blob, now()))
            c.execute("UPDATE orgs SET storage_bytes = storage_bytes + ? WHERE id=?", (len(data), org_id))
        return {"ok": True}

    @api.get("/api/orgs/{org_id}/files/{sha}")
    def file_get(org_id: int, sha: str, user=Depends(auth)):
        check_sha(sha)
        with db.tx() as c:
            membership(c, org_id, user)
            row = c.one("SELECT data FROM files WHERE org_id=? AND sha=?", (org_id, sha))
        if not row:
            raise HTTPException(404, "Fichier introuvable.")
        return Response(vault.open(bytes(row["data"]), "%s|file|%s" % (org_id, sha)),
                        media_type="application/octet-stream")

    # ------------------------------------------------------------ company audit, export, deletion
    @api.get("/api/orgs/{org_id}/audit")
    def org_audit(org_id: int, user=Depends(auth)):
        with db.tx() as c:
            membership(c, org_id, user, "admin")
            rows = c.all("SELECT a.ts, a.action, a.ip, a.detail, u.email FROM audit a LEFT JOIN users u "
                         "ON u.id = a.user_id WHERE a.org_id=? ORDER BY a.id DESC LIMIT 200", (org_id,))
        return {"events": rows}

    @api.get("/api/orgs/{org_id}/export")
    def export(org_id: int, request: Request, user=Depends(auth)):
        with db.tx() as c:
            m = membership(c, org_id, user, "owner")
            rows = c.all("SELECT tbl, rid, payload FROM records WHERE org_id=? AND deleted=0 ORDER BY tbl, rid", (org_id,))
            audit(c, "org_exported", request, user["id"], org_id)
        data = {}
        for r in rows:
            data.setdefault(r["tbl"], []).append(
                json.loads(vault.open_text(r["payload"], "%s|%s|%s" % (org_id, r["tbl"], r["rid"]))))
        return JSONResponse({"company": m["name"], "exported_at": datetime.utcnow().isoformat() + "Z", "data": data},
                            headers={"Content-Disposition": 'attachment; filename="safqa-export.json"'})

    @api.post("/api/orgs/{org_id}/delete")
    def delete_org(org_id: int, body: DeleteIn, request: Request, user=Depends(auth)):
        if not sec.verify_password(body.password, user["pw_hash"]):
            raise HTTPException(400, "Mot de passe incorrect.")
        with db.tx() as c:
            membership(c, org_id, user, "owner")
            for t in ("records", "files", "members", "invites", "devices", "ai_usage"):
                c.execute("DELETE FROM %s WHERE org_id=?" % t, (org_id,))
            c.execute("DELETE FROM orgs WHERE id=?", (org_id,))
            audit(c, "org_deleted", request, user["id"], org_id)
        return {"ok": True}

    # ------------------------------------------------------------ AI relay
    @api.post("/ai/v1/messages")
    async def ai_messages(request: Request):
        user = auth(request)
        if not settings.anthropic_key:
            raise HTTPException(503, "L'IA n'est pas encore activée sur ce serveur.")
        try:
            org_id = int(request.headers.get("x-safqa-org", "0"))
        except ValueError:
            raise HTTPException(400, "Entreprise manquante.")
        raw = await request.body()
        if len(raw) > 16 * 1024 * 1024:
            raise HTTPException(413, "Requête trop volumineuse.")
        try:
            body = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "JSON invalide.")
        if body.get("model") not in ALLOWED_MODELS:
            raise HTTPException(400, "Modèle non autorisé.")
        kind = "ai_analysis" if (body.get("output_config") or {}).get("format") else "ai_question"
        month = datetime.now().strftime("%Y-%m")
        with db.tx() as c:
            m = membership(c, org_id, user, "member")
            limit = plan_info(m)["limits"]["ai_analyses" if kind == "ai_analysis" else "ai_questions"] or 0
            used = c.value("SELECT n FROM ai_usage WHERE org_id=? AND month=? AND kind=?", (org_id, month, kind)) or 0
            if used >= limit:
                raise HTTPException(402, "Quota IA mensuel de votre abonnement atteint (%d)." % limit)
            c.execute("INSERT INTO ai_usage(org_id, month, kind, n) VALUES (?,?,?,1) ON CONFLICT (org_id, month, kind) "
                      "DO UPDATE SET n = ai_usage.n + 1", (org_id, month, kind))
        body["max_tokens"] = min(int(body.get("max_tokens") or 16000), 32000)
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() in ("content-type", "anthropic-version", "anthropic-beta", "accept")}
        headers["x-api-key"] = settings.anthropic_key
        req = urllib.request.Request(API_URL + "/v1/messages", data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            upstream = urllib.request.urlopen(req, timeout=900)
        except urllib.error.HTTPError as exc:
            return Response(exc.read(), status_code=exc.code, media_type="application/json")
        except OSError as exc:
            raise HTTPException(502, "Service IA injoignable : %s" % exc)

        def stream():
            with upstream:
                while True:
                    chunk = upstream.read1(65536) if hasattr(upstream, "read1") else upstream.read(65536)
                    if not chunk:
                        break
                    yield chunk
        return StreamingResponse(stream(), media_type=upstream.headers.get("content-type", "text/event-stream"))

    # ------------------------------------------------------------ back-office API
    @api.get("/api/admin/stats")
    def admin_stats(user=Depends(admin)):
        t = now()
        month = datetime.now().strftime("%Y-%m")
        with db.tx() as c:
            orgs = c.all("SELECT plan, plan_until FROM orgs")
            plans = {}
            for o in orgs:
                p = plan_info(o)["label"]
                plans[p] = plans.get(p, 0) + 1
            mrr = sum((billing.PLANS.get(plan_info(o)["plan"], {}).get("price_dh") or 0) for o in orgs) if billing else 0
            return {
                "users": c.value("SELECT COUNT(*) AS n FROM users"),
                "active_7d": c.value("SELECT COUNT(*) AS n FROM users WHERE last_login>?", (t - 7 * 86400,)),
                "signups_30d": c.value("SELECT COUNT(*) AS n FROM users WHERE created_at>?", (t - 30 * 86400,)),
                "orgs": len(orgs), "plans": plans, "mrr_dh": mrr,
                "rows": c.value("SELECT COUNT(*) AS n FROM records WHERE deleted=0"),
                "storage_mb": round((c.value("SELECT COALESCE(SUM(size),0) AS n FROM files") or 0) / 1048576, 1),
                "ai_month": c.value("SELECT COALESCE(SUM(n),0) AS n FROM ai_usage WHERE month=?", (month,)),
                "failed_logins_24h": c.value("SELECT COUNT(*) AS n FROM audit WHERE action='login_failed' AND ts>?",
                                             (t - 86400,)),
                "locked": c.value("SELECT COUNT(*) AS n FROM users WHERE locked_until>?", (t,)),
                "db": db.kind, "ai": bool(settings.anthropic_key), "smtp": bool(settings.smtp["host"]),
                "license": bool(settings.license_secret)}

    @api.get("/api/admin/users")
    def admin_users(q: str = "", user=Depends(admin)):
        like = "%" + q.strip().lower()[:80] + "%"
        with db.tx() as c:
            rows = c.all("SELECT id, email, name, is_admin, disabled, totp_enabled, failed_logins, locked_until, "
                         "created_at, last_login FROM users WHERE LOWER(email) LIKE ? OR LOWER(COALESCE(name,'')) LIKE ? "
                         "ORDER BY id DESC LIMIT 200", (like, like))
            for r in rows:
                r["orgs"] = c.all("SELECT o.id, o.name, m.role FROM members m JOIN orgs o ON o.id=m.org_id "
                                  "WHERE m.user_id=?", (r["id"],))
        return {"users": rows}

    @api.post("/api/admin/users/{uid}/{action}")
    def admin_user_action(uid: int, action: str, request: Request, user=Depends(admin)):
        out = {"ok": True}
        with db.tx() as c:
            target = c.one("SELECT * FROM users WHERE id=?", (uid,))
            if not target:
                raise HTTPException(404, "Utilisateur introuvable.")
            if action in ("disable", "enable"):
                if uid == user["id"]:
                    raise HTTPException(400, "Vous ne pouvez pas désactiver votre propre compte.")
                c.execute("UPDATE users SET disabled=? WHERE id=?", (1 if action == "disable" else 0, uid))
                if action == "disable":
                    c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            elif action == "unlock":
                c.execute("UPDATE users SET failed_logins=0, locked_until=0 WHERE id=?", (uid,))
            elif action == "revoke":
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            elif action == "reset-password":
                temp = sec.new_code(4) + "-" + sec.new_code(4) + "-" + sec.new_digits(2)
                c.execute("UPDATE users SET pw_hash=?, must_change_pw=1, failed_logins=0, locked_until=0 WHERE id=?",
                          (sec.hash_password(temp), uid))
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                out["temporary_password"] = temp
            elif action == "reset-2fa":
                if target["is_admin"]:
                    raise HTTPException(400, "Impossible pour un administrateur.")
                c.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE id=?", (uid,))
            else:
                raise HTTPException(404, "Action inconnue.")
            audit(c, "admin_user_" + action, request, user["id"], detail={"user": uid})
        return out

    @api.get("/api/admin/orgs")
    def admin_orgs(q: str = "", user=Depends(admin)):
        like = "%" + q.strip().lower()[:80] + "%"
        month = datetime.now().strftime("%Y-%m")
        with db.tx() as c:
            rows = c.all("SELECT * FROM orgs WHERE LOWER(name) LIKE ? OR COALESCE(ice,'') LIKE ? ORDER BY id DESC LIMIT 200",
                         (like, like))
            for r in rows:
                r.update(plan_info(r))
                r["members"] = c.value("SELECT COUNT(*) AS n FROM members WHERE org_id=?", (r["id"],))
                r["owner"] = c.value("SELECT u.email FROM members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? "
                                     "AND m.role='owner' ORDER BY m.created_at LIMIT 1", (r["id"],))
                r["records"] = c.value("SELECT COUNT(*) AS n FROM records WHERE org_id=? AND deleted=0", (r["id"],))
                r["ai_month"] = c.value("SELECT COALESCE(SUM(n),0) AS n FROM ai_usage WHERE org_id=? AND month=?",
                                        (r["id"], month))
        return {"orgs": rows, "plans": ["TRIAL", "ESSENTIEL", "PRO", "ENTREPRISE", "FREE"]}

    @api.post("/api/admin/orgs/{org_id}/plan")
    def admin_plan(org_id: int, body: PlanIn, request: Request, user=Depends(admin)):
        plan = body.plan.upper()
        if plan not in ("TRIAL", "ESSENTIEL", "PRO", "ENTREPRISE", "FREE"):
            raise HTTPException(400, "Formule inconnue.")
        if body.until:
            try:
                datetime.strptime(body.until, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(400, "Date invalide (AAAA-MM-JJ).")
        with db.tx() as c:
            c.execute("UPDATE orgs SET plan=?, plan_until=? WHERE id=?",
                      (None if plan == "FREE" else plan, body.until, org_id))
            audit(c, "admin_plan", request, user["id"], org_id, {"plan": plan, "until": body.until})
        return {"ok": True}

    @api.post("/api/admin/orgs/{org_id}/{action}")
    def admin_org_action(org_id: int, action: str, request: Request, user=Depends(admin)):
        if action not in ("disable", "enable"):
            raise HTTPException(404, "Action inconnue.")
        with db.tx() as c:
            c.execute("UPDATE orgs SET disabled=? WHERE id=?", (1 if action == "disable" else 0, org_id))
            audit(c, "admin_org_" + action, request, user["id"], org_id)
        return {"ok": True}

    @api.get("/api/admin/audit")
    def admin_audit(q: str = "", user=Depends(admin)):
        like = "%" + q.strip().lower()[:80] + "%"
        with db.tx() as c:
            rows = c.all("SELECT a.id, a.ts, a.action, a.ip, a.detail, a.org_id, u.email FROM audit a LEFT JOIN users u "
                         "ON u.id=a.user_id WHERE LOWER(a.action) LIKE ? OR LOWER(COALESCE(u.email,'')) LIKE ? "
                         "OR COALESCE(a.ip,'') LIKE ? ORDER BY a.id DESC LIMIT 300", (like, like, like))
        return {"events": rows}

    @api.post("/api/admin/license")
    def admin_license(body: LicenseMake, request: Request, user=Depends(admin)):
        if not billing or not settings.license_secret:
            raise HTTPException(400, "SAFQA_LICENSE_SECRET n'est pas configuré.")
        try:
            key = billing.make_key(body.plan, datetime.strptime(body.until, "%Y-%m-%d").date(), body.customer,
                                   secret=settings.license_secret.encode())
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        with db.tx() as c:
            audit(c, "admin_license", request, user["id"], detail={"plan": body.plan, "customer": body.customer[:40]})
        return {"key": key}

    return api


def _make_default():
    try:
        return create_app()
    except RuntimeError as exc:           # readable message in the hosting logs
        log.error(str(exc))
        raise


app = _make_default() if os.environ.get("SAFQA_NO_AUTOAPP") != "1" else None
