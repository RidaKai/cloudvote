# Test de la logique de clôture SANS base Oracle (fausse base en mémoire).
# Lancer :  pip install fastapi httpx oracledb   puis   python test_sans_bd.py
import os, sys, types
os.environ.update(CLOSE_SECRET="s3cret", DB_USER="u", DB_PASSWORD="p", DB_DSN="d", WALLET_PASSWORD="w")
import oracledb

# --- fausse base en mémoire ---
DB = {"positions": {1: ["OPEN", 10, True], 2: ["OPEN", 10, True], 3: ["OPEN", 10, True], 4: ["OPEN", 10, False]},
      "elections": {10: "PUBLISHED"},
      "cands": {1: [101, 102], 2: [201, 202], 3: [301], 4: [401]},
      "ballots": [(1, 101), (1, 101), (1, 102), (2, 201), (2, 202)],
      "results": {}}
class Cur:
    rowcount = 0
    def execute(self, sql, **kw):
        s = " ".join(sql.split())
        if s.startswith("SELECT p.id_poste, p.id_election"):
            self._r = [(pid, v[1]) for pid, v in DB["positions"].items() if v[0] == "OPEN" and v[2]]
        elif s.startswith("SELECT c.id_candidat, COUNT"):
            p = kw["p"]; self._r = [(c, sum(1 for b in DB["ballots"] if b == (p, c))) for c in DB["cands"][p]]
        elif s.startswith("DELETE FROM resultats"):
            DB["results"] = {k: v for k, v in DB["results"].items() if k[1] != kw["p"]}
        elif s.startswith("UPDATE postes"):
            DB["positions"][kw["p"]][0] = "CLOSED"
        elif s.startswith("UPDATE elections"):
            n = 0
            for e, st in DB["elections"].items():
                if st == "PUBLISHED" and not any(v[0] == "OPEN" and v[1] == e for v in DB["positions"].values()):
                    DB["elections"][e] = "CLOSED"; n += 1
            self.rowcount = n
    def executemany(self, sql, data):
        for r in data: DB["results"][(r[0], r[1], r[2])] = r[3:]
    def fetchall(self): return self._r
class Conn:
    def cursor(self): return Cur()
    def commit(self): pass
    def rollback(self): pass
class Pool:
    def acquire(self):
        class C:
            def __enter__(s): return Conn()
            def __exit__(s, *a): return False
        return C()
oracledb.create_pool = lambda **kw: Pool()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi.testclient import TestClient
import main
c = TestClient(main.app)
assert c.get("/health").json() == {"status": "ok"}
assert c.post("/internal/close").status_code == 401
assert c.post("/internal/close", headers={"Authorization": "Bearer wrong"}).status_code == 401
r = c.post("/internal/close", headers={"Authorization": "Bearer s3cret"})
print("1er appel :", r.status_code, r.json())
for k, v in sorted(DB["results"].items()): print("  ", k, v)
r2 = c.post("/internal/close", headers={"Authorization": "Bearer s3cret"})
print("2e appel  :", r2.json())
assert r2.json()["closed_positions"] == 0
print("OK")
