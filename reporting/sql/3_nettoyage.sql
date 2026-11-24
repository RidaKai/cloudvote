-- Partie 4 — Supprimer les données de l'élection de test (enfants d'abord).
-- (En ADMIN : ALTER SESSION SET CURRENT_SCHEMA = CLOUDVOTE; d'abord)
DELETE FROM resultats      WHERE id_election IN (SELECT id_election FROM elections WHERE titre = 'TEST cloture Partie 4');
DELETE FROM bulletins      WHERE id_election IN (SELECT id_election FROM elections WHERE titre = 'TEST cloture Partie 4');
DELETE FROM participations WHERE id_election IN (SELECT id_election FROM elections WHERE titre = 'TEST cloture Partie 4');
DELETE FROM candidats WHERE id_poste IN (SELECT p.id_poste FROM postes p JOIN elections e ON e.id_election = p.id_election
                                         WHERE e.titre = 'TEST cloture Partie 4');
DELETE FROM postes         WHERE id_election IN (SELECT id_election FROM elections WHERE titre = 'TEST cloture Partie 4');
DELETE FROM elections      WHERE titre = 'TEST cloture Partie 4';
COMMIT;
