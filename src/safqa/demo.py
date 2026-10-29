"""Demonstration dataset: a fictitious works company with three contracts
at different stages, a tender pipeline, suppliers, banks, expenses,
guarantees, a site journal and a schedule.  Dates are relative to today so
the alerts and the cash-flow forecast are meaningful whenever it is loaded.
"""

import os
from datetime import date, timedelta

from . import analysis
from . import tracking as tr

COMPANY = {"name": "Atlas Travaux SARL (démo)", "ice": "001234567000089", "rc": "45123 Rabat",
           "if_number": "12345678", "cnss": "8765432", "patente": "25478963",
           "address": "Avenue Hassan II", "city": "Rabat", "phone": "+212 5 37 00 00 00",
           "email": "contact@atlas-travaux.example", "manager": "Directeur technique"}

SAMPLE_CPS = os.path.join(os.path.dirname(__file__), "data", "sample_cps.txt")


def clear_all(store):
    for table in ("projects", "documents", "checklist", "orders", "items", "decomptes", "receptions", "chat",
                  "tiers", "tenders", "expenses", "budget_lines", "guarantees", "journal", "tasks",
                  "measurements"):
        store.x("DELETE FROM %s" % table)


def load_demo(store, today=None, docs_dir=None):
    today = today or date.today()

    def d(days):
        return (today + timedelta(days=days)).isoformat()

    if not store.get_json("company"):
        store.set_json("company", COMPANY)

    T = {}
    for kind, name, city, extra in [
        ("client", "Commune de Témara", "Témara", {}),
        ("client", "Direction provinciale de l'Équipement - Settat", "Settat", {}),
        ("client", "Régie de distribution d'eau - région Centre (démo)", "Khouribga", {}),
        ("fournisseur", "Carrières Al Amal", "Skhirat", {"phone": "+212 6 61 11 22 33"}),
        ("fournisseur", "Béton Prêt Rabat", "Rabat", {}),
        ("fournisseur", "Acier & Tubes Distribution", "Casablanca", {}),
        ("fournisseur", "Transport Chaoui", "Settat", {}),
        ("fournisseur", "Location Engins du Centre", "Berrechid", {}),
        ("sous_traitant", "Électricité Nour", "Rabat", {}),
        ("bet", "Laboratoire Essais BTP (démo)", "Rabat", {}),
        ("banque", "Banque A (démo)", "Rabat", {"contact": "Chargé d'affaires entreprises"}),
        ("banque", "Banque B (démo)", "Casablanca", {}),
    ]:
        row = {"kind": kind, "name": name, "city": city, "created_at": today.isoformat()}
        row.update(extra)
        T[name] = store.insert("tiers", row)
    bank_a, bank_b = T["Banque A (démo)"], T["Banque B (démo)"]

    # ------------------------------------------------------------------ P1: voirie, en retard
    p1 = store.save_project({
        "ref": "12/2026", "title": "Aménagement de voirie et assainissement - quartier Al Wifaq",
        "owner": "Commune de Témara", "client_id": T["Commune de Témara"], "location": "Témara",
        "category": "Voirie", "manager": "Ing. Karim B.", "amount_ttc": 2450000.0,
        "approval_notif_date": d(-230), "delay_days": 180, "delay_months": 6, "status": "en_cours"})
    if os.path.exists(SAMPLE_CPS):
        doc = analysis.ingest(SAMPLE_CPS, "CPS_AO_12_2026.txt", "CPS")
        doc.update(project_id=p1, uploaded_at=d(-225))
        store.insert("documents", doc)
    for code in ("ACTE_ENGAGEMENT", "DECL_HONNEUR", "CAUTION_PROV", "ATTEST_FISCALE", "ATTEST_CNSS", "RC_CERT",
                 "POUVOIRS", "BPDE_SIGNE", "NOTIF_APPROB", "CAUTION_DEF", "OS_COMMENCEMENT", "PROGRAMME_EXEC",
                 "JOURNAL_CHANTIER", "ATTACHEMENTS", "DECOMPTES"):
        store.set_check(p1, code, True, d(-200))
    for o in [("1", "commencement", -210, "Démarrage des travaux"), ("2", "arret", -120, "Intempéries - fortes pluies"),
              ("3", "reprise", -105, "Reprise après intempéries")]:
        store.insert("orders", {"project_id": p1, "number": o[0], "kind": o[1], "date": d(o[2]), "note": o[3]})
    items1 = [("1", "Terrassements généraux en déblai", "m³", 4200, 45), ("2", "Couche de fondation en GNF", "m³", 1800, 160),
              ("3", "Enrobés bitumineux 6 cm", "m²", 9500, 85), ("4", "Conduite PVC Ø400 assainissement", "ml", 1200, 520),
              ("5", "Regards de visite préfabriqués", "U", 40, 6500), ("6", "Bordures de trottoir T3", "ml", 2600, 95)]
    ids1 = [store.insert("items", {"project_id": p1, "number": n, "designation": des, "unit": u, "qty_contract": q,
                                   "unit_price_ht": pu, "qty_executed": 0}) for n, des, u, q, pu in items1]
    _measure(store, p1, ids1, [(-150, [2100, 500, 0, 600, 12, 0]), (-95, [1500, 700, 3500, 500, 14, 900]),
                               (-35, [1000, 300, 2500, 150, 4, 1100])], d)
    _decomptes(store, p1, [(-140, -138, -80, [2100, 500, 0, 600, 12, 0]),
                           (-85, -83, None, [3600, 1200, 3500, 1100, 26, 900])], d)
    for cat, amount in [("materiaux", 640000), ("main_oeuvre", 360000), ("materiel", 240000),
                        ("sous_traitance", 120000), ("transport", 80000), ("frais_generaux", 110000)]:
        store.insert("budget_lines", {"project_id": p1, "category": cat, "amount_ht": amount})
    _expenses(store, p1, T, d, [
        (-205, "frais_generaux", "Installation de chantier", None, 38000, "paye"),
        (-190, "materiel", "Location pelle hydraulique - mois 1", "Location Engins du Centre", 62000, "paye"),
        (-170, "materiaux", "GNF 0/31.5 - 500 m³", "Carrières Al Amal", 47500, "paye"),
        (-160, "materiaux", "Tuyaux PVC Ø400 - 600 ml", "Acier & Tubes Distribution", 168000, "paye"),
        (-150, "main_oeuvre", "Paie équipe terrassement - mois 2", None, 68000, "paye"),
        (-130, "materiel", "Location compacteur et niveleuse", "Location Engins du Centre", 98000, "paye"),
        (-100, "materiaux", "Regards préfabriqués - 26 U", "Béton Prêt Rabat", 104000, "paye"),
        (-90, "main_oeuvre", "Paie équipes - mois 4", None, 92000, "paye"),
        (-75, "materiaux", "Enrobés - 3 500 m²", "Carrières Al Amal", 154000, "facture", -15),
        (-60, "materiel", "Location finisseur et cylindre", "Location Engins du Centre", 112000, "facture", -5),
        (-45, "transport", "Transport matériaux - trimestre", "Transport Chaoui", 46000, "facture", 15),
        (-40, "sous_traitance", "Réseau éclairage provisoire", "Électricité Nour", 58000, "engage"),
        (-30, "main_oeuvre", "Paie équipes - mois 6", None, 96000, "paye"),
        (-20, "materiaux", "Bordures T3 - 1 100 ml", "Béton Prêt Rabat", 66000, "facture", 25),
        (-10, "etudes", "Essais de compactage et carottages", "Laboratoire Essais BTP (démo)", 18500, "facture", 20),
    ])
    store.insert("guarantees", {"project_id": p1, "kind": "definitive", "bank_id": bank_a, "ref": "CD-2026-0412",
                                "amount": 73500, "issue_date": d(-215), "expiry_date": d(20), "status": "active",
                                "commission_pct": 1.5})
    for i, (days, w, n, work, inc) in enumerate([
            (-3, "Ensoleillé", 28, "Pose bordures T3 côté nord (180 ml). Enrobés rue 4.", ""),
            (-2, "Nuageux", 26, "Enrobés rue 5 (650 m²). Contrôle densité par le laboratoire.", ""),
            (-1, "Pluie", 12, "Arrêt partiel l'après-midi pour pluie. Curage regards R12-R15.",
             "Pluie à partir de 14 h : travaux d'enrobés suspendus."),
            (0, "Ensoleillé", 27, "Reprise enrobés rue 5. Réglage trottoirs.", "")]):
        store.insert("journal", {"project_id": p1, "date": d(days), "weather": w, "workforce": n,
                                 "equipment": "Finisseur, cylindre, camions x3", "work_done": work,
                                 "incidents": inc, "visitors": "BET de contrôle" if i == 1 else "",
                                 "created_at": d(days)})
    for i, (name, s, e, prog) in enumerate([
            ("Installation de chantier", -210, -200, 100), ("Terrassements généraux", -200, -120, 100),
            ("Réseau d'assainissement", -170, -60, 90), ("Couche de fondation", -110, -40, 85),
            ("Enrobés bitumineux", -60, 10, 55), ("Bordures et trottoirs", -40, 20, 45),
            ("Signalisation et finitions", 5, 30, 0)]):
        store.insert("tasks", {"project_id": p1, "name": name, "start": d(s), "end": d(e), "progress": prog,
                               "sort": i, "responsible": "Chef de chantier"})

    # ------------------------------------------------------------------ P2: école, démarrage
    p2 = store.save_project({
        "ref": "07/2026", "title": "Construction d'une école primaire de 12 classes",
        "owner": "Direction provinciale de l'Équipement - Settat",
        "client_id": T["Direction provinciale de l'Équipement - Settat"], "location": "Settat",
        "category": "Bâtiment", "manager": "Ing. Salma E.", "amount_ttc": 4980000.0,
        "approval_notif_date": d(-40), "delay_days": 360, "delay_months": 12, "status": "en_cours",
        "terms": {"penalty_rate_per_day": {"value": 0.001, "source": "saisie", "article_label": "CPS art. 14"},
                  "penalty_cap_pct": {"value": 8.0, "source": "saisie", "article_label": "CPS art. 14"}}})
    for code in ("ACTE_ENGAGEMENT", "DECL_HONNEUR", "CAUTION_PROV", "ATTEST_FISCALE", "ATTEST_CNSS", "RC_CERT",
                 "POUVOIRS", "BPDE_SIGNE", "NOTIF_APPROB", "OS_COMMENCEMENT"):
        store.set_check(p2, code, True, d(-30))
    store.insert("orders", {"project_id": p2, "number": "1", "kind": "commencement", "date": d(-25),
                            "note": "Ordre de service de commencement"})
    items2 = [("1", "Fouilles en rigoles et en puits", "m³", 1450, 70), ("2", "Béton armé en fondations", "m³", 620, 1900),
              ("3", "Béton armé en élévation", "m³", 780, 2300), ("4", "Maçonnerie en agglos 20 cm", "m²", 5200, 210),
              ("5", "Enduits intérieurs et extérieurs", "m²", 11800, 75), ("6", "Menuiserie aluminium", "m²", 520, 1450)]
    ids2 = [store.insert("items", {"project_id": p2, "number": n, "designation": des, "unit": u, "qty_contract": q,
                                   "unit_price_ht": pu, "qty_executed": 0}) for n, des, u, q, pu in items2]
    _measure(store, p2, ids2, [(-5, [900, 120, 0, 0, 0, 0])], d)
    for cat, amount in [("materiaux", 1650000), ("main_oeuvre", 980000), ("materiel", 360000),
                        ("sous_traitance", 520000), ("transport", 110000), ("frais_generaux", 240000)]:
        store.insert("budget_lines", {"project_id": p2, "category": cat, "amount_ht": amount})
    _expenses(store, p2, T, d, [
        (-24, "frais_generaux", "Installation de chantier et clôture", None, 64000, "paye"),
        (-15, "materiel", "Location pelle et chargeuse", "Location Engins du Centre", 54000, "facture", 30),
        (-8, "materiaux", "Béton B25 - 120 m³", "Béton Prêt Rabat", 98400, "facture", 45),
        (-6, "materiaux", "Acier HA - 14 t", "Acier & Tubes Distribution", 126000, "engage"),
    ])
    store.insert("guarantees", {"tender_id": None, "project_id": p2, "kind": "provisoire", "bank_id": bank_b,
                                "ref": "CP-2026-0077", "amount": 50000, "issue_date": d(-120), "expiry_date": d(-10),
                                "status": "mainlevee_demandee", "commission_pct": 1.2})
    for i, (name, s, e, prog) in enumerate([
            ("Installation de chantier", -25, -15, 100), ("Terrassements et fouilles", -15, 15, 55),
            ("Fondations", 5, 60, 0), ("Gros œuvre - élévation", 50, 200, 0), ("Second œuvre", 180, 320, 0),
            ("VRD et aménagements extérieurs", 280, 340, 0)]):
        store.insert("tasks", {"project_id": p2, "name": name, "start": d(s), "end": d(e), "progress": prog,
                               "sort": i, "responsible": "Conducteur de travaux"})
    store.insert("journal", {"project_id": p2, "date": d(-1), "weather": "Ensoleillé", "workforce": 18,
                             "equipment": "Pelle, chargeuse, bétonnière", "work_done": "Fouilles bloc B. Béton de propreté bloc A.",
                             "incidents": "", "visitors": "Maître d'ouvrage", "created_at": d(-1)})

    # ------------------------------------------------------------------ P3: AEP, réceptionné
    p3 = store.save_project({
        "ref": "31/2025", "title": "Réhabilitation du réseau d'eau potable - centre urbain",
        "owner": "Régie de distribution d'eau - région Centre (démo)",
        "client_id": T["Régie de distribution d'eau - région Centre (démo)"], "location": "Khouribga",
        "category": "Hydraulique", "manager": "Ing. Karim B.", "amount_ttc": 1436400.0,
        "approval_notif_date": d(-520), "delay_days": 240, "delay_months": 8, "status": "receptionne"})
    for code in ("ACTE_ENGAGEMENT", "DECL_HONNEUR", "CAUTION_PROV", "ATTEST_FISCALE", "ATTEST_CNSS", "RC_CERT",
                 "POUVOIRS", "BPDE_SIGNE", "NOTIF_APPROB", "CAUTION_DEF", "ASSURANCES", "OS_COMMENCEMENT",
                 "PROGRAMME_EXEC", "JOURNAL_CHANTIER", "ATTACHEMENTS", "DECOMPTES", "PV_RECEP_PROV", "RECOLEMENT"):
        store.set_check(p3, code, True, d(-300))
    store.insert("orders", {"project_id": p3, "number": "1", "kind": "commencement", "date": d(-480), "note": ""})
    items3 = [("1", "Conduite PEHD Ø110", "ml", 3200, 180), ("2", "Conduite PEHD Ø160", "ml", 1500, 260),
              ("3", "Branchements particuliers", "U", 210, 1100)]
    ids3 = [store.insert("items", {"project_id": p3, "number": n, "designation": des, "unit": u, "qty_contract": q,
                                   "unit_price_ht": pu, "qty_executed": 0}) for n, des, u, q, pu in items3]
    _measure(store, p3, ids3, [(-400, [1800, 600, 80]), (-300, [1380, 900, 128])], d)
    _decomptes(store, p3, [(-390, -388, -330, [1800, 600, 80]), (-290, -287, -230, [3180, 1500, 208])], d,
               final_last=True)
    store.insert("receptions", {"project_id": p3, "kind": "provisoire", "date": d(-245), "with_reserves": 0})
    for cat, amount in [("materiaux", 480000), ("main_oeuvre", 260000), ("materiel", 120000), ("transport", 40000)]:
        store.insert("budget_lines", {"project_id": p3, "category": cat, "amount_ht": amount})
    _expenses(store, p3, T, d, [
        (-470, "materiaux", "Tubes PEHD Ø110 et Ø160", "Acier & Tubes Distribution", 452000, "paye"),
        (-430, "main_oeuvre", "Paie équipes pose", None, 248000, "paye"),
        (-420, "materiel", "Location pelle et compacteur", "Location Engins du Centre", 106000, "paye"),
        (-400, "transport", "Transport tubes", "Transport Chaoui", 35000, "paye"),
    ])
    store.insert("guarantees", {"project_id": p3, "kind": "retenue", "bank_id": bank_a, "ref": "CRG-2025-1190",
                                "amount": 77000, "issue_date": d(-300), "expiry_date": d(140), "status": "active",
                                "commission_pct": 1.5})

    # ------------------------------------------------------------------ tenders
    for ref, title, owner, cat, est, dep, status, bid, extra in [
        ("45/2026", "Aménagement d'une place publique et parkings", "Commune de Témara", "Aménagement urbain",
         3200000, 12, "veille", None, {"caution_amount": 32000, "qualification": "Classe 3 - secteur B"}),
        ("52/2026", "Construction d'un centre de santé communal", "Direction provinciale de l'Équipement - Settat",
         "Bâtiment", 5600000, 5, "etude", 5420000, {"caution_amount": 56000}),
        ("38/2026", "Renforcement de routes rurales - lot 2", "Direction provinciale de l'Équipement - Settat",
         "Voirie", 6400000, -20, "soumis", 6150000, {"opening_date": d(3), "caution_amount": 64000}),
        ("21/2026", "Aménagement de voirie et assainissement - quartier Al Wifaq", "Commune de Témara", "Voirie",
         2600000, -260, "gagne", 2450000, {"project_id": p1}),
        ("17/2026", "Construction d'un bâtiment administratif", "Commune de Témara", "Bâtiment",
         4100000, -90, "perdu", 4020000, {"winner": "Entreprise concurrente", "winning_bid_ttc": 3890000}),
        ("09/2026", "Construction d'une école primaire de 12 classes", "Direction provinciale de l'Équipement - Settat",
         "Bâtiment", 5200000, -75, "gagne", 4980000, {"project_id": p2}),
    ]:
        row = {"ref": ref, "title": title, "owner": owner, "client_id": T.get(owner), "category": cat,
               "estimate_ttc": est, "deposit_date": d(dep), "status": status, "bid_ttc": bid,
               "created_at": d(min(dep, 0) - 30), "updated_at": d(0)}
        row.update(extra)
        tid = store.insert("tenders", row)
        if status in ("veille", "etude", "soumis") and extra.get("caution_amount"):
            store.insert("guarantees", {"tender_id": tid, "kind": "provisoire", "bank_id": bank_b,
                                        "ref": "CP-%s" % ref.replace("/", "-"), "amount": extra["caution_amount"],
                                        "issue_date": d(dep - 10), "expiry_date": d(dep + 75),
                                        "status": "active", "commission_pct": 1.2})
    store.set("demo_loaded", "1")
    return {"projects": [p1, p2, p3]}


