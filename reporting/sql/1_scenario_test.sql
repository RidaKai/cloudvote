-- ============================================================
-- Partie 4 — Scénario de test de la clôture (schéma en français).
-- À exécuter dans Database Actions → SQL avec le bouton « Run Script ».
-- Si vous êtes connecté en ADMIN, exécutez d'abord :
--   ALTER SESSION SET CURRENT_SCHEMA = CLOUDVOTE;
--
-- Crée une élection PUBLISHED qui se termine dans 2 minutes, avec 3 postes :
--   President      : A = 2 voix, B = 1 voix   → A gagne, pas d'égalité
--   Vice-president : C = 1 voix, D = 1 voix   → égalité (est_egalite = 1 pour C et D)
--   Treasurer      : E = 0 voix               → cas « aucun vote »
-- Les bulletins sont insérés directement (pas besoin de la partie 2 pour ce test).
-- ============================================================
SET SERVEROUTPUT ON
DECLARE
  v_e  NUMBER;  v_p1 NUMBER;  v_p2 NUMBER;  v_p3 NUMBER;
  v_a  NUMBER;  v_b  NUMBER;  v_c  NUMBER;  v_d  NUMBER;  v_x NUMBER;
BEGIN
  INSERT INTO elections (titre, date_ouverture, date_cloture, statut)
  VALUES ('TEST cloture Partie 4', SYSTIMESTAMP - INTERVAL '1' HOUR,
          SYSTIMESTAMP + INTERVAL '2' MINUTE, 'PUBLISHED')
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
  -- Treasurer : aucun bulletin

  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Election de test creee : id_election = ' || v_e);
END;
/
