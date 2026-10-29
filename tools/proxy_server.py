#!/usr/bin/env python3
"""Safqa relay: lets subscribers use the AI with their licence key only.

The app (mode « Serveur Safqa ») sends its Messages API request here with an
`x-safqa-license` header.  The relay checks the key and the monthly quota of
the plan, adds your Anthropic API key and streams the answer back.

    export ANTHROPIC_API_KEY=sk-ant-...
    export SAFQA_LICENSE_SECRET=...        # same as for tools/make_license.py
    python tools/proxy_server.py --port 8080

Put it behind HTTPS (Caddy, Nginx, Cloudflare Tunnel...) and set
DEFAULT_PROXY_URL in safqa/config.py to its public URL.
"""

import argparse
import json
import os
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from safqa import billing  # noqa: E402
from safqa.ai import ANALYSIS_SCHEMA, API_URL  # noqa: E402

ALLOWED_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"}
MAX_BODY = 8 * 1024 * 1024


class Quota:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS usage (license TEXT, month TEXT, kind TEXT, n INTEGER,"
                        " PRIMARY KEY (license, month, kind))")
        self.lock = threading.Lock()

    def take(self, license_key, kind, limit):
        month = datetime.now().strftime("%Y-%m")
        with self.lock:
            row = self.db.execute("SELECT n FROM usage WHERE license=? AND month=? AND kind=?",
                                  (license_key, month, kind)).fetchone()
            n = row[0] if row else 0
            if n >= limit:
                return False
            self.db.execute("INSERT INTO usage VALUES (?,?,?,1) ON CONFLICT(license, month, kind) "
                            "DO UPDATE SET n=n+1", (license_key, month, kind))
            self.db.commit()
            return True


class Relay(BaseHTTPRequestHandler):
    quota = None
    api_key = None

    def _error(self, status, message):
        data = json.dumps({"type": "error", "error": {"type": "safqa_error", "message": message}}).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/v1/messages":
            return self._error(404, "Not found")
        ok, plan, _exp, msg = billing.check_key(self.headers.get("x-safqa-license", ""))
        if not ok:
            return self._error(403, msg)
        length = int(self.headers.get("content-length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._error(413, "Requête trop volumineuse")
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return self._error(400, "JSON invalide")
        if body.get("model") not in ALLOWED_MODELS:
            return self._error(400, "Modèle non autorisé")
        fmt = (body.get("output_config") or {}).get("format") or {}
        kind = "ai_analysis" if fmt.get("schema") == ANALYSIS_SCHEMA else "ai_question"
        limit = billing.PLANS[plan]["ai_analyses" if kind == "ai_analysis" else "ai_questions"]
        if not self.quota.take(self.headers["x-safqa-license"].strip().upper(), kind, limit):
            return self._error(402, "Quota mensuel de votre abonnement atteint.")
        body["max_tokens"] = min(int(body.get("max_tokens") or 16000), 32000)

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() in ("content-type", "anthropic-version", "anthropic-beta", "accept")}
        headers["x-api-key"] = self.api_key
        req = urllib.request.Request(API_URL + "/v1/messages", data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            upstream = urllib.request.urlopen(req, timeout=900)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        except OSError as exc:
            return self._error(502, "Service IA injoignable : %s" % exc)
        self.send_response(200)
        self.send_header("content-type", upstream.headers.get("content-type", "text/event-stream"))
        self.end_headers()
        with upstream:
            while True:
                chunk = upstream.read1(65536) if hasattr(upstream, "read1") else upstream.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--db", default="safqa_quota.db")
    args = ap.parse_args()
    Relay.api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not Relay.api_key:
        sys.exit("ANTHROPIC_API_KEY manquant")
    if not os.environ.get("SAFQA_LICENSE_SECRET"):
        sys.exit("SAFQA_LICENSE_SECRET manquant")
    Relay.quota = Quota(args.db)
    print("Relais Safqa sur %s:%d" % (args.host, args.port))
    ThreadingHTTPServer((args.host, args.port), Relay).serve_forever()


if __name__ == "__main__":
    main()
