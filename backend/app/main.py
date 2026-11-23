from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from datetime import datetime, timezone

from app.security import hash_password, verify_password, create_access_token, verify_token

load_dotenv()
app = FastAPI(title="CloudVote API")

# --- MODELES DE DONNEES ---
class LoginRequest(BaseModel):
    email: str
    password: str
    turnstile_token: str

class CreateElectorRequest(BaseModel):
    email: str
    full_name: str
    password: str
    role: str = "ELECTOR"

class CreateElectionRequest(BaseModel):
    title: str
    opens_at: datetime
    closes_at: datetime

class UpdateElectionRequest(BaseModel):
    status: str = None
    opens_at: datetime = None
    closes_at: datetime = None

class CreatePositionRequest(BaseModel):
    name: str
    closes_at: datetime = None

class CreateCandidateRequest(BaseModel):
    full_name: str
    elector_id: int = None
    image_url: str = None

class VoteRequest(BaseModel):
    election_id: int
    position_id: int
    candidate_id: int
    turnstile_token: str

# --- BASES DE DONNEES SIMULEES ---
MOCK_ELECTORS = [
    {"elector_id": 1, "email": "admin@esi.ac.ma", "full_name": "Admin CloudVote", "role": "ADMIN", "password_hash": hash_password("Admin123!")}
]
MOCK_ELECTIONS = []
MOCK_POSITIONS = []
MOCK_CANDIDATES = []
MOCK_PARTICIPATIONS = [] # Pour vérifier si l'étudiant a déjà voté
MOCK_BALLOTS = [] # Les votes (anonymes)

election_id_counter = 1
position_id_counter = 1
candidate_id_counter = 1

# --- SECURITE ---
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")
    return payload

def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Accès refusé. Réservé aux administrateurs.")
    return current_user

# --- ROUTES PUBLIQUES ---
@app.get("/api/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/auth/login")
def login(request: LoginRequest):
    if not request.turnstile_token or request.turnstile_token != "captcha_valide": 
         raise HTTPException(status_code=400, detail="CAPTCHA invalide")

    user = next((u for u in MOCK_ELECTORS if u["email"] == request.email), None)
    if not user or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    token_data = {"sub": user["email"], "role": user["role"], "elector_id": user["elector_id"], "full_name": user["full_name"]}
    return {"access_token": create_access_token(data=token_data), "role": user["role"], "full_name": user["full_name"]}

@app.get("/api/me")
def get_my_info(current_user: dict = Depends(get_current_user)):
    return {"elector_id": current_user.get("elector_id"), "email": current_user.get("sub"), "full_name": current_user.get("full_name"), "role": current_user.get("role")}

# --- ROUTES ETUDIANTS ---
@app.get("/api/elections")
def list_elections(current_user: dict = Depends(get_current_user)):
    # L'étudiant ne voit que les élections PUBLIÉES ou FERMÉES
    visible_elections = [e for e in MOCK_ELECTIONS if e["status"] in ["PUBLISHED", "CLOSED"]]
    return visible_elections

@app.get("/api/elections/{election_id}")
def get_election_details(election_id: int, current_user: dict = Depends(get_current_user)):
    election = next((e for e in MOCK_ELECTIONS if e["election_id"] == election_id), None)
    if not election:
        raise HTTPException(status_code=404, detail="Élection non trouvée")
    
    positions = [p for p in MOCK_POSITIONS if p["election_id"] == election_id]
    for pos in positions:
        pos["candidates"] = [c for c in MOCK_CANDIDATES if c["position_id"] == pos["position_id"]]
        
    return {"election": election, "positions": positions}

