import hmac, logging, os
import oracledb
from fastapi import FastAPI, Header, HTTPException

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("closing")

CLOSE_SECRET = os.environ["CLOSE_SECRET"]
WALLET_DIR = os.environ.get("WALLET_DIR", "/etc/secrets")   # dossier des Secret Files de Render

def _init_session(conn, requested_tag):
    conn.cursor().execute("ALTER SESSION SET TIME_ZONE = 'UTC'")

pool = oracledb.create_pool(
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    dsn=os.environ["DB_DSN"],
    config_dir=WALLET_DIR,
    wallet_location=WALLET_DIR,
    wallet_password=os.environ["WALLET_PASSWORD"],
    min=1, max=2, increment=1,
    session_callback=_init_session,
)

app = FastAPI(title="CloudVote reporting")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/internal/close")
def close_due_positions(authorization: str = Header(default="")):
    # Comparaison à temps constant pour que le secret ne puisse pas être deviné par le temps de réponse
    if not hmac.compare_digest(authorization.encode(), f"Bearer {CLOSE_SECRET}".encode()):
        raise HTTPException(401, "Unauthorized")

    closed_positions = 0
    with pool.acquire() as conn:
        cur = conn.cursor()
        try:
            # 1) Verrouiller chaque poste OPEN dont l'heure de fin est atteinte.
            #    SKIP LOCKED : un appel parallèle, ou un vote encore en cours, est sauté
            #    et traité au passage suivant, jamais compté deux fois.
            cur.execute("""
                SELECT p.id_poste, p.id_election
                FROM postes p
                JOIN elections e ON e.id_election = p.id_election
                WHERE p.statut = 'OPEN' AND e.statut = 'PUBLISHED'
                  AND NVL(p.date_cloture, e.date_cloture) <= SYSTIMESTAMP
                FOR UPDATE OF p.statut SKIP LOCKED""")
            due = cur.fetchall()

            for position_id, election_id in due:
                # 2) Compter les bulletins par candidat (candidats à 0 voix inclus)
                cur.execute("""
                    SELECT c.id_candidat, COUNT(b.id_bulletin)
                    FROM candidats c
                    LEFT JOIN bulletins b
                      ON b.id_poste = c.id_poste AND b.id_candidat = c.id_candidat
                    WHERE c.id_poste = :p
                    GROUP BY c.id_candidat""", p=position_id)
                counts = cur.fetchall()
                total_votes = sum(n for _, n in counts)
                top = max((n for _, n in counts), default=0)
                n_top = sum(1 for _, n in counts if n == top)
                data = []
                for candidate_id, n in counts:
                    pct = round(100 * n / total_votes, 2) if total_votes else 0
                    is_tie = 1 if top > 0 and n == top and n_top > 1 else 0
                    data.append((election_id, position_id, candidate_id, n, pct, is_tie))

                # 3) Écrire dans la table resultats (supprimer d'abord = sûr même si un
                #    passage précédent a planté en cours de route)
                cur.execute("DELETE FROM resultats WHERE id_poste = :p", p=position_id)
                if data:
                    cur.executemany("""
                        INSERT INTO resultats (id_election, id_poste, id_candidat,
                                               total_votes, pourcentage, est_egalite)
                        VALUES (:1, :2, :3, :4, :5, :6)""", data)

                # 4) Marquer le poste comme fermé
                cur.execute("UPDATE postes SET statut = 'CLOSED' WHERE id_poste = :p",
                            p=position_id)
                closed_positions += 1

            # 5) Une élection est fermée quand sa date de fin est atteinte et
            #    qu'aucun de ses postes n'est encore ouvert
            cur.execute("""
                UPDATE elections e SET statut = 'CLOSED'
                WHERE e.statut = 'PUBLISHED' AND e.date_cloture <= SYSTIMESTAMP
                  AND NOT EXISTS (SELECT 1 FROM postes p
                                  WHERE p.id_election = e.id_election AND p.statut = 'OPEN')""")
            closed_elections = cur.rowcount

            conn.commit()      # tout ce qui précède devient visible d'un seul coup
        except Exception:
            conn.rollback()    # rien n'est écrit à moitié
            log.exception("Closing failed")
            raise HTTPException(500, "Closing failed")

    log.info("Closing run: %s positions, %s elections closed", closed_positions, closed_elections)
    return {"closed_positions": closed_positions, "closed_elections": closed_elections}
