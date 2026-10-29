"""ERP layer: portfolio KPIs, budget vs actual, cash flow, receivables
aging, tender pipeline, guarantees and the schedule of deadlines.

Pure functions over rows from storage.Store, like tracking.py.
"""

from collections import OrderedDict
from datetime import date, timedelta

from . import analysis, risk
from . import tracking as tr

PROJECT_STATUS = [("en_cours", "En cours"), ("suspendu", "Suspendu"),
                  ("receptionne", "Réception provisoire"), ("clos", "Clôturé")]
PROJECT_CATEGORIES = ["Voirie", "Assainissement", "Bâtiment", "Hydraulique", "Électricité",
                      "Aménagement urbain", "Ouvrages d'art", "Génie civil", "Autre"]
EXPENSE_CATEGORIES = [("main_oeuvre", "Main d'œuvre"), ("materiaux", "Matériaux"),
                      ("materiel", "Matériel & engins"), ("sous_traitance", "Sous-traitance"),
                      ("transport", "Transport"), ("etudes", "Études & essais"),
                      ("frais_generaux", "Frais généraux"), ("autre", "Autre")]
EXPENSE_STATUS = [("engage", "Engagé"), ("facture", "Facturé"), ("paye", "Payé")]
TENDER_STATUS = [("veille", "Veille"), ("etude", "En étude"), ("soumis", "Soumis"),
                 ("gagne", "Attribué"), ("perdu", "Perdu"), ("abandonne", "Abandonné")]
GUARANTEE_KINDS = [("provisoire", "Caution provisoire"), ("definitive", "Caution définitive"),
                   ("retenue", "Caution de retenue de garantie"), ("avance", "Caution d'avance"),
                   ("autre", "Autre garantie")]
GUARANTEE_STATUS = [("active", "En cours"), ("mainlevee_demandee", "Mainlevée demandée"),
                    ("liberee", "Libérée")]
TIER_KINDS = [("client", "Maître d'ouvrage"), ("fournisseur", "Fournisseur"),
              ("sous_traitant", "Sous-traitant"), ("banque", "Banque"),
              ("bet", "BET / Laboratoire"), ("autre", "Autre")]
WEATHER = ["Ensoleillé", "Nuageux", "Pluie", "Fortes pluies", "Vent fort", "Chaleur extrême"]

LABELS = {name: dict(values) for name, values in (
    ("project_status", PROJECT_STATUS), ("expense_category", EXPENSE_CATEGORIES),
    ("expense_status", EXPENSE_STATUS), ("tender_status", TENDER_STATUS),
    ("guarantee_kind", GUARANTEE_KINDS), ("guarantee_status", GUARANTEE_STATUS),
    ("tier_kind", TIER_KINDS))}

MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
             "nov.", "déc."]


def label(kind, code):
    return LABELS.get(kind, {}).get(code, code or "")


def _d(value):
    return tr.parse_date(value)


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

def project_state(store, pid, today=None):
    """Bundle + resolved contract terms + risk flags for one project."""
    b = store.bundle(pid)
    if not b["project"]:
        return None
    terms = analysis.project_terms(b["documents"])
    for k, v in (b["project"].get("terms") or {}).items():
        terms[k] = v          # manual corrections win
    p = dict(b["project"], terms=terms)
    b["project_full"] = p
    b["terms"] = terms
    b["schedule"] = tr.schedule(p, b["orders"], b["receptions"], today)
    b["finance"] = project_financials(b, today)
    b["flags"] = risk.evaluate(p, b["documents"], b["checklist"], b["orders"], b["items"],
                               b["decomptes"], b["receptions"], today,
                               expenses=b["expenses"], budget=b["budget"],
                               guarantees=b["guarantees"], finance=b["finance"])
    return b


def expense_ttc(e):
    return (e.get("amount_ht") or 0) * (1 + (e.get("tva_pct") or 0) / 100.0)


