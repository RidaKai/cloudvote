<div class="cover">
<h1 class="title">Partie 4 — Service de reporting / clôture (Render)</h1>
<p class="meta">Guide pas à pas · CloudVote · FastAPI sur Render Web Service Free (PaaS)</p>
</div>

# Ce que fait ma partie, en 4 phrases

> **Schéma en français.** La base de CloudVote utilise des noms français : `postes`, `candidats`, `bulletins`, `resultats` (colonnes `total_votes`, `pourcentage`, `est_egalite`), `id_poste`, `statut`, `date_cloture`… Les valeurs de statut restent en anglais (`PUBLISHED`, `OPEN`, `CLOSED`). `main.py` et les scripts SQL de ce dossier sont déjà adaptés.


Ton service est une petite API FastAPI hébergée sur **Render**, séparée de l'API de vote. Elle n'a que deux routes : `GET /health` (pour vérifier qu'il est vivant et le réveiller) et `POST /internal/close`, protégée par un secret. Toutes les 30 minutes, le Worker Cloudflare de Taha (partie 5) appelle `/internal/close` : ton code trouve les postes dont la date de fin est passée, compte les bulletins, écrit la table `resultats` et passe les postes (puis l'élection) à `CLOSED` (colonne `statut`), **dans une seule transaction**. Si on l'appelle deux fois, rien n'est compté deux fois (c'est l'**idempotence**).

| Tu reçois de… | Quoi | Tu donnes à… | Quoi |
|---|---|---|---|
| Partie 1 (BD) | mot de passe `CLOUDVOTE`, `tnsnames.ora`, `ewallet.pem`, mot de passe du wallet | Partie 5 (Taha) | l'URL Render, ex. `https://cloudvote-reporting.onrender.com` |
| Groupe (jour 0) | `CLOSE_SECRET` (le même que Taha) | | |

**Contenu de ce dossier :**

```text
reporting/
  main.py                     # le service (identique au guide du groupe, commentaires en français)
  requirements.txt            # fastapi, uvicorn[standard], oracledb
  test_sans_bd.py             # teste la logique sans base Oracle (fausse base en mémoire)
  sql/1_scenario_test.sql     # crée une élection de test (gagnant, égalité, aucun vote)
  sql/2_verifier_resultats.sql
  sql/3_nettoyage.sql
  README.md                   # ce guide
```

# Étape 1 — Préparer ton PC

1. Installer **Python 3.11 ou plus** (sur Windows, cocher « Add Python to PATH ») et **Git**.
2. Récupérer le dépôt du groupe et créer ta branche :

```bash
git clone https://github.com/<org>/cloudvote.git
cd cloudvote
git checkout -b partie4-reporting
```

3. Copier les fichiers de ce dossier dans `cloudvote/reporting/`.
4. Vérifier que le `.gitignore` à la racine contient au moins : `.env`, `wallet/`, `.venv/`, `__pycache__/`.

# Étape 2 — Installer et tester sans base de données (faisable tout de suite)

Tu n'as pas besoin d'attendre la partie 1 pour vérifier que ta logique marche.

**Windows (PowerShell)** :

```powershell
cd reporting
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt httpx
python test_sans_bd.py
```

**Linux / macOS** :

```bash
cd reporting
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt httpx
python test_sans_bd.py
```

Résultat attendu (à la fin) :

```text
1er appel : 200 {'closed_positions': 3, 'closed_elections': 0}
   (10, 1, 101) (2, 66.67, 0)      <- poste 1 : gagnant à 2 voix
   (10, 1, 102) (1, 33.33, 0)
   (10, 2, 201) (1, 50.0, 1)       <- poste 2 : égalité → is_tie = 1
   (10, 2, 202) (1, 50.0, 1)
   (10, 3, 301) (0, 0, 0)          <- poste 3 : aucun vote → 0, 0 %
2e appel  : {'closed_positions': 0, 'closed_elections': 0}   <- idempotent
OK
```

Ce test vérifie aussi que `/health` répond et que `/internal/close` renvoie **401** sans secret ou avec un mauvais secret. (L'élection n'est pas fermée ici, car le test contient un 4<sup>e</sup> poste dont la date n'est pas encore atteinte : c'est voulu.)

> Si l'activation de l'environnement est bloquée sous PowerShell : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis réessayer.

# Étape 3 — Récupérer les accès à la base (de la partie 1)

Demande en privé (jamais dans Git) :

