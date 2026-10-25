"""AI client tests against a local fake Messages API (no network, no key)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from safqa import ai, analysis

CPS_RESULT = {
    "summary": "Marché de voirie.",
    "contract": {"objet": "Voirie", "maitre_ouvrage": "Commune de Témara", "reference": "12/2026", "lieu": "Témara"},
    "terms": [{"key": "penalty_rate_per_day", "value_number": 0.001, "value_text": "", "article": "A10",
               "quote": "une pénalité de 1/1000 du montant initial du marché par jour calendaire de retard"},
              {"key": "advance_pct", "value_number": 15, "value_text": "", "article": "A12",
               "quote": "une avance de 15 % est accordée"}],
    "obligations": [{"party": "Titulaire", "category": "Délais", "description": "Remettre le programme",
                     "deadline": "15 jours après OS", "importance": "haute", "article": "A9",
                     "quote": "L'entrepreneur doit remettre le programme d'exécution des travaux"}],
    "deadlines": [], "penalties": [], "documents_required": [],
    "risks": [{"severity": "élevé", "title": "Pénalités sans mise en demeure", "detail": "", "action": "Négocier",
               "article": "A10", "quote": "les pénalités seront appliquées sans mise en demeure préalable"}],
    "bpde_items": [],
}


class FakeAPI(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeAPI.requests.append((self.headers, body))
        if self.headers.get("x-api-key") == "bad":
            self.send_response(401)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"type":"error","error":{"type":"authentication_error","message":"invalid"}}')
            return
        if body["messages"][-1]["content"] == "refuse":
            events = [("message_start", {"type": "message_start", "message": {"model": body["model"], "usage": {}}}),
                      ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "refusal"}, "usage": {}})]
        else:
            text = json.dumps(CPS_RESULT, ensure_ascii=False) if "output_config" in body and \
                "format" in body["output_config"] else "Selon [A10], la pénalité est de 1/1000 par jour."
            half = len(text) // 2
            events = [
                ("message_start", {"type": "message_start", "message": {"model": body["model"], "usage": {"input_tokens": 10}}}),
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
                ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text[:half]}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text[half:]}}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 50}}),
                ("message_stop", {"type": "message_stop"}),
            ]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for name, data in events:
            self.wfile.write(("event: %s\ndata: %s\n\n" % (name, json.dumps(data, ensure_ascii=False))).encode())


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def test_analysis_with_verified_citations(server, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    client = ai.ClaudeClient(api_key="k", base_url=server)
    import os
    doc = analysis.ingest(os.path.join(os.path.dirname(__file__), "fixtures", "sample_cps.txt"))
    new = analysis.run_ai(client, doc)
    res = new["ai"]
    ob = res["obligations"][0]
    assert ob["verified"] and ob["article_key"] == "A5"  # quote found in article 5, citation corrected
    assert res["risks"][0]["verified"] and res["risks"][0]["article_key"] == "A10"
    terms = {t["key"]: t for t in res["terms"]}
    assert terms["penalty_rate_per_day"]["verified"]
    assert not terms["advance_pct"]["verified"]  # hallucinated quote is flagged
    assert "advance_pct" not in new["terms"]      # and not used as a contract term
    headers, body = FakeAPI.requests[-1]
    assert headers["anthropic-version"] == ai.API_VERSION
    assert body["model"] == ai.DEFAULT_MODEL and body["stream"] is True
    assert body["fallbacks"] == "default"
    assert body["output_config"]["format"]["type"] == "json_schema"


def test_chat(server, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    client = ai.ClaudeClient(api_key="k", base_url=server)
    text, info = ai.ask(client, "Pénalités ?", [], "contexte", [{"role": "assistant", "content": "bonjour"}])
    assert "[A10]" in text and info["stop_reason"] == "end_turn"
    _, body = FakeAPI.requests[-1]
    assert body["messages"][0]["role"] == "user"


def test_errors(server, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    with pytest.raises(ai.AIError, match="Clé API invalide"):
        ai.ClaudeClient(api_key="bad", base_url=server).message("s", [{"role": "user", "content": "x"}])
    with pytest.raises(ai.AIError, match="décliné"):
        ai.ClaudeClient(api_key="k", base_url=server).message("s", [{"role": "user", "content": "refuse"}])


def test_schema_is_strict():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False
            assert set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    walk(ai.ANALYSIS_SCHEMA)
