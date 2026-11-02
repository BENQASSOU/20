"""Safqa Cloud client: account, company space, secure synchronisation.

Offline-first: the phone keeps working without network; every change is
queued locally (storage.sync_dirty) and exchanged with the server when the
connection is back.  Conflicts are resolved record by record, the last
change received by the server wins.
"""

import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.request

from . import config

TIMEOUT = 40
BATCH = 400


class CloudError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def _ssl():
    from .ai import _ssl_context
    return _ssl_context()


def default_url():
    return (getattr(config, "CLOUD_URL", "") or "").rstrip("/")


class Cloud:
    def __init__(self, url, token=""):
        self.url = (url or "").strip().rstrip("/")
        self.token = token or ""

    def request(self, method, path, body=None, raw=None, timeout=TIMEOUT, expect_json=True):
        if not self.url:
            raise CloudError("Adresse du serveur Safqa Cloud non configurée.")
        if not self.url.startswith("https://") and not self.url.startswith(("http://127.0.0.1", "http://localhost")):
            raise CloudError("Connexion refusée : le serveur doit utiliser HTTPS.")
        headers = {"accept": "application/json", "user-agent": "SafqaERP"}
        data = None
        if raw is not None:
            data, headers["content-type"] = raw, "application/octet-stream"
        elif body is not None:
            data, headers["content-type"] = json.dumps(body).encode(), "application/json"
        if self.token:
            headers["authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            ctx = _ssl() if self.url.startswith("https://") else None
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read() or b"{}").get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, list):          # validation error
                detail = "Données invalides."
            raise CloudError(detail or "Erreur du serveur (%s)." % exc.code, exc.code)
        except (urllib.error.URLError, OSError) as exc:
            raise CloudError("Serveur injoignable (%s). Vérifiez votre connexion Internet."
                             % getattr(exc, "reason", exc))
        if not expect_json:
            return payload
        return json.loads(payload or b"{}")

    # ------------------------------------------------------------ account
    def signup(self, email, password, name, company, device):
        return self.request("POST", "/api/auth/signup", {"email": email, "password": password, "name": name,
                                                         "company": company, "device": device})

    def login(self, email, password, code="", device=""):
        return self.request("POST", "/api/auth/login", {"email": email, "password": password, "code": code,
                                                        "device": device})

    def logout(self):
        return self.request("POST", "/api/auth/logout")

    def me(self):
        return self.request("GET", "/api/me")

    def change_password(self, current, new):
        return self.request("POST", "/api/auth/password", {"current": current, "new": new})

    def reset_request(self, email):
        return self.request("POST", "/api/auth/reset/request", {"email": email})

    def reset_confirm(self, email, code, new):
        return self.request("POST", "/api/auth/reset/confirm", {"email": email, "code": code, "new": new})

    def totp_setup(self):
        return self.request("POST", "/api/auth/2fa/setup")

    def totp_enable(self, code):
        return self.request("POST", "/api/auth/2fa/enable", {"code": code})

    def totp_disable(self, password, code):
        return self.request("POST", "/api/auth/2fa/disable", {"password": password, "code": code})

    def sessions(self):
        return self.request("GET", "/api/auth/sessions")

    def revoke_session(self, sid):
        return self.request("DELETE", "/api/auth/sessions/%s" % int(sid))

    # ------------------------------------------------------------ company
    def create_org(self, name, ice=""):
        return self.request("POST", "/api/orgs", {"name": name, "ice": ice})

    def members(self, org):
        return self.request("GET", "/api/orgs/%s/members" % org)

    def invite(self, org, role):
        return self.request("POST", "/api/orgs/%s/invites" % org, {"role": role})

    def accept(self, code):
        return self.request("POST", "/api/invites/accept", {"code": code})

    def set_role(self, org, uid, role):
        return self.request("PATCH", "/api/orgs/%s/members/%s" % (org, uid), {"role": role})

    def remove_member(self, org, uid):
        return self.request("DELETE", "/api/orgs/%s/members/%s" % (org, uid))

    def reset_member_password(self, org, uid):
        return self.request("POST", "/api/orgs/%s/members/%s/reset-password" % (org, uid))

    def license(self, org, key):
        return self.request("POST", "/api/orgs/%s/license" % org, {"key": key})

    def register_device(self, org, name):
        return self.request("POST", "/api/orgs/%s/devices" % org, {"name": name})

    def sync(self, org, device_no, since, changes):
        return self.request("POST", "/api/orgs/%s/sync" % org,
                            {"device_no": device_no, "since": since, "changes": changes}, timeout=120)

    def files_missing(self, org, shas):
        return self.request("POST", "/api/orgs/%s/files/check" % org, {"shas": shas}).get("missing", [])

    def put_file(self, org, sha, data):
        return self.request("PUT", "/api/orgs/%s/files/%s" % (org, sha), raw=data, timeout=300)

    def get_file(self, org, sha):
        return self.request("GET", "/api/orgs/%s/files/%s" % (org, sha), timeout=300, expect_json=False)

    def export(self, org):
        return self.request("GET", "/api/orgs/%s/export" % org, timeout=300, expect_json=False)


# --------------------------------------------------------------------------
# Session state stored on the device (never synchronised)
# --------------------------------------------------------------------------

