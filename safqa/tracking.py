"""Contract execution tracking: schedule, work orders, quantities,
payment statements (décomptes) and acceptances (réceptions).

All functions are pure: they take plain dicts (rows from storage.py) and
return computed values, which keeps them easy to test.
"""

import calendar
from datetime import date, datetime, timedelta

from . import regulation as reg
from .textnum import parse_decimal

OS_KINDS = [
    ("commencement", "Commencement des travaux"),
    ("arret", "Arrêt (ajournement) des travaux"),
    ("reprise", "Reprise des travaux"),
    ("modification", "Modification / travaux supplémentaires"),
    ("prolongation", "Prolongation de délai"),
    ("autre", "Autre"),
]
OS_LABELS = dict(OS_KINDS)


def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def fmt_date(d):
    d = parse_date(d)
    return d.strftime("%d/%m/%Y") if d else "-"


def add_months(d, months):
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def term(terms, key):
    t = (terms or {}).get(key)
    if isinstance(t, dict):
        return t.get("value")
    if t is None:
        return reg.DEFAULTS.get(key)
    return t


# --------------------------------------------------------------------------
# Schedule
# --------------------------------------------------------------------------

def schedule(project, orders, receptions=(), today=None):
    """Compute the contractual timeline.

    Returns dict with start, end (contractual end including suspensions and
    extensions), suspended_days, elapsed, remaining, late_days, progress
    (0..1 of time consumed) and `stopped` (an arrêt without reprise).
    """
    today = today or date.today()
    delay_days = project.get("delay_days") or 0
    delay_months = project.get("delay_months")
    orders = sorted(orders, key=lambda o: (parse_date(o.get("date")) or date.max, o.get("id") or 0))
    start = None
    for o in orders:
        if o.get("kind") == "commencement":
            start = parse_date(o.get("effective_date") or o.get("date"))
            break
    out = {"start": start, "end": None, "suspended_days": 0, "extension_days": 0,
           "elapsed": 0, "remaining": None, "late_days": 0, "progress": 0.0,
           "stopped": False, "stops": []}
    if not start:
        return out

    suspended = 0
    stop_since = None
    for o in orders:
        d = parse_date(o.get("effective_date") or o.get("date"))
        if not d:
            continue
        if o.get("kind") == "arret" and stop_since is None:
            stop_since = d
        elif o.get("kind") == "reprise" and stop_since is not None:
            days = max(0, (d - stop_since).days)
            suspended += days
            out["stops"].append((stop_since, d, days))
            stop_since = None
        elif o.get("kind") == "prolongation":
            out["extension_days"] += int(o.get("days") or 0)
    if stop_since is not None:
        days = max(0, (today - stop_since).days)
        suspended += days
        out["stops"].append((stop_since, None, days))
        out["stopped"] = True
    out["suspended_days"] = suspended

    if delay_months and not delay_days:
        base_end = add_months(start, int(delay_months))
    else:
        base_end = start + timedelta(days=int(delay_days))
    end = base_end + timedelta(days=suspended + out["extension_days"])
    out["end"] = end

    # works are finished at provisional acceptance (or the date the PV gives)
    finished = None
    for r in receptions or ():
        if r.get("kind") == "provisoire" and r.get("date"):
            finished = parse_date(r.get("works_end_date") or r.get("date"))
    ref = finished or today
    total = max(1, (end - start).days)
    active_elapsed = max(0, (ref - start).days - (suspended if ref >= today else 0))
    out["elapsed"] = active_elapsed
    out["remaining"] = (end - today).days if not finished else 0
    out["late_days"] = max(0, (ref - end).days)
    out["finished"] = finished
    out["progress"] = min(1.0, max(0.0, (min(ref, end) - start).days / float(total)))
    return out


def penalty_estimate(project, sched):
    """Delay penalties = late days x daily rate x base, capped."""
    terms = project.get("terms") or {}
    rate = term(terms, "penalty_rate_per_day") or 0
    cap_pct = term(terms, "penalty_cap_pct") or 0
    base = project.get("amount_ttc") or term(terms, "contract_amount_ttc") or 0
    late = sched.get("late_days", 0)
    raw = late * rate * base
    cap = base * cap_pct / 100.0
    amount = min(raw, cap) if cap else raw
    days_to_cap = int(cap / (rate * base)) if rate and base and cap else None
    return {"late_days": late, "rate": rate, "base": base, "raw": raw, "cap": cap,
            "amount": amount, "capped": bool(cap and raw >= cap),
            "ratio_of_cap": (raw / cap) if cap else 0.0, "days_to_cap": days_to_cap}


# --------------------------------------------------------------------------
# Quantities (bordereau des prix - détail estimatif)
# --------------------------------------------------------------------------

def item_amount(item, qty_key="qty_executed"):
    return (item.get(qty_key) or 0) * (item.get("unit_price_ht") or 0)


def quantities_summary(items, terms=None):
    initial_ht = sum(item_amount(i, "qty_contract") for i in items)
    executed_ht = sum(item_amount(i) for i in items)
    rows = []
    for i in items:
        qc = i.get("qty_contract") or 0
        qe = i.get("qty_executed") or 0
        var = ((qe - qc) / qc * 100.0) if qc else (100.0 if qe else 0.0)
        rows.append({"item": i, "variance_pct": var, "overrun": qe > qc + 1e-9,
                     "amount_ht": item_amount(i), "progress": (qe / qc) if qc else 0.0})
    inc = term(terms, "mass_increase_pct")
    mass_var = ((executed_ht - initial_ht) / initial_ht * 100.0) if initial_ht else 0.0
    return {"initial_ht": initial_ht, "executed_ht": executed_ht,
            "progress": (executed_ht / initial_ht) if initial_ht else 0.0,
            "mass_variation_pct": mass_var, "mass_increase_limit_pct": inc, "rows": rows}