- le mot de passe de l'utilisateur `CLOUDVOTE` ;
- les fichiers `tnsnames.ora` et `ewallet.pem` (tirés de `Wallet_cloudvote.zip`) ;
- le mot de passe du wallet ;
- et au groupe, le `CLOSE_SECRET` (généré le jour 0 avec `python -c "import secrets; print(secrets.token_urlsafe(48))"`).

Mets les deux fichiers du wallet dans un dossier **hors du dépôt**, par exemple `C:\cloudvote\wallet\` ou `~/cloudvote-wallet/`.

# Étape 4 — Lancer le service en local avec la vraie base

**Windows (PowerShell)** — dans `reporting`, environnement activé :

```powershell
$env:DB_USER="CLOUDVOTE"
$env:DB_PASSWORD="<mot de passe CLOUDVOTE>"
$env:DB_DSN="cloudvote_tp"
$env:WALLET_DIR="C:\cloudvote\wallet"
$env:WALLET_PASSWORD="<mot de passe du wallet>"
$env:CLOSE_SECRET="dev-secret"
uvicorn main:app --port 8001
```

**Linux / macOS** :

```bash
export DB_USER=CLOUDVOTE DB_PASSWORD='...' DB_DSN=cloudvote_tp \
       WALLET_DIR=~/cloudvote-wallet WALLET_PASSWORD='...' CLOSE_SECRET=dev-secret
uvicorn main:app --port 8001
```

Dans un **deuxième terminal** (sous Windows, écrire bien `curl.exe`, pas `curl`) :

```bash
curl.exe http://localhost:8001/health
#  {"status":"ok"}
curl.exe -X POST http://localhost:8001/internal/close
#  {"detail":"Unauthorized"}   (401)
curl.exe -X POST http://localhost:8001/internal/close -H "Authorization: Bearer dev-secret"
#  {"closed_positions":0,"closed_elections":0}   (200 : la connexion à la BD marche)
```

Si la 3<sup>e</sup> commande renvoie 500, regarde le premier terminal : l'erreur Oracle y est affichée (voir « Dépannage » à la fin).

# Étape 5 — Le scénario de clôture complet

1. Ouvrir **Database Actions → SQL**. Par défaut, seul `ADMIN` peut s'y connecter. Deux possibilités :
   - demander à la partie 1 d'activer l'accès web de `CLOUDVOTE` (en ADMIN : *Database Actions → Database Users → CLOUDVOTE → Edit → cocher Web Access*), puis se connecter en `CLOUDVOTE` ;
   - ou se connecter en `ADMIN` et exécuter d'abord `ALTER SESSION SET CURRENT_SCHEMA = CLOUDVOTE;` pour que les scripts travaillent sur les tables de `CLOUDVOTE`.

   Ouvrir ensuite `sql/1_scenario_test.sql` et cliquer **Run Script**. Il crée l'élection « TEST cloture Partie 4 », qui se termine **dans 2 minutes**.
2. Appeler tout de suite la clôture :
   `curl.exe -X POST http://localhost:8001/internal/close -H "Authorization: Bearer dev-secret"`
   → `closed_positions: 0` (la date n'est pas encore atteinte : rien n'est fermé trop tôt).