class Account:
    """Reads/writes the connection state in the local settings table."""

    def __init__(self, store):
        self.store = store

    @property
    def url(self):
        return (self.store.get("cloud_url") or default_url()).rstrip("/")

    @property
    def token(self):
        return self.store.get("cloud_token") or ""

    @property
    def connected(self):
        return bool(self.token and self.url)

    @property
    def me(self):
        return self.store.get_json("cloud_me", {}) or {}

    @property
    def org_id(self):
        v = self.store.get("cloud_org")
        return int(v) if v and v.isdigit() else None

    @property
    def org(self):
        return next((o for o in self.me.get("orgs", []) if o["id"] == self.org_id), None)

    @property
    def role(self):
        return (self.org or {}).get("role")

    def client(self):
        return Cloud(self.url, self.token)

    def save_login(self, url, payload):
        self.store.set("cloud_url", url.rstrip("/"))
        self.store.set("cloud_token", payload["token"])
        self.save_me(payload)

    def save_me(self, payload):
        me = {k: payload.get(k) for k in ("user", "orgs", "ai")}
        self.store.set_json("cloud_me", me)
        org = self.org
        if org:
            self.store.set_json("cloud_plan", {k: org.get(k) for k in ("plan", "label", "until", "active", "limits")})
        elif self.org_id and me.get("orgs") is not None:
            self.store.set("cloud_org", "")

    def device_no(self, org_id):
        v = self.store.get("sync_device_%s" % org_id)
        return int(v) if v and v.isdigit() else 0

    def seq(self, org_id):
        v = self.store.get("sync_seq_%s" % org_id)
        return int(v) if v and v.isdigit() else 0

    def forget(self):
        for k in ("cloud_token", "cloud_me", "cloud_org", "cloud_plan"):
            self.store.set(k, "")


# --------------------------------------------------------------------------
# Joining a company space and synchronising
# --------------------------------------------------------------------------

def device_name():
    try:
        import platform
        return ("Safqa · %s" % (platform.node() or "téléphone"))[:100]
    except Exception:  # noqa: BLE001
        return "Safqa"


def attach(store, account, org_id, mode, backup_dir=None):
    """Bind this device to a company space.

    mode: 'push'    - this phone's data becomes the company's data (empty space)
          'replace' - a backup is kept, then the company's data replaces local data
    """
    cloud = account.client()
    reg = cloud.register_device(org_id, device_name())
    if backup_dir and mode == "replace" and not store.is_empty():
        os.makedirs(backup_dir, exist_ok=True)
        with open(os.path.join(backup_dir, "avant-synchro-%s.db" % time.strftime("%Y%m%d-%H%M%S")), "wb") as fh:
            fh.write(store.backup_bytes())
    store.set("cloud_org", str(org_id))
    store.set("sync_device_%s" % org_id, str(reg["device_no"]))
    store.set("sync_seq_%s" % org_id, "0")
    store.set_id_base(reg["device_no"])
    if mode == "replace":
        store.sync_wipe()
    else:
        store.sync_mark_all()
    account.save_me(cloud.me())
    return reg


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def synchronize(store, account, docs_dir, progress=None):
    """One full exchange. Returns {'sent', 'received', 'files_up', 'files_down'}."""
    org = account.org_id
    if not account.connected or not org:
        raise CloudError("Connectez-vous à Safqa Cloud pour synchroniser.")
    cloud = account.client()
    device = account.device_no(org)
    if not device:
        raise CloudError("Cet appareil n'est pas encore relié à l'espace entreprise.")
    out = {"sent": 0, "received": 0, "files_up": 0, "files_down": 0}
    read_only = account.role == "viewer"

    # Fingerprint new local documents so the file itself can follow.
    for d in store.q("SELECT id, path FROM documents WHERE (file_sha IS NULL OR file_sha='') AND path<>''"):
        if d.get("path") and os.path.exists(d["path"]):
            store.x("UPDATE documents SET file_sha=? WHERE id=?", (file_sha(d["path"]), d["id"]))

    since = account.seq(org)
    for _round in range(200):
        batch = [] if read_only else store.sync_take(BATCH)
        changes = [{k: v for k, v in it.items() if k != "v"} for it in batch]
        res = cloud.sync(org, device, since, changes)
        if batch:
            store.sync_done(batch)
            out["sent"] += len(batch)
        if res.get("changes"):
            store.sync_apply(res["changes"])
            out["received"] += len(res["changes"])
        since = res.get("seq", since)
        store.set("sync_seq_%s" % org, str(since))
        if res.get("plan"):
            plan = dict(res["plan"])
            store.set_json("cloud_plan", plan)
        if progress:
            progress(out)
        if not res.get("more") and (read_only or not store.sync_pending()):
            break

    # Files: upload ours, download the ones created on other devices.
    docs = store.q("SELECT id, filename, path, file_sha FROM documents WHERE file_sha IS NOT NULL AND file_sha<>''")
    local = {d["file_sha"]: d for d in docs if d.get("path") and os.path.exists(d["path"])}
    if local and not read_only:
        for sha in cloud.files_missing(org, list(local)):
            with open(local[sha]["path"], "rb") as fh:
                cloud.put_file(org, sha, fh.read())
            out["files_up"] += 1
    os.makedirs(docs_dir, exist_ok=True)
    for d in docs:
        if d["file_sha"] in local:
            continue
        try:
            data = cloud.get_file(org, d["file_sha"])
        except CloudError as exc:
            if exc.status == 404:
                continue                      # not uploaded yet by its author
            raise
        if hashlib.sha256(data).hexdigest() != d["file_sha"]:
            continue
        ext = os.path.splitext(d.get("filename") or "")[1][:8]
        path = os.path.join(docs_dir, "cloud_%s%s" % (d["file_sha"][:16], ext))
        with open(path + ".part", "wb") as fh:
            fh.write(data)
        shutil.move(path + ".part", path)
        store.sync_local_write("UPDATE documents SET path=? WHERE id=?", (path, d["id"]))
        local[d["file_sha"]] = d
        out["files_down"] += 1
    store.set("sync_last", time.strftime("%Y-%m-%d %H:%M:%S"))
    return out