def project_financials(b, today=None):
    p = b.get("project_full") or b["project"]
    terms = p.get("terms") or {}
    tva = (tr.term(terms, "tva_pct") or 20.0) / 100.0
    contract_ttc = p.get("amount_ttc") or tr.term(terms, "contract_amount_ttc") or 0
    contract_ht = contract_ttc / (1 + tva) if contract_ttc else 0
    decs = sorted(b.get("decomptes", []), key=lambda d: d.get("number") or 0)
    last = decs[-1] if decs else {}
    invoiced_ttc = last.get("total_ttc") or 0
    invoiced_ht = last.get("total_ht") or 0
    paid = sum(d.get("paid_amount") or 0 for d in decs if d.get("paid_date"))
    unpaid = sum(d.get("net_ttc") or 0 for d in decs if not d.get("paid_date"))
    exps = b.get("expenses", [])
    costs_ht = sum(e.get("amount_ht") or 0 for e in exps)
    costs_unpaid_ttc = sum(expense_ttc(e) for e in exps if e.get("status") != "paye")
    budget = OrderedDict((c, 0.0) for c, _ in EXPENSE_CATEGORIES)
    for line in b.get("budget", []):
        budget[line.get("category") or "autre"] = budget.get(line.get("category") or "autre", 0) + (line.get("amount_ht") or 0)
    actual = OrderedDict((c, 0.0) for c, _ in EXPENSE_CATEGORIES)
    for e in exps:
        actual[e.get("category") or "autre"] = actual.get(e.get("category") or "autre", 0) + (e.get("amount_ht") or 0)
    budget_ht = sum(budget.values())
    by_cat = []
    for code, lbl in EXPENSE_CATEGORIES:
        if budget.get(code) or actual.get(code):
            bud, act = budget.get(code, 0), actual.get(code, 0)
            by_cat.append({"code": code, "label": lbl, "budget": bud, "actual": act,
                           "ratio": (act / bud) if bud else (1.0 if act else 0.0),
                           "overrun": bool(bud) and act > bud})
    q = tr.quantities_summary(b.get("items", []), terms)
    progress = q["progress"] if q["initial_ht"] else (invoiced_ht / contract_ht if contract_ht else 0)
    # Cost at completion: what is spent plus what the budget still expects.
    remaining_budget = max(0.0, budget_ht - costs_ht)
    cost_at_completion = costs_ht + remaining_budget if budget_ht else (
        costs_ht / progress if progress > 0.05 else costs_ht)
    margin_ht = invoiced_ht - costs_ht
    forecast_margin = contract_ht - cost_at_completion if contract_ht else 0
    return {
        "contract_ttc": contract_ttc, "contract_ht": contract_ht,
        "invoiced_ttc": invoiced_ttc, "invoiced_ht": invoiced_ht,
        "paid_ttc": paid, "unpaid_ttc": unpaid,
        "retenue": last.get("retenue") or 0,
        "backlog_ht": max(0.0, contract_ht - invoiced_ht),
        "costs_ht": costs_ht, "costs_unpaid_ttc": costs_unpaid_ttc,
        "budget_ht": budget_ht, "by_category": by_cat,
        "margin_ht": margin_ht, "margin_pct": (margin_ht / invoiced_ht * 100) if invoiced_ht else 0,
        "cost_at_completion": cost_at_completion, "forecast_margin": forecast_margin,
        "forecast_margin_pct": (forecast_margin / contract_ht * 100) if contract_ht else 0,
        "progress": min(1.0, progress), "invoiced_ratio": (invoiced_ht / contract_ht) if contract_ht else 0,
    }


# --------------------------------------------------------------------------
# Portfolio
# --------------------------------------------------------------------------

def month_keys(today, n=12):
    keys = []
    y, m = today.year, today.month
    for _ in range(n):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(keys))


def month_label(key):
    return "%s %02d" % (MONTHS_FR[key[1] - 1], key[0] % 100)


