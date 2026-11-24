from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from datetime import datetime, timezone
from collections import Counter # Pour compter les votes facilement

from app.security import hash_password, verify_password, create_access_token, verify_token
from app.db import get_connection

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

# --- BASES DE DONNEES SIMULEES (Uniquement pour les routes étudiantes pour l'instant) ---
MOCK_ELECTIONS = []
MOCK_POSITIONS = []
MOCK_CANDIDATES = []
MOCK_PARTICIPATIONS = []
MOCK_BALLOTS = []

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

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                sql = "SELECT id_electeur, email, nom_complet, hash_mot_de_passe, role FROM electeurs WHERE email = :email"
                cursor.execute(sql, email=request.email)
                row = cursor.fetchone()
                
                if not row:
                    raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
                
                user_id, user_email, user_name, user_hash, user_role = row
                
                if not verify_password(request.password, user_hash):
                    raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
                
                token_data = {"sub": user_email, "role": user_role, "elector_id": user_id, "full_name": user_name}
                access_token = create_access_token(data=token_data)
                
                return {"access_token": access_token, "role": user_role, "full_name": user_name}
                
    except HTTPException as http_ex:
        raise http_ex 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur base de données : {str(e)}")

@app.get("/api/me")
def get_my_info(current_user: dict = Depends(get_current_user)):
    return {"elector_id": current_user.get("elector_id"), "email": current_user.get("sub"), "full_name": current_user.get("full_name"), "role": current_user.get("role")}


# --- ROUTES ADMINISTRATEUR (Connectées à Oracle) ---