3. **Attendre 2 minutes**, puis rappeler la même commande
   → `{"closed_positions":3,"closed_elections":1}`.
   (Si d'autres élections de test de la partie 1 sont déjà échues, les nombres peuvent être plus grands.)
4. Exécuter `sql/2_verifier_resultats.sql`. Attendu :

   | Poste | Candidat | total_votes | pourcentage | est_egalite |
   |---|---|---|---|---|
   | President | Candidat A | 2 | 66.67 | 0 |
   | President | Candidat B | 1 | 33.33 | 0 |
   | Vice-president | Candidat C | 1 | 50 | 1 |
   | Vice-president | Candidat D | 1 | 50 | 1 |
   | Treasurer | Candidat E | 0 | 0 | 0 |

   et les statuts de l'élection et des postes à `CLOSED`.
5. Rappeler une 3<sup>e</sup> fois → `closed_positions: 0`, et `2_verifier_resultats.sql` donne exactement les mêmes lignes (**pas de double comptage**).
6. **Faire des captures d'écran** de chaque étape (terminal + résultats SQL) : elles servent pour `docs/tests.md` (tests T9 à T13) et pour la soutenance.
7. Pour recommencer : `sql/3_nettoyage.sql`, puis retour au point 1.

# Étape 6 — Tester avec le Worker de Taha (en local)

Laisse ton service tourner sur le port 8001. Taha met dans son `.dev.vars` :

```text
RENDER_URL=http://localhost:8001
CLOSE_SECRET=dev-secret
```

puis lance `npx wrangler dev --test-scheduled` et déclenche le cron à la main. Son terminal doit afficher `close ok (attempt 1): {...}`, et ton terminal une ligne `Closing run: ...`. Si vous n'êtes pas sur le même PC, faites-le sur un seul PC (le plus simple).

# Étape 7 — Commit et pull request

```bash
git add reporting/
git status            # vérifier qu'AUCUN fichier wallet, .env ou .venv n'apparaît
git commit -m "Partie 4 : service de clôture FastAPI pour Render"
git push -u origin partie4-reporting
```

Puis ouvrir une *pull request* sur GitHub vers `main`. Render déploiera depuis `main`, donc la PR doit être fusionnée avant l'étape 8 (ou choisis ta branche dans Render pour un premier essai).

# Étape 8 — Déployer sur Render

1. Aller sur **render.com** → *Sign in with GitHub* → autoriser l'accès au dépôt `cloudvote`.
2. **New → Web Service** → choisir le dépôt `cloudvote`.
3. Remplir :

   | Champ | Valeur |
   |---|---|
   | Name | `cloudvote-reporting` |
   | Branch | `main` |
   | Root Directory | `reporting` |
   | Runtime / Language | Python 3 |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
   | Instance Type | **Free** |

4. **Environment Variables** :

   | Clé | Valeur |
   |---|---|
   | `DB_USER` | `CLOUDVOTE` |
   | `DB_PASSWORD` | mot de passe de CLOUDVOTE |
   | `DB_DSN` | `cloudvote_tp` |
   | `WALLET_DIR` | `/etc/secrets` |
   | `WALLET_PASSWORD` | mot de passe du wallet |
   | `CLOSE_SECRET` | la longue valeur du groupe (**pas** `dev-secret`) |

5. **Secret Files** : ajouter deux fichiers. Nom `tnsnames.ora` → coller le contenu du fichier. Nom `ewallet.pem` → coller tout le contenu (de `-----BEGIN` jusqu'à la dernière ligne `-----END ...-----`). Render les place dans `/etc/secrets/`.
6. **Health Check Path** (dans *Advanced*) : `/health`.
7. **Create Web Service**. Suivre l'onglet *Logs* jusqu'à voir `Uvicorn running on http://0.0.0.0:...` puis « Your service is live ».

# Étape 9 — Tester en ligne et transmettre l'URL

```bash
curl.exe https://cloudvote-reporting.onrender.com/health
#  {"status":"ok"}   (la 1re fois peut prendre ~1 min : réveil du service gratuit)
curl.exe -X POST https://cloudvote-reporting.onrender.com/internal/close
#  401
curl.exe -X POST https://cloudvote-reporting.onrender.com/internal/close -H "Authorization: Bearer <CLOSE_SECRET>"
#  200 {"closed_positions":...,"closed_elections":...}
```

Refaire le scénario de l'étape 5 contre l'URL Render. Puis **donner l'URL à Taha** (sa variable `RENDER_URL`) et vérifier que vous avez **exactement le même** `CLOSE_SECRET`. Quand son Worker est déployé, l'onglet *Logs* de Render doit montrer une ligne `Closing run: ...` à chaque :00 et :30.

# Étape 10 — Ta liste « Terminé quand »

- [ ] `GET https://<render-url>/health` renvoie ok
- [ ] `/internal/close` sans l'en-tête → 401 ; avec le bon en-tête → 200
- [ ] Scénario de clôture OK, le second appel ne compte rien
- [ ] Cas « égalité » et « aucun vote » corrects dans `resultats`
- [ ] Les logs Render montrent une ligne par passage, et aucune donnée d'électeur

# Ce que tu dois savoir expliquer à la soutenance

**Pourquoi un service séparé sur Render ?** Le calcul des résultats est un traitement par lots : on l'isole de l'API de vote (VM 2) pour ne pas la ralentir, et c'est le 2<sup>e</sup> PaaS de l'architecture, chez un autre fournisseur qu'Oracle.

**Comment il est protégé ?** Par un secret partagé dans l'en-tête `Authorization: Bearer <CLOSE_SECRET>`, comparé avec `hmac.compare_digest` (comparaison à temps constant, pour qu'on ne puisse pas deviner le secret en mesurant le temps de réponse). Sans le secret : 401. Le secret est dans les variables d'environnement de Render, jamais dans Git.

**Comment il se connecte à la base ?** Avec `python-oracledb` en mode *thin*, en mTLS grâce au wallet (`tnsnames.ora` + `ewallet.pem`) placé dans les *Secret Files* de Render. Render n'a pas d'IP fixe, c'est pour ça qu'on utilise le mTLS plutôt qu'une liste d'IP autorisées.

**Pourquoi c'est idempotent (pas de double comptage) ?**

1. On ne sélectionne que les postes encore `OPEN` dont la date de fin est passée ; la **même transaction** qui écrit les résultats les passe à `CLOSED`, donc l'appel suivant ne les voit plus.
2. `FOR UPDATE ... SKIP LOCKED` : si deux appels arrivent en même temps, le second saute les lignes que le premier a verrouillées. Et si un étudiant est en train de voter sur ce poste (l'API de la VM 2 verrouille aussi la ligne du poste), le poste est sauté et traité au passage suivant.
3. En cas d'erreur, `rollback` : rien n'est écrit à moitié, le passage suivant refait tout. Le `DELETE` avant l'`INSERT` dans `resultats` rend aussi l'écriture sûre.

**Égalités et absence de votes ?** Tous les candidats ex æquo au score maximal ont `est_egalite = 1` (le règlement décide ensuite). Si personne n'a voté, chaque candidat a 0 et 0 %, sans division par zéro.

**Et si Render dort ?** Le service gratuit s'endort après ~15 min ; le Worker de Taha attend jusqu'à 70 s et réessaie 3 fois. Ce retard ne permet **aucun** vote tardif : l'API de la VM 2 vérifie la date de fin avec l'horloge de la base à chaque vote. Il retarde seulement la publication des résultats.

**Pourquoi des `def` et pas `async def` ?** Le pilote Oracle est bloquant ; FastAPI exécute les fonctions `def` dans un pool de threads, ce qui évite de bloquer le serveur.

# Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `KeyError: 'CLOSE_SECRET'` (ou `DB_USER`…) au démarrage | variable d'environnement manquante | la définir (étape 4 en local, étape 8 sur Render) |
| `DPY-6005` / connexion impossible | mauvais `WALLET_DIR`, fichier wallet manquant, mauvais mot de passe du wallet, ou base arrêtée | vérifier que le dossier contient `tnsnames.ora` **et** `ewallet.pem` ; redémarrer la base dans la console OCI (elle s'arrête après 7 jours sans activité) |
| Erreur `DPY-…` disant que `tnsnames.ora` ou `cloudvote_tp` est introuvable | `tnsnames.ora` absent du dossier `WALLET_DIR` | remettre le fichier, vérifier le nom exact du service dans `tnsnames.ora` |
| `ORA-01017` | mauvais utilisateur ou mot de passe | vérifier `DB_USER` / `DB_PASSWORD` avec la partie 1 |
| `ORA-00942` table or view does not exist | les tables ont été créées sous un autre utilisateur (ex. ADMIN), ou tu exécutes les scripts SQL en ADMIN sans changer de schéma | demander à la partie 1 de créer le schéma en tant que `CLOUDVOTE` ; en ADMIN, lancer d'abord `ALTER SESSION SET CURRENT_SCHEMA = CLOUDVOTE;` |
| Impossible de se connecter à Database Actions en `CLOUDVOTE` | l'accès web n'est activé que pour ADMIN par défaut | voir l'étape 5, point 1 |
| 401 alors que le secret est bon | espace ou retour à la ligne copié dans la variable, ou valeurs différentes Render / Worker | recopier la valeur proprement des deux côtés |
| Le build Render échoue sur la version de Python | version par défaut de Render trop récente pour un paquet | ajouter la variable d'environnement `PYTHON_VERSION=3.12.8` puis redéployer |
| `closed_positions` reste à 0 | élection encore `DRAFT`, ou date de fin pas atteinte (dates en UTC !) | publier l'élection ; vérifier `SYS_EXTRACT_UTC(closes_at)` avec `sql/2_verifier_resultats.sql` |
| `curl` sous PowerShell affiche une erreur étrange | `curl` est un alias de `Invoke-WebRequest` | utiliser `curl.exe` |
