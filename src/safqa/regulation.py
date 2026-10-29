"""Reference data for Moroccan public works contracts.

Values below are the usual defaults of the regulatory framework. A CPS can
set its own values within the limits of the texts, so the app always prefers
the value extracted from the uploaded CPS and falls back on these defaults
only when the CPS is silent.  Users must check the texts in force: they are
amended regularly.
"""

TEXTS = {
    "DECRET_MP": "Décret n° 2-22-431 du 8 mars 2023 relatif aux marchés publics",
    "CCAG_T": "CCAG-T - Décret n° 2-14-394 du 13 mai 2016 (marchés de travaux)",
    "DELAIS_PAIEMENT": "Décret n° 2-16-344 du 22 juillet 2016 fixant les délais de "
                       "paiement et les intérêts moratoires",
    "NANTISSEMENT": "Loi n° 112-13 relative au nantissement des marchés publics",
    "TVA": "Code général des impôts - TVA",
}

DEFAULTS = {
    # cautionnement définitif, % du montant initial
    "caution_definitive_pct": 3.0,
    "caution_definitive_delay_days": 30,
    # retenue de garantie: 10 % de chaque acompte, plafonnée à 7 % du montant initial
    "retenue_rate_pct": 10.0,
    "retenue_cap_pct": 7.0,
    # pénalités de retard: taux fixé par le CPS, usuellement 1/1000 par jour
    "penalty_rate_per_day": 0.001,
    "penalty_cap_pct": 8.0,
    "warranty_months": 12,
    "payment_delay_days": 60,
    "tva_pct": 20.0,
    "os_start_max_days": 60,
    "mass_increase_pct": 10.0,
    "mass_decrease_pct": 25.0,
}

DEFAULT_SOURCES = {
    "caution_definitive_pct": TEXTS["CCAG_T"] + " - cautionnement définitif",
    "caution_definitive_delay_days": TEXTS["CCAG_T"] + " - constitution du cautionnement définitif",
    "retenue_rate_pct": TEXTS["CCAG_T"] + " - retenue de garantie",
    "retenue_cap_pct": TEXTS["CCAG_T"] + " - retenue de garantie",
    "penalty_rate_per_day": "Taux usuel - doit être fixé par le CPS",
    "penalty_cap_pct": TEXTS["CCAG_T"] + " - pénalités pour retard (plafond)",
    "warranty_months": TEXTS["CCAG_T"] + " - délai de garantie",
    "payment_delay_days": TEXTS["DELAIS_PAIEMENT"],
    "tva_pct": TEXTS["TVA"],
    "os_start_max_days": TEXTS["CCAG_T"] + " - ordre de service de commencement",
    "mass_increase_pct": TEXTS["CCAG_T"] + " - augmentation dans la masse",
    "mass_decrease_pct": TEXTS["CCAG_T"] + " - diminution dans la masse",
}

DISCLAIMER = ("Les références réglementaires sont indicatives. Vérifiez toujours le "
              "texte en vigueur et les clauses de votre CPS ; en cas de doute, "
              "consultez un juriste spécialisé en commande publique.")

# Checklist of documents per phase: (code, label, phase, mandatory)
DOCUMENT_CHECKLIST = [
    # Soumission
    ("ACTE_ENGAGEMENT", "Acte d'engagement signé", "Soumission", True),
    ("DECL_HONNEUR", "Déclaration sur l'honneur", "Soumission", True),
    ("CAUTION_PROV", "Cautionnement provisoire (ou attestation)", "Soumission", True),
    ("ATTEST_FISCALE", "Attestation de régularité fiscale", "Soumission", True),
    ("ATTEST_CNSS", "Attestation CNSS", "Soumission", True),
    ("RC_CERT", "Certificat d'immatriculation au registre de commerce", "Soumission", True),
    ("QUALIF_CLASSIF", "Certificat de qualification et de classification (BTP)", "Soumission", False),
    ("POUVOIRS", "Pièces justifiant les pouvoirs du signataire", "Soumission", True),
    ("BPDE_SIGNE", "Bordereau des prix - détail estimatif signé", "Soumission", True),
    # Démarrage
    ("NOTIF_APPROB", "Notification de l'approbation du marché", "Démarrage", True),
    ("CAUTION_DEF", "Cautionnement définitif", "Démarrage", True),
    ("ASSURANCES", "Attestations d'assurance (AT, RC, TRC, véhicules)", "Démarrage", True),
    ("OS_COMMENCEMENT", "Ordre de service de commencement", "Démarrage", True),
    ("PROGRAMME_EXEC", "Programme / planning d'exécution", "Démarrage", True),
    ("PLANS_EXEC", "Plans d'exécution approuvés", "Démarrage", False),
    ("PV_INSTALLATION", "PV d'installation de chantier / remise du site", "Démarrage", False),
    # Exécution
    ("JOURNAL_CHANTIER", "Journal / cahier de chantier", "Exécution", True),
    ("ATTACHEMENTS", "Attachements et métrés contradictoires", "Exécution", True),
    ("PV_REUNIONS", "PV des réunions de chantier", "Exécution", False),
    ("ESSAIS_LABO", "Résultats des essais de laboratoire", "Exécution", False),
    ("DECOMPTES", "Décomptes provisoires signés", "Exécution", True),
    # Réception
    ("PV_RECEP_PROV", "PV de réception provisoire", "Réception", True),
    ("LEVEE_RESERVES", "PV de levée des réserves", "Réception", False),
    ("RECOLEMENT", "Dossier de récolement (plans conformes à l'exécution)", "Réception", True),
    ("PV_RECEP_DEF", "PV de réception définitive", "Réception", True),
    ("DECOMPTE_DEF", "Décompte définitif signé", "Réception", True),
    ("MAINLEVEE", "Mainlevée du cautionnement / restitution de la retenue", "Réception", True),
]

PHASES = ["Soumission", "Démarrage", "Exécution", "Réception"]

# Clauses a works CPS is expected to contain: (code, label, keywords)
EXPECTED_CLAUSES = [
    ("OBJET", "Objet du marché", ("objet du marché", "objet du present marche", "objet du présent marché")),
    ("PIECES", "Pièces constitutives du marché", ("pièces constitutives", "pieces constitutives")),
    ("DELAI_EXEC", "Délai d'exécution", ("délai d'exécution", "delai d'execution")),
    ("PENALITES", "Pénalités pour retard", ("pénalité", "penalite")),
    ("CAUTION", "Cautionnements", ("cautionnement",)),
    ("RETENUE", "Retenue de garantie", ("retenue de garantie",)),
    ("ASSURANCE", "Assurances et responsabilités", ("assurance",)),
    ("PRIX", "Nature des prix / révision", ("nature des prix", "révision des prix", "revision des prix", "prix fermes",
                                             "prix révisables", "prix revisables", "prix ferme")),
    ("PAIEMENT", "Modalités de paiement", ("paiement", "décompte", "decompte")),
    ("RECEPTION", "Réception provisoire et définitive", ("réception provisoire", "reception provisoire")),
    ("GARANTIE", "Délai de garantie", ("délai de garantie", "delai de garantie")),
    ("RESILIATION", "Résiliation", ("résiliation", "resiliation")),
    ("LITIGES", "Règlement des différends", ("litige", "différend", "different", "contestation")),
]
