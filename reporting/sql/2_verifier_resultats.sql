-- Partie 4 — Vérifier l'effet de /internal/close sur l'élection de test.
-- (En ADMIN : ALTER SESSION SET CURRENT_SCHEMA = CLOUDVOTE; d'abord)

-- 1) Statuts : avant la clôture PUBLISHED / OPEN, après : CLOSED / CLOSED
SELECT e.id_election, e.statut AS statut_election, p.nom AS poste, p.statut AS statut_poste,
       SYS_EXTRACT_UTC(e.date_cloture) AS fin_utc
FROM elections e JOIN postes p ON p.id_election = e.id_election
WHERE e.titre = 'TEST cloture Partie 4'
ORDER BY e.id_election, p.id_poste;

-- 2) Résultats écrits par le service
--    Attendu : A 2 (66.67 %), B 1 (33.33 %) ; C 1 (50 %, égalité), D 1 (50 %, égalité) ; E 0 (0 %)
SELECT p.nom AS poste, c.nom_complet AS candidat, r.total_votes, r.pourcentage, r.est_egalite
FROM resultats r
JOIN postes    p ON p.id_poste    = r.id_poste
JOIN candidats c ON c.id_candidat = r.id_candidat
JOIN elections e ON e.id_election = r.id_election
WHERE e.titre = 'TEST cloture Partie 4'
ORDER BY p.id_poste, r.total_votes DESC;
