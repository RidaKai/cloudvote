import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_connection
from app.security import hash_password

def create_admin():
    print("Connexion à Oracle...")
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # On cherche avec les noms en français (id_electeur, electeurs)
                cursor.execute("SELECT id_electeur FROM electeurs WHERE email = :email", email="admin@esi.ac.ma")
                if cursor.fetchone():
                    print("L'admin existe déjà dans la base de données !")
                    return

                hashed_pw = hash_password("Admin123!")

                # On insère avec les noms en français
                sql = """
                    INSERT INTO electeurs (email, nom_complet, hash_mot_de_passe, role, statut)
                    VALUES (:email, :nom_complet, :hash_mdp, :role, 'ACTIVE')
                """
                cursor.execute(sql, email="admin@esi.ac.ma", nom_complet="Admin CloudVote", hash_mdp=hashed_pw, role="ADMIN")
                conn.commit()
                print("Admin créé avec succès dans Oracle !")
    except Exception as e:
        print(f"Erreur : {e}")

if __name__ == "__main__":
    create_admin()