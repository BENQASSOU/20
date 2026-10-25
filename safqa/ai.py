"""Claude API client (raw HTTPS + server-sent events).

The official `anthropic` Python SDK depends on compiled packages (pydantic-
core, jiter) that python-for-android cannot build, so the APK talks to the
Messages API directly with urllib.  Two modes:

* direct : the user's own API key (x-api-key header)
* proxy  : the publisher's relay (tools/proxy_server.py) holds the API key
           and checks the subscriber's licence key, so subscribers never
           need an Anthropic account.
"""

import json
import re
import ssl
import time
import urllib.error
import urllib.request

from .segment import quote_in_text

API_URL = "https://api.anthropic.com"
API_VERSION = "2026-10-21"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_MODEL = "claude-opus-5-5"
MODELS = [
    ("claude-opus-5-5", "Claude Opus 5.5 - le plus précis (recommandé)"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5 - rapide, moins cher"),
    ("claude-haiku-5-5", "Claude Haiku 5.5 - très économique"),
]
CHUNK_CHARS = 300000   # ~85k tokens of French text per request
FULL_DOC_CHARS = 350000


class AIError(Exception):
    def __init__(self, message, retryable=False, status=None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover
        return ssl.create_default_context()


class ClaudeClient:
    def __init__(self, api_key="", model=DEFAULT_MODEL, base_url="", license_key="", timeout=600):
        self.api_key = (api_key or "").strip()
        self.model = model or DEFAULT_MODEL
        self.base_url = (base_url or API_URL).rstrip("/")
        self.license_key = (license_key or "").strip()
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.api_key) or (self.base_url != API_URL and bool(self.license_key))

    def _headers(self):
        h = {"content-type": "application/json", "anthropic-version": API_VERSION,
             "anthropic-beta": FALLBACK_BETA, "accept": "text/event-stream"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        if self.license_key:
            h["x-safqa-license"] = self.license_key
        return h

    def message(self, system, messages, max_tokens=32000, effort="high", schema=None,
                on_progress=None, retries=2):
        """Stream one Messages request; returns (text, info)."""
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "stream": True,
            "system": system,
            "messages": messages,
            "fallbacks": "default",
            "output_config": {"effort": effort},
        }
        if schema:
            body["output_config"]["format"] = {"type": "json_schema", "schema": schema}
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        attempt = 0
        while True:
            try:
                return self._stream(data, on_progress)
            except AIError as exc:
                if exc.retryable and attempt < retries:
                    attempt += 1
                    time.sleep(2 * attempt * attempt)
                    continue
                raise

    def _stream(self, data, on_progress):
        req = urllib.request.Request(self.base_url + "/v1/messages", data=data,
                                     headers=self._headers(), method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context())
        except urllib.error.HTTPError as exc:
            raise _http_error(exc)
        except (urllib.error.URLError, OSError) as exc:
            raise AIError("Connexion impossible au service IA (%s). Vérifiez Internet." %
                          getattr(exc, "reason", exc), retryable=True)

        blocks = {}
        info = {"stop_reason": None, "model": None, "usage": {}, "fallback": False}
        received = 0
        event = None
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    ev = json.loads(payload)
                except ValueError:
                    continue
                et = ev.get("type") or event
                if et == "message_start":
                    msg = ev.get("message", {})
                    info["model"] = msg.get("model")
                    info["usage"].update(msg.get("usage") or {})
                elif et == "content_block_start":
                    cb = ev.get("content_block", {})
                    blocks[ev.get("index", len(blocks))] = {"type": cb.get("type"), "text": cb.get("text", "")}
                    if cb.get("type") == "fallback":
                        info["fallback"] = True
                elif et == "content_block_delta":
                    d = ev.get("delta", {})
                    if d.get("type") == "text_delta":
                        b = blocks.setdefault(ev.get("index", 0), {"type": "text", "text": ""})
                        b["text"] += d.get("text", "")
                        received += len(d.get("text", ""))
                        if on_progress:
                            on_progress(received)
                elif et == "message_delta":
                    info["stop_reason"] = (ev.get("delta") or {}).get("stop_reason") or info["stop_reason"]
                    info["usage"].update(ev.get("usage") or {})
                elif et == "error":
                    err = ev.get("error", {})
                    kind = err.get("type", "")
                    raise AIError("Erreur du service IA : %s" % err.get("message", kind),
                                  retryable=kind in ("overloaded_error", "api_error", "rate_limit_error"))
        except (OSError, ValueError) as exc:
            raise AIError("Connexion interrompue pendant la réponse (%s)." % exc, retryable=True)
        finally:
            resp.close()

        if info["stop_reason"] == "refusal":
            raise AIError("Le modèle a décliné cette demande. Reformulez la question ou utilisez "
                          "l'analyse hors-ligne.")
        # A mid-stream fallback continues the partial text, so text blocks concatenate.
        text = "".join(b["text"] for _, b in sorted(blocks.items()) if b.get("type") == "text")
        if info["stop_reason"] == "max_tokens":
            info["truncated"] = True
        return text, info


def _http_error(exc):
    status = exc.code
    try:
        detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
    except Exception:
        detail = ""
    if status == 401:
        return AIError("Clé API invalide ou expirée.", status=status)
    if status == 402 or status == 403:
        return AIError(detail or "Accès refusé (abonnement ou quota).", status=status)
    if status == 429:
        return AIError("Trop de requêtes, nouvel essai…", retryable=True, status=status)
    if status in (500, 502, 503, 504, 529):
        return AIError("Service IA momentanément indisponible.", retryable=True, status=status)
    return AIError("Requête refusée (%s) : %s" % (status, detail), status=status)


# --------------------------------------------------------------------------
# Contract analysis
# --------------------------------------------------------------------------

TERM_KEYS = ["execution_delay_days", "penalty_rate_per_day", "penalty_cap_pct", "retenue_rate_pct",
             "retenue_cap_pct", "caution_definitive_pct", "caution_definitive_delay_days",
             "warranty_months", "payment_delay_days", "advance_pct", "contract_amount_ttc",
             "price_type"]

_S = {"type": "string"}
_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _obj(props):
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


CITE = {"article": _S, "quote": _S}

ANALYSIS_SCHEMA = _obj({
    "summary": _S,
    "contract": _obj({"objet": _S, "maitre_ouvrage": _S, "reference": _S, "lieu": _S}),
    "terms": {"type": "array", "items": _obj(dict(
        key={"type": "string", "enum": TERM_KEYS}, value_number=_NUM, value_text=_S, **CITE))},
    "obligations": {"type": "array", "items": _obj(dict(
        party={"type": "string", "enum": ["Titulaire", "Maître d'ouvrage", "Maître d'œuvre", "Autre"]},
        category=_S, description=_S, deadline=_S,
        importance={"type": "string", "enum": ["haute", "moyenne", "basse"]}, **CITE))},
    "deadlines": {"type": "array", "items": _obj(dict(
        label=_S, duration_days=_NUM, trigger=_S, **CITE))},
    "penalties": {"type": "array", "items": _obj(dict(
        label=_S, rate_or_amount=_S, cap=_S, base=_S, **CITE))},
    "documents_required": {"type": "array", "items": _obj(dict(document=_S, when=_S, **CITE))},
    "risks": {"type": "array", "items": _obj(dict(
        severity={"type": "string", "enum": ["critique", "élevé", "moyen", "info"]},
        title=_S, detail=_S, action=_S, **CITE))},
    "bpde_items": {"type": "array", "items": _obj(dict(
        number=_S, designation=_S, unit=_S, quantity=_NUM, unit_price_ht=_NUM))},
})

SYSTEM_ANALYSIS = """Tu es un expert de la commande publique marocaine (décret n° 2-22-431 du 8 mars 2023 relatif aux marchés publics, CCAG-Travaux approuvé par le décret n° 2-14-394, décret n° 2-16-344 sur les délais de paiement). Tu assistes une petite entreprise de BTP, un bureau d'études ou un chef de projet qui exécute le marché : tu analyses les pièces du point de vue du titulaire.

Le document est fourni découpé en articles, chacun précédé d'une balise comme [A12] (Article 12) ou [P3] (page 3 quand il n'y a pas d'articles).

Règles :
- Chaque élément extrait doit citer la balise exacte de l'article source dans le champ "article" (ex. "A12") et recopier dans "quote" un extrait mot pour mot de cet article (une phrase, 300 caractères maximum) qui le justifie. Ces citations sont vérifiées automatiquement : n'invente rien et ne reformule pas la citation.
- Si une information n'est pas dans le document, ne la déduis pas : laisse la liste vide ou la valeur à null.
- "terms" : valeurs numériques normalisées. penalty_rate_per_day est une fraction (1/1000 par jour = 0.001). Les pourcentages sont en points (7 % = 7). warranty_months en mois. Les montants en dirhams. price_type dans value_text ("ferme", "révisable" ou "actualisable").
- "obligations" : les obligations contractuelles concrètes (qui doit faire quoi, quand). Priorise celles qui ont un délai, un coût ou une sanction. 60 au maximum.
- "risks" : risques financiers et juridiques pour le titulaire : pénalités lourdes, dérogations au CCAG-T, clauses à ses frais / sans indemnité, incohérences entre articles (délais, montants, pourcentages différents), montant en lettres différent des chiffres, clauses manquantes ou ambiguës. Pour chaque risque, propose une action concrète.
- "bpde_items" : uniquement si le document contient le bordereau des prix / détail estimatif ; sinon liste vide.
- Rédige en français, de façon concise et professionnelle."""


def chunk_articles(articles, limit=CHUNK_CHARS):
    chunks, cur, size = [], [], 0
    for a in articles:
        n = len(a.text) + 40
        if cur and size + n > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(a)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def render_articles(articles):
    return "\n\n".join("[%s] %s (page %s)\n%s" % (a.key, a.label(), a.page, a.text) for a in articles)


def analyze(client, articles, doc_type, filename, on_progress=None, pdf_b64=None):
    """Run the AI analysis and verify every citation against the source text."""
    results = []
    if pdf_b64:
        content = [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                   "data": pdf_b64}},
                   {"type": "text", "text": "Document scanné « %s » (type : %s). Le texte n'a pas de balises : "
                    "dans le champ article indique « Art. N p. X » d'après le document." % (filename, doc_type)}]
        text, info = client.message(SYSTEM_ANALYSIS, [{"role": "user", "content": content}],
                                    schema=ANALYSIS_SCHEMA, on_progress=on_progress)
        results.append((_parse_json(text, info), None))
    else:
        chunks = chunk_articles(articles)
        for i, chunk in enumerate(chunks):
            head = "Document « %s » (type : %s)%s.\n\n" % (
                filename, doc_type, " - partie %d/%d" % (i + 1, len(chunks)) if len(chunks) > 1 else "")
            text, info = client.message(
                SYSTEM_ANALYSIS, [{"role": "user", "content": head + render_articles(chunk)}],
                schema=ANALYSIS_SCHEMA, on_progress=on_progress)
            results.append((_parse_json(text, info), chunk))
    return merge_results(results, articles)