def portfolio(store, today=None, months=12):
    today = today or date.today()
    states = [s for s in (project_state(store, p["id"], today) for p in store.projects()) if s]
    keys = month_keys(today, months)
    invoiced_m = OrderedDict((k, 0.0) for k in keys)
    costs_m = OrderedDict((k, 0.0) for k in keys)
    collected_m = OrderedDict((k, 0.0) for k in keys)
    aging = OrderedDict([("0-30 j", 0.0), ("31-60 j", 0.0), ("61-90 j", 0.0), ("> 90 j", 0.0)])
    tot = {"contract_ht": 0.0, "invoiced_ht": 0.0, "backlog_ht": 0.0, "paid_ttc": 0.0,
           "unpaid_ttc": 0.0, "costs_ht": 0.0, "margin_ht": 0.0, "retenue": 0.0,
           "forecast_margin": 0.0, "payables_ttc": 0.0, "penalties": 0.0}
    rows = []
    year_invoiced = 0.0
    for s in states:
        f = s["finance"]
        for k in tot:
            if k in f:
                tot[k] += f[k] or 0
        tot["payables_ttc"] += f["costs_unpaid_ttc"]
        pen = tr.penalty_estimate(s["project_full"], s["schedule"])
        tot["penalties"] += pen["amount"]
        prev = 0.0
        for d in sorted(s["decomptes"], key=lambda d: d.get("number") or 0):
            dd = _d(d.get("date"))
            amount = (d.get("total_ht") or 0) - prev
            prev = d.get("total_ht") or 0
            if dd and (dd.year, dd.month) in invoiced_m:
                invoiced_m[(dd.year, dd.month)] += amount
            if dd and dd.year == today.year:
                year_invoiced += amount
            pd = _d(d.get("paid_date"))
            if pd and (pd.year, pd.month) in collected_m:
                collected_m[(pd.year, pd.month)] += d.get("paid_amount") or 0
            if not d.get("paid_date"):
                ref = _d(d.get("submitted_date")) or dd
                age = (today - ref).days if ref else 0
                bucket = "0-30 j" if age <= 30 else "31-60 j" if age <= 60 else "61-90 j" if age <= 90 else "> 90 j"
                aging[bucket] += d.get("net_ttc") or 0
        for e in s["expenses"]:
            ed = _d(e.get("date"))
            if ed and (ed.year, ed.month) in costs_m:
                costs_m[(ed.year, ed.month)] += e.get("amount_ht") or 0
        crit = sum(1 for fl in s["flags"] if fl["severity"] == "critique")
        high = sum(1 for fl in s["flags"] if fl["severity"] == "élevé")
        rows.append({"state": s, "critical": crit, "high": high})
    tot["margin_pct"] = (tot["margin_ht"] / tot["invoiced_ht"] * 100) if tot["invoiced_ht"] else 0
    tot["year_invoiced_ht"] = year_invoiced
    guarantees = store.q("SELECT * FROM guarantees WHERE status IS NULL OR status != 'liberee'")
    tot["guarantees"] = sum(g.get("amount") or 0 for g in guarantees)
    tot["projects"] = len(states)
    tot["active_projects"] = sum(1 for s in states if (s["project"].get("status") or "en_cours") == "en_cours")
    return {"totals": tot, "rows": rows, "states": states,
            "series": [(month_label(k), invoiced_m[k], costs_m[k], collected_m[k]) for k in keys],
            "aging": list(aging.items()),
            "pipeline": tender_pipeline(store.all("tenders"), today),
            "guarantees": guarantees_summary(store, today)}


def tender_pipeline(tenders, today=None):
    today = today or date.today()
    by_status = OrderedDict((code, {"label": lbl, "count": 0, "amount": 0.0}) for code, lbl in TENDER_STATUS)
    upcoming = []
    for t in tenders:
        st = t.get("status") or "veille"
        if st not in by_status:
            st = "veille"
        by_status[st]["count"] += 1
        by_status[st]["amount"] += t.get("bid_ttc") or t.get("estimate_ttc") or 0
        dd = _d(t.get("deposit_date"))
        if dd and st in ("veille", "etude") and dd >= today:
            upcoming.append(((dd - today).days, t))
    won, lost = by_status["gagne"]["count"], by_status["perdu"]["count"]
    upcoming.sort(key=lambda x: x[0])
    active = sum(by_status[s]["amount"] for s in ("veille", "etude", "soumis"))
    return {"by_status": by_status, "win_rate": (won / (won + lost)) if (won + lost) else None,
            "upcoming": upcoming, "active_amount": active,
            "active_count": sum(by_status[s]["count"] for s in ("veille", "etude", "soumis"))}


