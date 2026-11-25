# CloudVote — Service de reporting / clôture (Partie 4)

**Responsable :** Ayyoub Essafi
**Plateforme :** Render — Web Service (offre Free) · **Type de service cloud :** PaaS
**Technologies :** Python 3.13, FastAPI, Uvicorn, python-oracledb
**URL :** https://cloudvote-reporting.onrender.com

## Rôle dans l'architecture CloudVote

Ce service clôture automatiquement les scrutins et calcule les résultats.

- Il est **déclenché toutes les 30 minutes** par le Cloudflare Worker (Partie 5, FaaS), qui appelle `POST /internal/close`.
- Il **lit les bulletins** et **écrit les résultats** dans la base **Oracle Autonomous Database** (Partie 1, PaaS Oracle Cloud).
- Les votes eux-mêmes sont enregistrés par l'API backend (Partie 2, VM Oracle).

```text
Cloudflare Worker (FaaS) --HTTPS + secret--> Render (ce service, PaaS) --mTLS--> Oracle Autonomous DB (PaaS)
```

L'architecture fait ainsi collaborer trois fournisseurs : Cloudflare, Render et Oracle Cloud.

## Routes

| Méthode | Route | Accès | Réponse |
|---|---|---|---|
| GET | `/health` | public | `{"status":"ok"}` — vérification de l'état du service (utilisée par Render toutes les 5 s) |
| POST | `/internal/close` | en-tête `Authorization: Bearer <CLOSE_SECRET>` | `{"closed_positions": n, "closed_elections": m}` ; `401` sans le bon secret |

## Fonctionnement de la clôture

À chaque appel de `/internal/close` :

1. Vérification du secret (comparaison à temps constant, `hmac.compare_digest`).
2. Sélection et verrouillage des postes `OPEN` d'une élection `PUBLISHED` dont la date de clôture (`postes.date_cloture`, sinon `elections.date_cloture`) est passée — `FOR UPDATE SKIP LOCKED`.
3. Pour chaque poste : comptage des bulletins par candidat (table `bulletins`), calcul du pourcentage et détection des égalités.
4. Écriture dans la table `resultats` (`total_votes`, `pourcentage`, `est_egalite`), puis passage du poste à `CLOSED`.
5. Passage de l'élection à `CLOSED` lorsque tous ses postes sont fermés.
6. Validation de l'ensemble en **une seule transaction** (rollback en cas d'erreur).

**Idempotence :** un poste traité passe à `CLOSED` dans la même transaction que l'écriture de ses résultats ; un nouvel appel ne le sélectionne plus et ne compte donc jamais deux fois les mêmes voix.

## Configuration (variables d'environnement Render)

| Variable | Rôle |
|---|---|
| `DB_USER`, `DB_PASSWORD` | compte applicatif de la base (`CLOUDVOTE`) |
| `DB_DSN` | service Oracle (`cloudvote_tp`) |
| `WALLET_DIR` | dossier du wallet : `/etc/secrets` (Secret Files de Render) |
| `WALLET_PASSWORD` | mot de passe du wallet Oracle |
| `CLOSE_SECRET` | secret partagé avec le Cloudflare Worker |
| `PYTHON_VERSION` | `3.13.2` |

**Secret Files Render :** `tnsnames.ora` et `ewallet.pem` (wallet Oracle, connexion mTLS).
Aucun secret n'est stocké dans le dépôt Git.

## Déploiement sur Render

| Paramètre | Valeur |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` |
| Instance | Free (0,1 CPU, 512 Mo) — mise en veille après inactivité |

## Fichiers

| Fichier | Contenu |
|---|---|
| `main.py` | le service FastAPI |
| `requirements.txt` | dépendances (fastapi, uvicorn, oracledb) |
| `scenario.py` | scénario de démonstration : `creer`, `verifier`, `nettoyer` une élection de test |
| `test_sans_bd.py` | test de la logique de clôture sans base (base simulée en mémoire) |
| `inspecter_schema.py` | vérification de la connexion et lecture du schéma de la base |
| `sql/` | scripts SQL équivalents au scénario (création, vérification, nettoyage) |

## Exécution locale

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# définir DB_USER, DB_PASSWORD, DB_DSN, WALLET_DIR, WALLET_PASSWORD, CLOSE_SECRET
uvicorn main:app --port 8001
```

## Scénario de démonstration

```powershell
python scenario.py creer      # élection de test : 3 postes, clôture dans 2 minutes
# après 2 minutes :
curl.exe -X POST https://cloudvote-reporting.onrender.com/internal/close -H "Authorization: Bearer <CLOSE_SECRET>"
python scenario.py verifier   # statuts CLOSED + résultats
python scenario.py nettoyer
```

Résultats attendus : `{"closed_positions":3,"closed_elections":1}` ; President : A 2 voix (66,67 %), B 1 (33,33 %) ; Vice-president : C et D 1 voix chacun (50 %, égalité) ; Treasurer : E 0 voix. Un second appel renvoie `{"closed_positions":0,"closed_elections":0}`.

## Tests réalisés

| Test | Résultat |
|---|---|
| `/health` | 200 `{"status":"ok"}` |
| `/internal/close` sans secret | 401 |
| Clôture avant la date de fin | aucun poste fermé |
| Clôture après la date de fin | 3 postes et 1 élection fermés |
| Gagnant / égalité / aucun vote | résultats corrects |
| Second appel (idempotence) | 0 poste fermé, résultats inchangés |
