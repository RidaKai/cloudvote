"""
Partie 4 - Scénario de test de la clôture, sans passer par Database Actions.
Utilise la même connexion que le service (variables DB_USER, DB_PASSWORD,
DB_DSN, WALLET_DIR, WALLET_PASSWORD).

    python scenario.py creer       # crée l'élection de test (se termine dans 2 min)
    python scenario.py verifier    # affiche statuts + résultats de l'élection de test
    python scenario.py nettoyer    # supprime toutes les données de l'élection de test

Élection de test « TEST cloture Partie 4 » :
    President      : A = 2 voix, B = 1 voix   -> A gagne
    Vice-president : C = 1 voix, D = 1 voix   -> égalité (est_egalite = 1)
    Treasurer      : E = 0 voix               -> aucun vote
"""
import os
import sys
import oracledb

TITRE = "TEST cloture Partie 4"


def connect():
    wallet = os.environ["WALLET_DIR"]
    conn = oracledb.connect(
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        dsn=os.environ["DB_DSN"], config_dir=wallet, wallet_location=wallet,
        wallet_password=os.environ["WALLET_PASSWORD"])
    conn.cursor().execute("ALTER SESSION SET TIME_ZONE = 'UTC'")
    return conn


def creer(conn, minutes=2):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM elections WHERE titre = :t", t=TITRE)
    if cur.fetchone()[0]:
        sys.exit("Une élection de test existe déjà : lance d'abord  python scenario.py nettoyer")
    new_id = cur.var(int)
    cur.execute("""
    DECLARE
      v_e  NUMBER;  v_p1 NUMBER;  v_p2 NUMBER;  v_p3 NUMBER;
      v_a  NUMBER;  v_b  NUMBER;  v_c  NUMBER;  v_d  NUMBER;  v_x NUMBER;
    BEGIN
      INSERT INTO elections (titre, date_ouverture, date_cloture, statut)
      VALUES (:titre, SYSTIMESTAMP - INTERVAL '1' HOUR,
              SYSTIMESTAMP + NUMTODSINTERVAL(:minutes, 'MINUTE'), 'PUBLISHED')
      RETURNING id_election INTO v_e;

      INSERT INTO postes (id_election, nom) VALUES (v_e, 'President')      RETURNING id_poste INTO v_p1;
      INSERT INTO postes (id_election, nom) VALUES (v_e, 'Vice-president') RETURNING id_poste INTO v_p2;
      INSERT INTO postes (id_election, nom) VALUES (v_e, 'Treasurer')      RETURNING id_poste INTO v_p3;

      INSERT INTO candidats (id_poste, nom_complet) VALUES (v_p1, 'Candidat A') RETURNING id_candidat INTO v_a;
      INSERT INTO candidats (id_poste, nom_complet) VALUES (v_p1, 'Candidat B') RETURNING id_candidat INTO v_b;
      INSERT INTO candidats (id_poste, nom_complet) VALUES (v_p2, 'Candidat C') RETURNING id_candidat INTO v_c;
      INSERT INTO candidats (id_poste, nom_complet) VALUES (v_p2, 'Candidat D') RETURNING id_candidat INTO v_d;
      INSERT INTO candidats (id_poste, nom_complet) VALUES (v_p3, 'Candidat E') RETURNING id_candidat INTO v_x;

      INSERT INTO bulletins (id_election, id_poste, id_candidat) VALUES (v_e, v_p1, v_a);
      INSERT INTO bulletins (id_election, id_poste, id_candidat) VALUES (v_e, v_p1, v_a);
      INSERT INTO bulletins (id_election, id_poste, id_candidat) VALUES (v_e, v_p1, v_b);
      INSERT INTO bulletins (id_election, id_poste, id_candidat) VALUES (v_e, v_p2, v_c);
      INSERT INTO bulletins (id_election, id_poste, id_candidat) VALUES (v_e, v_p2, v_d);

      :new_id := v_e;
    END;""", titre=TITRE, minutes=minutes, new_id=new_id)
    conn.commit()
    print(f"Élection de test créée : id_election = {new_id.getvalue()}, "
          f"elle se termine dans {minutes} minute(s).")


def verifier(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT e.id_election, e.statut, p.nom, p.statut,
               TO_CHAR(SYS_EXTRACT_UTC(e.date_cloture), 'YYYY-MM-DD HH24:MI:SS'),
               TO_CHAR(SYS_EXTRACT_UTC(SYSTIMESTAMP), 'YYYY-MM-DD HH24:MI:SS')
        FROM elections e JOIN postes p ON p.id_election = e.id_election
        WHERE e.titre = :t ORDER BY p.id_poste""", t=TITRE)
    rows = cur.fetchall()
    if not rows:
        print("Aucune élection de test. Lance  python scenario.py creer")
        return
    print(f"Élection {rows[0][0]} : statut = {rows[0][1]}   "
          f"(fin : {rows[0][4]} UTC, maintenant : {rows[0][5]} UTC)")
    for _, _, poste, statut_poste, _, _ in rows:
        print(f"   poste {poste:<15} statut = {statut_poste}")

    cur.execute("""
        SELECT p.nom, c.nom_complet, r.total_votes, r.pourcentage, r.est_egalite
        FROM resultats r
        JOIN postes p ON p.id_poste = r.id_poste
        JOIN candidats c ON c.id_candidat = r.id_candidat
        JOIN elections e ON e.id_election = r.id_election
        WHERE e.titre = :t ORDER BY p.id_poste, r.total_votes DESC""", t=TITRE)
    res = cur.fetchall()
    print("\nRésultats :" if res else "\nRésultats : aucun pour l'instant (pas encore clôturée)")
    if res:
        print(f"   {'poste':<15} {'candidat':<12} {'votes':>5} {'%':>7}  égalité")
        for poste, cand, total, pct, tie in res:
            print(f"   {poste:<15} {cand:<12} {total:>5} {float(pct):>7.2f}  {'OUI' if tie else 'non'}")


def nettoyer(conn):
    cur = conn.cursor()
    sub = "(SELECT id_election FROM elections WHERE titre = :t)"
    for table in ("resultats", "bulletins", "participations"):
        cur.execute(f"DELETE FROM {table} WHERE id_election IN {sub}", t=TITRE)
    cur.execute(f"""DELETE FROM candidats WHERE id_poste IN
                    (SELECT id_poste FROM postes WHERE id_election IN {sub})""", t=TITRE)
    cur.execute(f"DELETE FROM postes WHERE id_election IN {sub}", t=TITRE)
    cur.execute("DELETE FROM elections WHERE titre = :t", t=TITRE)
    n = cur.rowcount
    conn.commit()
    print(f"Nettoyage terminé ({n} élection(s) de test supprimée(s)).")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    actions = {"creer": creer, "verifier": verifier, "nettoyer": nettoyer}
    if action not in actions:
        sys.exit(__doc__)
    with connect() as c:
        actions[action](c)
