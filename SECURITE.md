# Sécurité et protection des données — Safqa Cloud

## Ce qui est protégé, et comment

| Risque | Protection en place |
|---|---|
| Interception sur le réseau (Wi-Fi public, 4G) | HTTPS obligatoire : l'application refuse tout serveur non HTTPS ; en-tête HSTS. |
| Vol de la base de données | Données des entreprises **chiffrées AES-256-GCM** avant d'être écrites ; chaque enregistrement est lié (données associées) à son entreprise, sa table et son identifiant : impossible de le déplacer vers une autre entreprise. Fichiers (CPS, PDF) chiffrés de la même façon. La clé (`SAFQA_DATA_KEY`) n'est jamais stockée dans la base. |
| Mots de passe volés dans la base | Jamais stockés : empreinte **scrypt** (lente et gourmande en mémoire) avec sel unique. |
| Devinette de mot de passe / force brute | 10 caractères minimum, mots de passe courants refusés ; **verrouillage 15 min après 5 échecs** ; limitation du nombre de requêtes par adresse IP ; temps de réponse identique que l'e-mail existe ou non. |
| Mot de passe compromis | **Double authentification** (application d'authentification, standard RFC 6238) — obligatoire pour l'équipe d'administration ; changer le mot de passe déconnecte les autres appareils. |
| Téléphone perdu ou volé | Sessions révocables à distance (back-office, ou propriétaire de l'entreprise) ; sessions expirées après 21 jours d'inactivité et 60 jours maximum ; jetons de session aléatoires stockés uniquement sous forme d'empreinte côté serveur. |
| Un client voit les données d'un autre | Cloisonnement vérifié à **chaque** requête (appartenance à l'entreprise) ; testé automatiquement. |
| Un collaborateur dépasse ses droits | Rôles : propriétaire, administrateur, collaborateur, lecture seule. Le serveur refuse les modifications d'un compte en lecture seule. Le dernier propriétaire ne peut pas être retiré. |
| Code d'invitation intercepté | Usage unique, expiration (7 jours par défaut), stocké sous forme d'empreinte. |
| Attaque du back-office (XSS, clickjacking) | Aucune donnée utilisateur insérée comme HTML ; Content-Security-Policy stricte ; interdiction d'affichage dans un cadre ; jeton conservé seulement le temps de l'onglet. |
| Fichiers corrompus ou falsifiés | Empreinte SHA-256 vérifiée à l'envoi et à la réception. |
| Fuite de la clé API IA | La clé Anthropic reste sur le serveur ; les téléphones ne la reçoivent jamais. Les clés API, licences et jetons ne sont jamais synchronisés entre appareils. |
| Traçabilité | Journal de sécurité : inscriptions, connexions et échecs, 2FA, invitations, rôles, réinitialisations, exports, suppressions, actions des administrateurs, avec date et adresse IP. |
| Erreur de configuration en production | Le serveur refuse de démarrer sans clé de chiffrement solide ni PostgreSQL. |
| Le serveur s'arrête | L'application fonctionne entièrement hors-ligne ; les modifications sont envoyées au retour du réseau. |

Ces protections sont vérifiées par des tests automatiques (`tests/test_cloud.py`, `tests/test_cloud_sync.py`)
exécutés sur SQLite et PostgreSQL à chaque modification du code.

## Vos responsabilités d'éditeur (bonnes pratiques)

1. **Double authentification partout** : Render, GitHub, Anthropic, votre messagerie, le back-office.
2. **`SAFQA_DATA_KEY`** : sauvegardée hors ligne, jamais partagée, jamais modifiée.
3. **Accès minimum** : seules les personnes qui en ont besoin dans `SAFQA_ADMIN_EMAILS`.
4. **Clé Anthropic** : définissez un plafond de dépense mensuel dans console.anthropic.com ; régénérez-la en cas de
   doute (puis mettez à jour Render).
5. **Sauvegardes** : vérifiez chaque mois qu'une restauration est possible.
6. **Mises à jour** : relancez un déploiement Render au moins une fois par mois (correctifs de sécurité de l'image).

## Conformité — loi n° 09-08 (protection des données personnelles)

À faire avant l'ouverture commerciale (à valider avec un juriste) :

- [ ] **Déclaration du traitement auprès de la CNDP** (www.cndp.ma) : gestion des comptes clients et des données
      de leurs marchés.
- [ ] **Transfert hors du Maroc** : si les données sont hébergées à l'étranger (ex. Render, région Francfort ; IA
      Anthropic), demander l'autorisation/déclaration de transfert prévue par la loi — ou héberger au Maroc
      (voir `DEPLOIEMENT.md`, option VPS).
- [ ] **Politique de confidentialité et conditions d'utilisation** : compléter le modèle servi à
      `/confidentialite` (`server/safqa_cloud/static/confidentialite.html`).
- [ ] **Contrats** avec vos sous-traitants (hébergeur, fournisseur IA, e-mail) couvrant la confidentialité.
- [ ] **Registre des traitements** et durée de conservation (modèle : 90 jours après clôture d'un espace).
- [ ] **Droits des personnes** : adresse de contact pour accès / rectification / opposition. L'export et la
      suppression d'un espace entreprise sont disponibles pour le propriétaire.

## En cas d'incident (fuite, compte piraté)

1. **Couper** : back-office → désactiver le compte concerné / suspendre l'entreprise ; Render → *Suspend* si
   nécessaire.
2. **Révoquer** : déconnecter les sessions ; régénérer la clé Anthropic et les mots de passe des comptes
   d'hébergement.
3. **Analyser** : journal de sécurité (back-office) et logs Render.
4. **Informer** les clients concernés et, selon la gravité, la CNDP.
5. **Corriger**, puis consigner l'incident et les mesures prises.

## Signaler une vulnérabilité

Écrivez à [adresse sécurité]. Merci de ne pas divulguer publiquement avant correction.