def _measure(store, pid, item_ids, rounds, d):
    for k, (days, qtys) in enumerate(rounds, 1):
        for item_id, q in zip(item_ids, qtys):
            if q:
                store.insert("measurements", {"project_id": pid, "item_id": item_id, "date": d(days), "qty": q,
                                              "ref": "Attachement n° %d" % k})
    for item_id in item_ids:
        store.recompute_item(item_id)


def _decomptes(store, pid, rounds, d, final_last=False):
    """rounds: (date, submitted, paid or None, cumulative quantities)."""
    project = store.project(pid)
    items = store.children("items", pid)
    previous = []
    for k, (day, sub, paid, qtys) in enumerate(rounds):
        snap = [dict(it, qty_executed=q) for it, q in zip(items, qtys)]
        res = tr.compute_decompte(dict(project, terms=project.get("terms") or {}), snap, previous,
                                  final=final_last and k == len(rounds) - 1)
        res.update(project_id=pid, date=d(day), submitted_date=d(sub), status="émis")
        if paid is not None:
            res.update(paid_date=d(paid), paid_amount=res["net_ttc"])
        store.insert("decomptes", res)
        previous.append(res)


def _expenses(store, pid, tiers, d, rows):
    for row in rows:
        day, cat, lbl, supplier, amount, status = row[:6]
        due = row[6] if len(row) > 6 else None
        store.insert("expenses", {
            "project_id": pid, "date": d(day), "category": cat, "label": lbl,
            "supplier_id": tiers.get(supplier) if supplier else None,
            "ref": "F-%s-%03d" % (d(day)[:7].replace("-", ""), abs(day)) if supplier else "",
            "amount_ht": float(amount), "tva_pct": 0.0 if cat == "main_oeuvre" else 20.0, "status": status,
            "due_date": d(due) if due is not None else None,
            "paid_date": d(day + 30) if status == "paye" else None})