def parse_bpde_csv(text):
    """Parse 'n;designation;unite;quantite;prix_unitaire' lines (also , or tab)."""
    items = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        sep = ";" if ";" in line else ("\t" if "\t" in line else ",")
        parts = [p.strip().strip('"') for p in line.split(sep)]
        if len(parts) < 5:
            continue
        qty = parse_decimal(parts[3])
        pu = parse_decimal(parts[4])
        if qty is None or pu is None:
            continue  # header line
        items.append({"number": parts[0], "designation": parts[1], "unit": parts[2],
                      "qty_contract": qty, "unit_price_ht": pu, "qty_executed": 0.0})
    return items


# --------------------------------------------------------------------------
# Décomptes
# --------------------------------------------------------------------------

def compute_decompte(project, items, previous, revision_ht=0.0, penalties=0.0,
                     advance_recovery=0.0, final=False):
    """Build payment statement N from cumulative executed quantities.

    `previous` = list of earlier décomptes (dicts with net_cumul_ttc).
    All amounts are cumulative except `net_ttc` (amount due this time).
    """
    terms = project.get("terms") or {}
    tva_pct = term(terms, "tva_pct") or 20.0
    ret_rate = (term(terms, "retenue_rate_pct") or 0) / 100.0
    ret_cap_pct = (term(terms, "retenue_cap_pct") or 0) / 100.0
    base = project.get("amount_ttc") or term(terms, "contract_amount_ttc") or 0

    works_ht = sum(item_amount(i) for i in items)
    total_ht = works_ht + (revision_ht or 0)
    tva = total_ht * tva_pct / 100.0
    total_ttc = total_ht + tva
    retenue = total_ttc * ret_rate
    if ret_cap_pct and base:
        retenue = min(retenue, base * ret_cap_pct)
    net_cumul = total_ttc - retenue - (penalties or 0) - (advance_recovery or 0)
    prev_cumul = max([p.get("net_cumul_ttc") or 0 for p in previous] or [0])
    detail = [{"number": i.get("number"), "designation": i.get("designation"), "unit": i.get("unit"),
               "qty": i.get("qty_executed") or 0, "pu": i.get("unit_price_ht") or 0,
               "amount": item_amount(i)} for i in items]
    return {
        "works_ht": works_ht, "revision_ht": revision_ht or 0, "total_ht": total_ht,
        "tva": tva, "total_ttc": total_ttc, "retenue": retenue, "penalties": penalties or 0,
        "advance_recovery": advance_recovery or 0, "net_cumul_ttc": net_cumul,
        "previous_ttc": prev_cumul, "net_ttc": net_cumul - prev_cumul,
        "number": len(previous) + 1, "final": bool(final), "detail": detail,
    }


def payment_status(decompte, terms, today=None):
    """Days outstanding for a décompte and whether interest is due."""
    today = today or date.today()
    limit = term(terms, "payment_delay_days") or 60
    start = parse_date(decompte.get("submitted_date"))
    paid = parse_date(decompte.get("paid_date"))
    if not start:
        return {"days": None, "limit": limit, "late": False, "paid": bool(paid)}
    end = paid or today
    days = (end - start).days
    return {"days": days, "limit": limit, "late": days > limit, "paid": bool(paid),
            "late_days": max(0, days - limit)}


# --------------------------------------------------------------------------
# Réceptions
# --------------------------------------------------------------------------

def reception_status(project, receptions, today=None):
    today = today or date.today()
    terms = project.get("terms") or {}
    months = int(term(terms, "warranty_months") or 12)
    prov = next((r for r in receptions if r.get("kind") == "provisoire"), None)
    final = next((r for r in receptions if r.get("kind") == "definitive"), None)
    out = {"provisional": prov, "final": final, "warranty_months": months,
           "warranty_end": None, "final_due": False, "days_to_final": None,
           "reserves_open": False}
    if prov and prov.get("date"):
        d = parse_date(prov["date"])
        out["warranty_end"] = add_months(d, months)
        out["days_to_final"] = (out["warranty_end"] - today).days
        out["final_due"] = not final and today >= out["warranty_end"]
        out["reserves_open"] = bool(prov.get("with_reserves")) and not prov.get("reserves_lifted_date")
    return out


def financial_summary(project, items, decomptes, sched):
    q = quantities_summary(items, project.get("terms"))
    pen = penalty_estimate(project, sched)
    paid = sum(d.get("paid_amount") or 0 for d in decomptes if d.get("paid_date"))
    due = sum(d.get("net_ttc") or 0 for d in decomptes if not d.get("paid_date"))
    last = max(decomptes, key=lambda d: d.get("number") or 0) if decomptes else None
    return {"initial_ht": q["initial_ht"], "executed_ht": q["executed_ht"],
            "progress": q["progress"], "paid_ttc": paid, "unpaid_ttc": due,
            "retenue": (last or {}).get("retenue", 0), "penalties_est": pen["amount"],
            "penalty": pen, "quantities": q}