def guarantee_info(g, today=None):
    today = today or date.today()
    exp = _d(g.get("expiry_date"))
    issue = _d(g.get("issue_date"))
    days = (exp - today).days if exp else None
    active = (g.get("status") or "active") != "liberee"
    months = max(0, ((exp or today) - issue).days / 30.4) if issue else 0
    fees = (g.get("amount") or 0) * (g.get("commission_pct") or 0) / 100.0 * months / 12.0
    return {"days_to_expiry": days, "expired": active and days is not None and days < 0,
            "expiring": active and days is not None and 0 <= days <= 30, "active": active,
            "fees_estimate": fees}


def guarantees_summary(store, today=None):
    rows = store.q("SELECT * FROM guarantees ORDER BY expiry_date")
    by_bank = OrderedDict()
    total = 0.0
    alerts = 0
    for g in rows:
        info = guarantee_info(g, today)
        if not info["active"]:
            continue
        total += g.get("amount") or 0
        name = store.tier_name(g.get("bank_id")) or "Banque non précisée"
        by_bank[name] = by_bank.get(name, 0) + (g.get("amount") or 0)
        if info["expired"] or info["expiring"]:
            alerts += 1
    return {"total": total, "by_bank": list(by_bank.items()), "alerts": alerts, "count": len(rows)}


# --------------------------------------------------------------------------
# Cash flow
# --------------------------------------------------------------------------

def cashflow_forecast(store, today=None, months=6):
    """Expected inflows (unpaid statements, retention release) and outflows
    (unpaid supplier invoices) per month; overdue amounts land in month 0."""
    today = today or date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    inflow = OrderedDict((k, 0.0) for k in keys)
    outflow = OrderedDict((k, 0.0) for k in keys)

    def bucket(d):
        if not d or (d.year, d.month) < keys[0]:
            return keys[0]
        k = (d.year, d.month)
        return k if k in inflow else None

    for p in store.projects():
        s = project_state(store, p["id"], today)
        delay = int(tr.term(s["terms"], "payment_delay_days") or 60)
        for d in s["decomptes"]:
            if d.get("paid_date"):
                continue
            ref = _d(d.get("submitted_date")) or _d(d.get("date"))
            k = bucket(ref + timedelta(days=delay) if ref else today)
            if k:
                inflow[k] += d.get("net_ttc") or 0
        rs = tr.reception_status(s["project_full"], s["receptions"], today)
        if rs["warranty_end"] and s["finance"]["retenue"] and not rs["final"]:
            k = bucket(rs["warranty_end"] + timedelta(days=delay))
            if k:
                inflow[k] += s["finance"]["retenue"]
    for e in store.q("SELECT * FROM expenses WHERE status IS NULL OR status != 'paye'"):
        due = _d(e.get("due_date")) or ((_d(e.get("date")) or today) + timedelta(days=60))
        k = bucket(due)
        if k:
            outflow[k] += expense_ttc(e)
    out = []
    running = 0.0
    for k in keys:
        running += inflow[k] - outflow[k]
        out.append({"month": month_label(k), "inflow": inflow[k], "outflow": outflow[k],
                    "net": inflow[k] - outflow[k], "cumulative": running})
    return out


def receivables(store, today=None):
    today = today or date.today()
    rows = []
    for p in store.projects():
        s = project_state(store, p["id"], today)
        for d in s["decomptes"]:
            if d.get("paid_date"):
                continue
            st = tr.payment_status(d, s["terms"], today)
            rows.append({"project": s["project"], "decompte": d, "status": st})
    rows.sort(key=lambda r: -(r["status"]["days"] or 0))
    return rows


