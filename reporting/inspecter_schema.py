"""
Partie 4 - Inspecter le schéma réel de la base CloudVote.

Ce script :
  1) vérifie que la connexion à la base marche (wallet + mots de passe) ;
  2) écrit dans schema_bd.txt la liste des tables, colonnes et contraintes.

Il ne modifie RIEN dans la base (lecture seule).

Utilisation (dans le dossier reporting, environnement .venv activé,
variables DB_USER, DB_PASSWORD, DB_DSN, WALLET_DIR, WALLET_PASSWORD définies) :
    python inspecter_schema.py
"""
import os
import sys
import oracledb

NEEDED = ["DB_USER", "DB_PASSWORD", "DB_DSN", "WALLET_DIR", "WALLET_PASSWORD"]
missing = [v for v in NEEDED if not os.environ.get(v)]
if missing:
    sys.exit(f"ERREUR : variable(s) non définie(s) : {', '.join(missing)}")

wallet = os.environ["WALLET_DIR"]
for f in ("tnsnames.ora", "ewallet.pem"):
    if not os.path.isfile(os.path.join(wallet, f)):
        sys.exit(f"ERREUR : {f} introuvable dans {wallet} (le zip du wallet a-t-il été extrait ?)")

print("Connexion à la base...")
conn = oracledb.connect(
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    dsn=os.environ["DB_DSN"],
    config_dir=wallet,
    wallet_location=wallet,
    wallet_password=os.environ["WALLET_PASSWORD"],
)
print("Connexion OK.")
cur = conn.cursor()
out = []

cur.execute("SELECT USER, SYSTIMESTAMP FROM dual")
user, now = cur.fetchone()
out.append(f"Utilisateur connecté : {user}   Heure de la base : {now}\n")

cur.execute("SELECT table_name FROM user_tables ORDER BY table_name")
tables = [r[0] for r in cur.fetchall()]
out.append(f"Tables ({len(tables)}) : {', '.join(tables) or 'AUCUNE'}\n")
if not tables:
    out.append("!! Aucune table pour cet utilisateur : le schéma a peut-être été créé sous ADMIN.\n")

for t in tables:
    out.append("=" * 70)
    out.append(f"TABLE {t}")
    cur.execute("""SELECT column_name, data_type, data_length, data_precision, data_scale,
                          nullable, data_default
                   FROM user_tab_columns WHERE table_name = :t ORDER BY column_id""", t=t)
    for name, typ, length, prec, scale, nullable, default in cur.fetchall():
        if typ in ("VARCHAR2", "CHAR", "RAW"):
            typ = f"{typ}({length})"
        elif typ == "NUMBER" and prec is not None:
            typ = f"NUMBER({prec},{scale})"
        null = "" if nullable == "Y" else " NOT NULL"
        dflt = f" DEFAULT {str(default).strip()}" if default else ""
        out.append(f"   {name:<28} {typ}{null}{dflt}")

    cur.execute("""
        SELECT c.constraint_name, c.constraint_type, c.search_condition_vc,
               (SELECT LISTAGG(cc.column_name, ', ') WITHIN GROUP (ORDER BY cc.position)
                  FROM user_cons_columns cc WHERE cc.constraint_name = c.constraint_name) cols,
               r.table_name ref_table,
               (SELECT LISTAGG(rc.column_name, ', ') WITHIN GROUP (ORDER BY rc.position)
                  FROM user_cons_columns rc WHERE rc.constraint_name = c.r_constraint_name) ref_cols
        FROM user_constraints c
        LEFT JOIN user_constraints r ON r.constraint_name = c.r_constraint_name
        WHERE c.table_name = :t AND c.constraint_type IN ('P','U','R','C')
        ORDER BY c.constraint_type, c.constraint_name""", t=t)
    kinds = {"P": "PRIMARY KEY", "U": "UNIQUE", "R": "FOREIGN KEY", "C": "CHECK"}
    for name, typ, cond, cols, ref_t, ref_c in cur.fetchall():
        if typ == "C" and cond and cond.strip().upper().endswith("IS NOT NULL"):
            continue  # on ignore les simples NOT NULL
        line = f"   [{kinds[typ]}] {name} ({cols})"
        if typ == "R":
            line += f" -> {ref_t}({ref_c})"
        if typ == "C":
            line += f" : {cond}"
        out.append(line)
    out.append("")

text = "\n".join(out)
with open("schema_bd.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)
print("\n>>> Résultat enregistré dans schema_bd.txt")
conn.close()