def _parse_json(text, info):
    try:
        return json.loads(text)
    except ValueError:
        if info.get("truncated"):
            raise AIError("Réponse IA tronquée (document trop long). Réessayez avec un modèle plus "
                          "puissant ou découpez le document.")
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
        raise AIError("Réponse IA illisible.")


def merge_results(results, articles):
    by_key = {a.key: a for a in articles}
    merged = {"summary": [], "contract": {}, "terms": [], "obligations": [], "deadlines": [],
              "penalties": [], "documents_required": [], "risks": [], "bpde_items": []}
    for data, _chunk in results:
        if data.get("summary"):
            merged["summary"].append(data["summary"])
        for k, v in (data.get("contract") or {}).items():
            if v and not merged["contract"].get(k):
                merged["contract"][k] = v
        for section in ("terms", "obligations", "deadlines", "penalties", "documents_required", "risks"):
            for item in data.get(section) or []:
                merged[section].append(verify_citation(item, by_key))
        merged["bpde_items"].extend(data.get("bpde_items") or [])
    merged["summary"] = "\n\n".join(merged["summary"])
    return merged


def verify_citation(item, by_key):
    """Mark the item verified if its quote is really in the cited article
    (or in another article, which then becomes the citation)."""
    item = dict(item)
    key = (item.get("article") or "").strip().strip("[]")
    quote = item.get("quote") or ""
    art = by_key.get(key)
    item["verified"] = False
    if art and quote and quote_in_text(quote, art.text):
        item["verified"] = True
    elif quote:
        for a in by_key.values():
            if quote_in_text(quote, a.text):
                art, item["verified"] = a, True
                break
    if art:
        item["article_key"] = art.key
        item["article_label"] = art.label()
        item["page"] = art.page
    else:
        item["article_key"] = None
        item["article_label"] = key or "Non localisé"
        item["page"] = None
    return item


