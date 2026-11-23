from fastapi import FastAPI
from dotenv import load_dotenv
import os

# Charge les variables du fichier .env
load_dotenv()

# Crée l'application
app = FastAPI(title="CloudVote API")

# Route de test pour voir si le serveur répond
@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "Le backend CloudVote est en ligne !"}