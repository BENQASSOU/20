"""Orchestrates document ingestion: extraction -> articles -> rules -> AI."""

import base64
import os

from . import rules
from .segment import Article, split_articles
from .textract import extract, guess_doc_type

DOC_PRIORITY = {"MARCHE": 0, "CPS": 1, "AVENANT": 2, "CCAG-T": 5}


def ingest(path, filename=None, doc_type=None):
    """Extract and analyse a document offline. Returns a dict for storage."""
    filename = filename or os.path.basename(path)
    doc = extract(path)
    doc_type = doc_type or guess_doc_type(doc.text, filename)
    articles = split_articles(doc)
    analysis = run_rules(articles, doc_type)
    return {
        "filename": filename, "path": path, "doc_type": doc_type,
        "pages": len(doc.pages), "char_count": doc.char_count, "scanned": 1 if doc.scanned else 0,
        "articles": [a.to_dict() for a in articles], "analysis": analysis,
        "ai_status": "",
    }


def run_rules(articles, doc_type):
    res = rules.extract(articles)
    resolved, conflicts = rules.resolve_terms(res["terms"])
    issues = rules.document_issues(articles, res["findings"], resolved, conflicts, doc_type)
    return {"findings": res["findings"], "terms": resolved, "conflicts": conflicts,
            "issues": issues, "ai": None, "ai_risks": []}


def articles_of(document):
    return [Article.from_dict(a) for a in (document.get("articles") or [])]


def run_ai(client, document, on_progress=None):
    """Add the AI layer to a stored document; returns the updated analysis."""
    from . import ai
    articles = articles_of(document)
    pdf_b64 = None
    if document.get("scanned") and document.get("path", "").lower().endswith(".pdf"):
        size = os.path.getsize(document["path"])
        if size > 30 * 1024 * 1024:
            raise ai.AIError("PDF scanné trop volumineux pour l'analyse IA (30 Mo max).")
        with open(document["path"], "rb") as fh:
            pdf_b64 = base64.b64encode(fh.read()).decode("ascii")
    elif not articles:
        raise ai.AIError("Aucun texte exploitable dans ce document.")
    result = ai.analyze(client, articles, document.get("doc_type", "CPS"),
                        document.get("filename", ""), on_progress=on_progress, pdf_b64=pdf_b64)
    analysis = dict(document.get("analysis") or {})
    analysis["ai"] = result
    analysis["ai_risks"] = result.get("risks", [])
    # AI fills the terms the rules could not find (only verified citations).
    terms = dict(analysis.get("terms") or {})
    for t in result.get("terms", []):
        key = t.get("key")
        val = t.get("value_number")
        if key == "price_type":
            val = t.get("value_text") or None
        if val is None or not key:
            continue
        cur = terms.get(key)
        if cur and cur.get("source") == "CPS":
            if isinstance(val, (int, float)) and isinstance(cur.get("value"), (int, float)) \
                    and abs(val - cur["value"]) > 1e-9 and t.get("verified"):
                cur["ai_value"] = val
            continue
        if t.get("verified") or document.get("scanned"):
            terms[key] = {"value": val, "source": "IA", "article_key": t.get("article_key"),
                          "article_label": t.get("article_label"), "page": t.get("page"),
                          "text": t.get("quote", "")}
    if "execution_delay_days" in terms and terms["execution_delay_days"]["source"] == "IA":
        d = terms["execution_delay_days"]["value"]
        if d and d % 30 == 0:
            terms["execution_delay_months"] = dict(terms["execution_delay_days"], value=int(d // 30))
    analysis["terms"] = terms
    return analysis


def project_terms(documents):
    """Contract terms for the project: the highest-priority document that
    states a value wins (marché/CPS before CCAG-T); defaults otherwise."""
    docs = sorted(documents, key=lambda d: DOC_PRIORITY.get(d.get("doc_type"), 3))
    out = {}
    for d in docs:
        for key, t in ((d.get("analysis") or {}).get("terms") or {}).items():
            if t.get("source") == "défaut":
                out.setdefault(key, t)
                continue
            if key not in out or out[key].get("source") == "défaut":
                out[key] = dict(t, document=d.get("filename"))
    return out


def unified_findings(document):
    """Rules findings + AI items in one list for display."""
    a = document.get("analysis") or {}
    out = []
    for f in a.get("findings", []):
        out.append(f)
    ai_res = a.get("ai") or {}
    for o in ai_res.get("obligations", []):
        out.append({"kind": "obligation", "category": o.get("category") or "Général",
                    "party": o.get("party"), "summary": o.get("description"),
                    "text": o.get("quote"), "deadline": o.get("deadline"),
                    "importance": o.get("importance"),
                    "article_key": o.get("article_key"), "article_label": o.get("article_label"),
                    "page": o.get("page"), "source": "IA", "verified": o.get("verified")})
    for d in ai_res.get("deadlines", []):
        out.append({"kind": "deadline", "category": "Délais", "party": "",
                    "summary": "%s%s%s" % (d.get("label"),
                                           (" : %s jours" % _n(d["duration_days"])) if d.get("duration_days") else "",
                                           (" (%s)" % d["trigger"]) if d.get("trigger") else ""),
                    "text": d.get("quote"), "article_key": d.get("article_key"),
                    "article_label": d.get("article_label"), "page": d.get("page"),
                    "source": "IA", "verified": d.get("verified"),
                    "value": {"days": d.get("duration_days"), "trigger": d.get("trigger")}})
    for p in ai_res.get("penalties", []):
        summary = p.get("label") or "Pénalité"
        if p.get("rate_or_amount"):
            summary += " : " + p["rate_or_amount"]
        if p.get("cap"):
            summary += " - plafond " + p["cap"]
        out.append({"kind": "penalty", "category": "Pénalités", "party": "Titulaire", "summary": summary,
                    "text": p.get("quote"), "article_key": p.get("article_key"),
                    "article_label": p.get("article_label"), "page": p.get("page"),
                    "source": "IA", "verified": p.get("verified")})
    for doc in ai_res.get("documents_required", []):
        out.append({"kind": "document", "category": "Documents", "party": "Titulaire",
                    "summary": "À fournir : %s%s" % (doc.get("document"), (" - " + doc["when"]) if doc.get("when") else ""),
                    "text": doc.get("quote"), "article_key": doc.get("article_key"),
                    "article_label": doc.get("article_label"), "page": doc.get("page"),
                    "source": "IA", "verified": doc.get("verified")})
    return out


def _n(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(v)) if v.is_integer() else ("%.1f" % v)


KIND_LABELS = {
    "obligation": "Obligation", "prohibition": "Interdiction", "deadline": "Délai",
    "penalty": "Pénalité", "financial": "Clause financière", "document": "Document à fournir",
    "derogation": "Dérogation", "risky_clause": "Clause à risque", "inconsistency": "Incohérence",
}
