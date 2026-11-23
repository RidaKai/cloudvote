import bcrypt
import jwt
import os
from datetime import datetime, timedelta, timezone

# Récupère le secret depuis le fichier .env
JWT_SECRET = os.getenv("JWT_SECRET", "fallback_secret")
ALGORITHM = "HS256"

# 1. Fonction pour hacher le mot de passe (quand on crée un compte)
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

# 2. Fonction pour vérifier si le mot de passe tapé est le bon
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# 3. Fonction pour générer le Token JWT (le badge de sécurité)
def create_access_token(data: dict):
    to_encode = data.copy()
    # Le token expirera dans 24 heures
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

# 4. Fonction pour vérifier un Token (utilisé pour protéger les routes)
def verify_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None