# --------------------------------------------------------------------------
# Schedule of deadlines
# --------------------------------------------------------------------------

def agenda(store, today=None, horizon=90, past=30):
    """All dated obligations across modules, sorted, within the window."""
    today = today or date.today()
    start, end = today - timedelta(days=past), today + timedelta(days=horizon)
    ev = []

    def add(d, kind, title, detail="", route=None, severity="info"):
        d = _d(d)
        if d and start <= d <= end:
            days = (d - today).days
            if days < 0 and severity == "info":
                severity = "élevé"
            elif 0 <= days <= 7 and severity == "info":
                severity = "moyen"
            ev.append({"date": d, "days": days, "kind": kind, "title": title, "detail": detail,
                       "route": route, "severity": severity})

    for t in store.all("tenders"):
        if (t.get("status") or "veille") in ("veille", "etude"):
            add(t.get("deposit_date"), "Appel d'offres", "Dépôt des offres - AO %s" % (t.get("ref") or ""),
                t.get("title") or "", "/ao/%s" % t["id"])
        if t.get("status") == "soumis":
            add(t.get("opening_date"), "Appel d'offres", "Ouverture des plis - AO %s" % (t.get("ref") or ""),
                t.get("title") or "", "/ao/%s" % t["id"])
    for g in store.q("SELECT * FROM guarantees WHERE status IS NULL OR status != 'liberee'"):
        add(g.get("expiry_date"), "Caution", "Échéance %s" % label("guarantee_kind", g.get("kind")).lower(),
            "%s - %s DH" % (g.get("ref") or "", "{:,.0f}".format(g.get("amount") or 0).replace(",", " ")),
            "/module/garanties")
    for e in store.q("SELECT * FROM expenses WHERE status = 'facture'"):
        add(e.get("due_date"), "Fournisseur", "Échéance facture %s" % (e.get("ref") or ""),
            e.get("label") or "", "/marche/%s?tab=couts" % e.get("project_id"))
    for p in store.projects():
        s = project_state(store, p["id"], today)
        pid = p["id"]
        name = p.get("ref") or p.get("title") or ""
        sched = s["schedule"]
        if sched.get("end") and not sched.get("finished"):
            add(sched["end"], "Délai", "Fin du délai contractuel - %s" % name, p.get("title") or "",
                "/marche/%s" % pid, "élevé" if sched["late_days"] else "info")
        notif = _d(p.get("approval_notif_date"))
        if notif:
            present = {c["code"] for c in s["checklist"] if c.get("present")}
            if "CAUTION_DEF" not in present:
                lim = int(tr.term(s["terms"], "caution_definitive_delay_days") or 30)
                add(notif + timedelta(days=lim), "Caution", "Constitution caution définitive - %s" % name,
                    "", "/marche/%s?tab=cautions" % pid, "élevé")
        delay = int(tr.term(s["terms"], "payment_delay_days") or 60)
        for d in s["decomptes"]:
            if not d.get("paid_date") and d.get("submitted_date"):
                add(_d(d["submitted_date"]) + timedelta(days=delay), "Paiement",
                    "Paiement attendu décompte n° %s - %s" % (d.get("number"), name),
                    "", "/marche/%s?tab=decomptes" % pid)
        rs = tr.reception_status(s["project_full"], s["receptions"], today)
        if rs["warranty_end"] and not rs["final"]:
            add(rs["warranty_end"], "Réception", "Fin du délai de garantie - %s" % name,
                "Demander la réception définitive", "/marche/%s?tab=receptions" % pid)
        for t in s["tasks"]:
            if (t.get("progress") or 0) < 100:
                add(t.get("end"), "Planning", "Fin de tâche : %s" % (t.get("name") or ""), name,
                    "/marche/%s?tab=planning" % pid)
    ev.sort(key=lambda e: (e["date"], e["kind"]))
    return ev
