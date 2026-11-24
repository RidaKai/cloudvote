import oracledb
import os
from dotenv import load_dotenv

load_dotenv()

# On récupère les infos depuis le fichier .env
ORACLE_USER = os.getenv("ORACLE_USER")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD")
ORACLE_DSN = os.getenv("ORACLE_DSN")
WALLET_PASSWORD = os.getenv("WALLET_PASSWORD")
WALLET_DIR = os.getenv("WALLET_DIR", "./wallet")

def get_connection():
    """
    Ouvre une connexion sécurisée à la base de données Oracle.
    """
    try:
        connection = oracledb.connect(
            user=ORACLE_USER,
            password=ORACLE_PASSWORD,
            dsn=ORACLE_DSN,
            config_dir=WALLET_DIR,
            wallet_location=WALLET_DIR,
            wallet_password=WALLET_PASSWORD
        )
        return connection
    except oracledb.Error as e:
        print(f"Erreur de connexion à Oracle : {e}")
        raise