# LA ROUTE POUR VOTER
@app.post("/api/votes", status_code=201)
def cast_vote(request: VoteRequest, current_user: dict = Depends(get_current_user)):
    # 1. Vérifier le CAPTCHA
    if not request.turnstile_token or request.turnstile_token != "captcha_valide":
        raise HTTPException(status_code=400, detail="CAPTCHA invalide")

    # 2. Vérifier que l'utilisateur est bien un électeur (pas un admin)
    if current_user.get("role") != "ELECTOR":
        raise HTTPException(status_code=403, detail="Seuls les électeurs peuvent voter.")

    elector_id = current_user.get("elector_id")

    # 3. Vérifier les dates de l'élection (avec l'heure UTC actuelle)
    election = next((e for e in MOCK_ELECTIONS if e["election_id"] == request.election_id), None)
    if not election or election["status"] != "PUBLISHED":
        raise HTTPException(status_code=400, detail="Élection non ouverte au vote")
    
    now = datetime.now(timezone.utc)
    opens_at = datetime.fromisoformat(election["opens_at"].replace('Z', '+00:00'))
    closes_at = datetime.fromisoformat(election["closes_at"].replace('Z', '+00:00'))

    if now < opens_at or now > closes_at:
        raise HTTPException(status_code=403, detail="Le vote est fermé (hors période).")

    # 4. Vérifier si l'étudiant n'a pas déjà voté pour ce poste
    already_voted = any(
        p["election_id"] == request.election_id and 
        p["position_id"] == request.position_id and 
        p["elector_id"] == elector_id 
        for p in MOCK_PARTICIPATIONS
    )
    if already_voted:
        raise HTTPException(status_code=409, detail="Vous avez déjà voté pour ce poste.")

    # 5. Vérifier que le candidat est bien dans ce poste
    candidate_valid = any(
        c["candidate_id"] == request.candidate_id and 
        c["position_id"] == request.position_id 
        for c in MOCK_CANDIDATES
    )
    if not candidate_valid:
        raise HTTPException(status_code=400, detail="Candidat invalide pour ce poste.")

    # 6. Enregistrer la participation (Qui a voté)
    MOCK_PARTICIPATIONS.append({
        "election_id": request.election_id, 
        "position_id": request.position_id, 
        "elector_id": elector_id
    })
    
    # 7. Enregistrer le bulletin (Le choix, de manière anonyme)
    MOCK_BALLOTS.append({
        "election_id": request.election_id,
        "position_id": request.position_id,
        "candidate_id": request.candidate_id
    })

    return {"message": "Vote enregistré avec succès"}

# --- ROUTES ADMINISTRATEUR ---
@app.post("/api/admin/electors", status_code=201)
def create_elector(request: CreateElectorRequest, admin: dict = Depends(require_admin)):
    if any(u["email"] == request.email for u in MOCK_ELECTORS):
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
    new_id = len(MOCK_ELECTORS) + 1
    MOCK_ELECTORS.append({"elector_id": new_id, "email": request.email, "full_name": request.full_name, "role": request.role, "password_hash": hash_password(request.password)})
    return {"message": "Électeur créé", "elector_id": new_id}

@app.post("/api/admin/elections", status_code=201)
def create_election(request: CreateElectionRequest, admin: dict = Depends(require_admin)):
    global election_id_counter
    if request.closes_at <= request.opens_at:
        raise HTTPException(status_code=400, detail="La date de fin doit être après la date d'ouverture")
    new_election = {"election_id": election_id_counter, "title": request.title, "opens_at": request.opens_at.isoformat(), "closes_at": request.closes_at.isoformat(), "status": "DRAFT"}
    MOCK_ELECTIONS.append(new_election)
    election_id_counter += 1
    return {"message": "Élection créée", "election": new_election}

# NOUVELLE ROUTE : Modifier le statut de l'élection (ex: passer en PUBLISHED)
@app.patch("/api/admin/elections/{election_id}")
def update_election(election_id: int, request: UpdateElectionRequest, admin: dict = Depends(require_admin)):
    election = next((e for e in MOCK_ELECTIONS if e["election_id"] == election_id), None)
    if not election:
        raise HTTPException(status_code=404, detail="Élection non trouvée")
    
    if request.status:
        if request.status not in ["DRAFT", "PUBLISHED", "CLOSED"]:
             raise HTTPException(status_code=400, detail="Statut invalide")
        election["status"] = request.status
        
    if request.opens_at: election["opens_at"] = request.opens_at.isoformat()
    if request.closes_at: election["closes_at"] = request.closes_at.isoformat()
    
    return {"message": "Élection mise à jour", "election": election}

@app.post("/api/admin/elections/{election_id}/positions", status_code=201)
def create_position(election_id: int, request: CreatePositionRequest, admin: dict = Depends(require_admin)):
    global position_id_counter
    if not any(e["election_id"] == election_id for e in MOCK_ELECTIONS):
        raise HTTPException(status_code=404, detail="Élection non trouvée")
    new_position = {"position_id": position_id_counter, "election_id": election_id, "name": request.name, "closes_at": request.closes_at, "status": "OPEN"}
    MOCK_POSITIONS.append(new_position)
    position_id_counter += 1
    return {"message": "Poste créé", "position": new_position}

@app.post("/api/admin/positions/{position_id}/candidates", status_code=201)
def create_candidate(position_id: int, request: CreateCandidateRequest, admin: dict = Depends(require_admin)):
    global candidate_id_counter
    if not any(p["position_id"] == position_id for p in MOCK_POSITIONS):
        raise HTTPException(status_code=404, detail="Poste non trouvé")
    new_candidate = {"candidate_id": candidate_id_counter, "position_id": position_id, "full_name": request.full_name, "elector_id": request.elector_id, "image_url": request.image_url}
    MOCK_CANDIDATES.append(new_candidate)
    candidate_id_counter += 1
    return {"message": "Candidat ajouté", "candidate": new_candidate}