# --------------------------------------------------------------------------
# Question answering
# --------------------------------------------------------------------------

SYSTEM_CHAT = """Tu es Safqa, assistant expert des marchés publics de travaux au Maroc (décret n° 2-22-431, CCAG-T décret n° 2-14-394, décret n° 2-16-344 sur les délais de paiement). Tu aides des entreprises de BTP, bureaux d'études et chefs de projet titulaires de marchés.

Réponds en français, de façon claire et pratique. Appuie chaque affirmation tirée des pièces du marché sur une citation de l'article entre crochets, par exemple [A12]. Distingue ce que dit le marché de ce qui relève de la réglementation générale ; pour la réglementation, indique le texte et invite à vérifier la version en vigueur. Si l'information n'est pas dans les pièces fournies, dis-le. Quand c'est utile, termine par les actions concrètes à mener (courrier, réserve écrite, demande d'OS, réclamation)."""


def _tokens(text):
    from .segment import normalize_for_match
    return [t for t in normalize_for_match(text).split() if len(t) > 2]


def select_articles(question, docs_articles, limit=FULL_DOC_CHARS):
    """docs_articles: [(doc_label, [Article])].  Keeps everything when it
    fits; otherwise ranks articles by keyword overlap with the question."""
    total = sum(len(a.text) for _, arts in docs_articles for a in arts)
    if total <= limit:
        return docs_articles
    q = set(_tokens(question))
    scored = []
    for di, (label, arts) in enumerate(docs_articles):
        for a in arts:
            toks = _tokens(a.title + " " + a.text)
            if not toks:
                continue
            hit = sum(1 for t in toks if t in q)
            title_hit = sum(3 for t in _tokens(a.title) if t in q)
            scored.append(((hit + title_hit) / (len(toks) ** 0.5), di, a))
    scored.sort(key=lambda x: -x[0])
    keep, size = set(), 0
    for score, di, a in scored:
        if size + len(a.text) > limit:
            continue
        keep.add((di, a.key))
        size += len(a.text)
    return [(label, [a for a in arts if (di, a.key) in keep]) for di, (label, arts) in enumerate(docs_articles)]


def ask(client, question, docs_articles, project_context, history, on_progress=None):
    selected = select_articles(question, docs_articles)
    corpus = []
    for label, arts in selected:
        if arts:
            corpus.append("=== %s ===\n%s" % (label, render_articles(arts)))
    system = [
        {"type": "text", "text": SYSTEM_CHAT},
        {"type": "text", "text": "Données de suivi du marché :\n" + project_context},
    ]
    if corpus:
        # Stable document block last in system, cached across questions.
        system.append({"type": "text", "text": "Pièces du marché :\n\n" + "\n\n".join(corpus),
                       "cache_control": {"type": "ephemeral"}})
    messages = []
    for h in history[-12:]:
        role = "assistant" if h["role"] == "assistant" else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + h["content"]
        else:
            messages.append({"role": role, "content": h["content"]})
    if messages and messages[0]["role"] == "assistant":
        messages.pop(0)
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + question
    else:
        messages.append({"role": "user", "content": question})
    text, info = client.message(system, messages, max_tokens=16000, effort="medium",
                                on_progress=on_progress)
    if not text.strip():
        raise AIError("Réponse vide du service IA.")
    return text, info