@app.post("/api/admin/electors", status_code=201)
def create_elector(request: CreateElectorRequest, admin: dict = Depends(require_admin)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_electeur FROM electeurs WHERE email = :email", email=request.email)
                if cursor.fetchone():
                    raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
                
                hashed_pw = hash_password(request.password)
                sql = """
                    INSERT INTO electeurs (email, nom_complet, hash_mot_de_passe, role, statut) 
                    VALUES (:email, :nom, :mdp, :role, 'ACTIVE') 
                    RETURNING id_electeur INTO :new_id
                """
                new_id = cursor.var(int)
                cursor.execute(sql, email=request.email, nom=request.full_name, mdp=hashed_pw, role=request.role, new_id=new_id)
                conn.commit()
                return {"message": "Électeur créé", "elector_id": new_id.getvalue()[0]}
    except HTTPException as ex:
        raise ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/elections", status_code=201)
def create_election(request: CreateElectionRequest, admin: dict = Depends(require_admin)):
    if request.closes_at <= request.opens_at:
        raise HTTPException(status_code=400, detail="La date de fin doit être après la date d'ouverture")
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                sql = """
                    INSERT INTO elections (titre, date_ouverture, date_cloture, statut) 
                    VALUES (:titre, :ouverture, :cloture, 'DRAFT') 
                    RETURNING id_election INTO :new_id
                """
                new_id = cursor.var(int)
                cursor.execute(sql, titre=request.title, ouverture=request.opens_at, cloture=request.closes_at, new_id=new_id)
                conn.commit()
                return {"message": "Élection créée", "election_id": new_id.getvalue()[0], "status": "DRAFT"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/admin/elections/{election_id}")
def update_election(election_id: int, request: UpdateElectionRequest, admin: dict = Depends(require_admin)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_election FROM elections WHERE id_election = :id", id=election_id)
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Élection non trouvée")
                
                if request.status:
                    cursor.execute("UPDATE elections SET statut = :statut WHERE id_election = :id", statut=request.status, id=election_id)
                if request.opens_at:
                    cursor.execute("UPDATE elections SET date_ouverture = :date WHERE id_election = :id", date=request.opens_at, id=election_id)
                if request.closes_at:
                    cursor.execute("UPDATE elections SET date_cloture = :date WHERE id_election = :id", date=request.closes_at, id=election_id)
                
                conn.commit()
                return {"message": "Élection mise à jour avec succès"}
    except HTTPException as ex:
        raise ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/elections/{election_id}/positions", status_code=201)
def create_position(election_id: int, request: CreatePositionRequest, admin: dict = Depends(require_admin)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_election FROM elections WHERE id_election = :id", id=election_id)
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Élection non trouvée")
                
                sql = """
                    INSERT INTO postes (id_election, nom, statut) 
                    VALUES (:eid, :nom, 'OPEN') 
                    RETURNING id_poste INTO :new_id
                """
                new_id = cursor.var(int)
                cursor.execute(sql, eid=election_id, nom=request.name, new_id=new_id)
                conn.commit()
                return {"message": "Poste créé", "position_id": new_id.getvalue()[0]}
    except HTTPException as ex:
        raise ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/positions/{position_id}/candidates", status_code=201)
def create_candidate(position_id: int, request: CreateCandidateRequest, admin: dict = Depends(require_admin)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_poste FROM postes WHERE id_poste = :id", id=position_id)
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Poste non trouvé")
                
                sql = """
                    INSERT INTO candidats (id_poste, nom_complet, url_image) 
                    VALUES (:pid, :nom, :img) 
                    RETURNING id_candidat INTO :new_id
                """
                new_id = cursor.var(int)
                cursor.execute(sql, pid=position_id, nom=request.full_name, img=request.image_url, new_id=new_id)
                conn.commit()
                return {"message": "Candidat ajouté", "candidate_id": new_id.getvalue()[0]}
    except HTTPException as ex:
        raise ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- ROUTES ETUDIANTS (Encore en mode MOCK pour l'instant, on les fera après) ---
@app.get("/api/elections")
def list_elections(current_user: dict = Depends(get_current_user)):
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

@app.post("/api/votes", status_code=201)
def cast_vote(request: VoteRequest, current_user: dict = Depends(get_current_user)):
    if not request.turnstile_token or request.turnstile_token != "captcha_valide":
        raise HTTPException(status_code=400, detail="CAPTCHA invalide")
    if current_user.get("role") != "ELECTOR":
        raise HTTPException(status_code=403, detail="Seuls les électeurs peuvent voter.")

    elector_id = current_user.get("elector_id")
    election = next((e for e in MOCK_ELECTIONS if e["election_id"] == request.election_id), None)
    if not election or election["status"] != "PUBLISHED":
        raise HTTPException(status_code=400, detail="Élection non ouverte au vote")
    
    now = datetime.now(timezone.utc)
    opens_at = datetime.fromisoformat(election["opens_at"].replace('Z', '+00:00'))
    closes_at = datetime.fromisoformat(election["closes_at"].replace('Z', '+00:00'))

    if now < opens_at or now > closes_at:
        raise HTTPException(status_code=403, detail="Le vote est fermé (hors période).")

    already_voted = any(
        p["election_id"] == request.election_id and p["position_id"] == request.position_id and p["elector_id"] == elector_id 
        for p in MOCK_PARTICIPATIONS
    )
    if already_voted:
        raise HTTPException(status_code=409, detail="Vous avez déjà voté pour ce poste.")

    candidate_valid = any(
        c["candidate_id"] == request.candidate_id and c["position_id"] == request.position_id 
        for c in MOCK_CANDIDATES
    )
    if not candidate_valid:
        raise HTTPException(status_code=400, detail="Candidat invalide pour ce poste.")

    MOCK_PARTICIPATIONS.append({"election_id": request.election_id, "position_id": request.position_id, "elector_id": elector_id})
    MOCK_BALLOTS.append({"election_id": request.election_id, "position_id": request.position_id, "candidate_id": request.candidate_id})

    return {"message": "Vote enregistré avec succès"}

@app.get("/api/elections/{election_id}/results")
def get_results(election_id: int, current_user: dict = Depends(get_current_user)):
    election = next((e for e in MOCK_ELECTIONS if e["election_id"] == election_id), None)
    if not election:
        raise HTTPException(status_code=404, detail="Élection non trouvée")
        
    if election["status"] != "CLOSED" and current_user.get("role") not in ["ADMIN", "JURY"]:
         raise HTTPException(status_code=403, detail="Les résultats ne sont pas encore publiés.")

    results_by_position = []
    positions = [p for p in MOCK_POSITIONS if p["election_id"] == election_id]
    
    for pos in positions:
        pos_ballots = [b for b in MOCK_BALLOTS if b["position_id"] == pos["position_id"]]
        total_votes = len(pos_ballots)
        
        vote_counts = Counter([b["candidate_id"] for b in pos_ballots])
        max_votes = max(vote_counts.values()) if vote_counts else 0
        
        candidates_results = []
        pos_candidates = [c for c in MOCK_CANDIDATES if c["position_id"] == pos["position_id"]]
        
        for cand in pos_candidates:
            count = vote_counts.get(cand["candidate_id"], 0)
            percentage = round((count / total_votes * 100), 2) if total_votes > 0 else 0.0
            is_tie = 1 if (count == max_votes and list(vote_counts.values()).count(max_votes) > 1) else 0
            
            candidates_results.append({
                "candidate_id": cand["candidate_id"],
                "full_name": cand["full_name"],
                "total": count,
                "percentage": percentage,
                "is_tie": is_tie
            })
            
        results_by_position.append({
            "position_id": pos["position_id"],
            "name": pos["name"],
            "total_votes": total_votes,
            "candidates": candidates_results
        })
        
    return {"election_id": election_id, "status": election["status"], "results": results_by_position}

@app.get("/api/admin/elections/{election_id}/stats")
def get_election_stats(election_id: int, admin: dict = Depends(require_admin)):
    positions = [p for p in MOCK_POSITIONS if p["election_id"] == election_id]
    stats = []
    for pos in positions:
        count = sum(1 for p in MOCK_PARTICIPATIONS if p["position_id"] == pos["position_id"])
        stats.append({"position_id": pos["position_id"], "name": pos["name"], "participation_count": count})
    return {"election_id": election_id, "stats": stats}