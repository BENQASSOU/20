# Mettre Safqa Cloud en ligne — guide pas à pas (sans être développeur)

Ce guide vous permet de lancer le serveur **Safqa Cloud** en une trentaine de minutes, sans écrire de code.
Une fois en ligne, vos clients :

- créent leur compte dans l'application, invitent leurs collaborateurs ;
- retrouvent leurs marchés sur tous leurs appareils (synchronisation automatique, même après une coupure réseau) ;
- utilisent l'IA Claude incluse dans leur abonnement, sans clé API ;

et vous, vous gérez tout depuis le **back-office web** : comptes, entreprises, abonnements, sécurité.

```
 Téléphones Android (app Safqa)  ──HTTPS──▶  Safqa Cloud (serveur)  ──▶  Base PostgreSQL (données chiffrées)
                                                   │
 Vous (navigateur)  ──HTTPS──▶  /admin  (back-office, double authentification obligatoire)
```

---

## Ce qu'il vous faut

| Quoi | Pourquoi | Coût indicatif* |
|---|---|---|
| Un compte **Render** (render.com) | héberge le serveur et la base de données, HTTPS automatique | serveur « Starter » ≈ 7 $/mois + base « Basic » ≈ 6 $/mois |
| Une clé **API Anthropic** (console.anthropic.com) | l'IA incluse dans les abonnements | à l'usage (quelques centimes par question) |
| Votre compte **GitHub** (déjà utilisé pour l'APK) | Render lit le code ici | gratuit |
| *(facultatif)* un nom de domaine `cloud.votre-domaine.ma` | adresse professionnelle | ≈ 100–200 DH/an |
| *(facultatif)* un service d'e-mail SMTP (Brevo, Google Workspace…) | « mot de passe oublié » par e-mail | gratuit à faible volume |

\* Prix à vérifier sur render.com/pricing au moment de l'inscription : ils évoluent.

---

## Étape 1 — Créer le compte Render

1. Allez sur **render.com** → **Get Started** → **Sign in with GitHub**.
2. Autorisez Render à accéder au dépôt **BENQASSOU/20**.
3. Activez tout de suite la **double authentification** de votre compte Render (Account Settings › Security).
   Faites de même sur GitHub : ces deux comptes donnent accès à toutes les données.

## Étape 2 — Lancer le « Blueprint » (installation automatique)

1. Dans Render : **New +** → **Blueprint**.
2. Choisissez le dépôt **BENQASSOU/20** et la branche qui contient le fichier `render.yaml`
   (aujourd'hui `claude/moroccan-procurement-ai-m9lx41`, ou `main` une fois la branche fusionnée).
3. Render affiche ce qu'il va créer : une base **safqa-db** et un service web **safqa-cloud**. Il vous demande 3 valeurs :

   | Variable | Quoi mettre |
   |---|---|
   | `SAFQA_ADMIN_EMAILS` | votre e-mail (ex. `ayoub@votre-domaine.ma`). Ce compte deviendra administrateur. Plusieurs adresses : séparez par des virgules. |
   | `ANTHROPIC_API_KEY` | votre clé `sk-ant-…` (console.anthropic.com › API Keys). Laissez vide pour démarrer sans IA serveur. |
   | `SAFQA_LICENSE_SECRET` | la **même** valeur que le secret GitHub `SAFQA_LICENSE_SECRET` (clés de licence). Si vous n'en avez pas : inventez une longue phrase secrète et mettez-la aux deux endroits. |

4. Cliquez **Apply**. Attendez 5 à 10 minutes (création de la base, construction du serveur).
5. Quand le service **safqa-cloud** est « Live », copiez son adresse (en haut de la page), par exemple
   `https://safqa-cloud-ab12.onrender.com`.
6. Vérification : ouvrez `https://…onrender.com/healthz` dans votre navigateur. Vous devez lire
   `{"ok":true,"db":"postgres",…}`.

## Étape 3 — ⚠️ Mettre la clé de chiffrement en lieu sûr

Render a généré automatiquement **`SAFQA_DATA_KEY`** : c'est la clé qui chiffre toutes les données de vos clients.

1. Service **safqa-cloud** → **Environment** → `SAFQA_DATA_KEY` → icône œil → copiez la valeur.
2. Enregistrez-la dans un gestionnaire de mots de passe (Bitwarden, 1Password…) **et** sur papier dans un coffre.
3. **Ne la modifiez jamais** : avec une autre clé, les données existantes deviennent illisibles.
   Ne l'envoyez jamais par e-mail ou WhatsApp.

## Étape 4 — Relier l'application au serveur

1. Sur GitHub : dépôt **BENQASSOU/20** → **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret** :
   - Nom : `SAFQA_CLOUD_URL`
   - Valeur : l'adresse de l'étape 2 (ex. `https://safqa-cloud-ab12.onrender.com`, sans `/` final).
2. Onglet **Actions** → **Build Android APK** → **Run workflow**. Après ~15 minutes, le nouvel APK est publié dans
   **Releases** : il est déjà configuré avec l'adresse de votre serveur.

> Les APK déjà installés peuvent aussi se connecter : *Plus › Compte & équipe › Modifier l'adresse du serveur*.

## Étape 5 — Créer votre compte administrateur

1. Dans l'application : **Plus › Compte & équipe › Créer un compte**, avec l'e-mail mis dans `SAFQA_ADMIN_EMAILS`.
2. Ouvrez `https://…onrender.com/admin` sur votre ordinateur et connectez-vous.
3. Le back-office vous demande d'activer la **double authentification** : installez *Google Authenticator* ou
   *Microsoft Authenticator*, ajoutez la clé affichée, tapez le code. C'est obligatoire pour le back-office.

✅ **C'est en ligne.** Vos clients peuvent créer leur compte depuis l'application.

---

## Au quotidien : le back-office (`/admin`)

| Situation | Que faire |
|---|---|
| Un client a payé son abonnement | **Entreprises** → **Formule** → choisir ESSENTIEL / PRO / ENTREPRISE et la date de fin. Effet immédiat sur tous ses appareils. *(Ou **Clés de licence** → générer une clé que le client saisit dans Plus › Abonnement.)* |
| Un client a oublié son mot de passe | Le propriétaire de son entreprise peut le réinitialiser depuis l'application (Équipe › ⋮). Sinon : **Utilisateurs** → **Mot de passe** → communiquez le mot de passe temporaire par téléphone. Il devra le changer. |
| Téléphone perdu ou volé | **Utilisateurs** → **Déconnecter** (coupe l'accès de tous ses appareils). Si besoin : **Retirer 2FA**. |
| Compte bloqué après des erreurs | **Utilisateurs** → **Déverrouiller** (sinon déblocage automatique après 15 min). |
| Client qui ne paie plus | **Entreprises** → **Formule** → FREE (lecture limitée), ou **Suspendre** (plus aucun accès). |
| Activité suspecte | **Journal de sécurité** : connexions, échecs, invitations, changements de rôle, exports, avec adresse IP. |
| Suivi de l'activité | **Tableau de bord** : utilisateurs actifs, entreprises par formule, revenu mensuel estimé, usage de l'IA. |

## Tenir la charge : 1 000 utilisateurs et plus

Test réalisé avant livraison (serveur 4 cœurs, PostgreSQL 16) :

| Scénario | Résultat |
|---|---|
| 1 000 inscriptions | 1 000 réussies, 0 erreur |
| 1 000 synchronisations **simultanées** | 1 000 réussies, 0 erreur (~155 req/s) |
| 1 000 lectures de compte simultanées | 1 000 réussies, 0 erreur |
| 300 connexions à la même seconde | 300 réussies, 0 erreur |

En pratique, 1 000 clients ne se connectent jamais tous à la même seconde : la synchronisation est légère et
l'application fonctionne hors-ligne. Quand l'activité augmente :

1. Render → **safqa-cloud** → **Settings** → passez au plan **Standard** (plus de mémoire/CPU), puis mettez
   `WEB_CONCURRENCY` à `4`.
2. Base de données : passez à un plan supérieur (1 Go+) dans **safqa-db** → **Settings**.
3. Gardez `WEB_CONCURRENCY × SAFQA_DB_POOL` (2 × 15 = 30 par défaut) en dessous de la limite de connexions de
   votre plan PostgreSQL.

## Sauvegardes

- **Base de données** : Render effectue des sauvegardes automatiques sur les plans payants (onglet *Recovery* de
  `safqa-db`). Vérifiez qu'elles sont actives.
- **Par entreprise** : le propriétaire peut exporter toutes ses données (format JSON) depuis l'application :
  *Plus › Compte & équipe › Exporter les données de l'entreprise*.
- **Sur chaque téléphone** : les données restent aussi en local (l'application fonctionne même si le serveur
  est arrêté), et *Plus › Paramètres › Sauvegarde* exporte un fichier complet.

## Option : héberger au Maroc (VPS) au lieu de Render

Si vos clients (ou la CNDP) exigent un hébergement au Maroc, confiez à un prestataire ces 4 commandes sur un
serveur Linux (Ubuntu) avec Docker :

```bash
git clone https://github.com/BENQASSOU/20.git && cd 20/deploy
cp .env.example .env && nano .env      # domaine, mots de passe : openssl rand -base64 48
docker compose up -d                    # base + serveur + HTTPS automatique + sauvegarde quotidienne
curl https://cloud.votre-domaine.ma/healthz
```

Les sauvegardes quotidiennes (30 jours) sont écrites dans `deploy/backups/` : copiez-les régulièrement ailleurs.

## Votre propre nom de domaine (facultatif)

Render → **safqa-cloud** → **Settings** → **Custom Domains** → ajoutez `cloud.votre-domaine.ma` et créez chez votre
registraire l'enregistrement DNS indiqué. Mettez ensuite à jour le secret GitHub `SAFQA_CLOUD_URL` et relancez le
build de l'APK.

## E-mails « mot de passe oublié » (facultatif)

Ajoutez dans Render → **Environment** : `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.
Sans e-mail configuré, la réinitialisation passe par le propriétaire de l'entreprise ou par vous (back-office).

## En cas de problème

| Symptôme | Cause probable | Solution |
|---|---|---|
| Le service ne démarre pas, log « Configuration incomplète » | variable manquante | Render → Environment : vérifier `DATABASE_URL`, `SAFQA_DATA_KEY` (32 caractères min.) |
| L'application affiche « Serveur injoignable » | adresse erronée ou service arrêté | ouvrir `…/healthz` ; vérifier l'adresse dans Compte & équipe |
| « L'IA n'est pas encore activée sur ce serveur » | `ANTHROPIC_API_KEY` vide | l'ajouter dans Render → Environment (redémarrage automatique) |
| « Quota IA mensuel atteint » | limite de la formule | changer de formule dans le back-office |
| « Serveur très sollicité » | pic de charge | voir *Tenir la charge* ci-dessus |
| Back-office : « double authentification obligatoire » | 2FA non activée | se reconnecter et suivre l'écran d'activation |
