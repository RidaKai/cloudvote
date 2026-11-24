from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from datetime import datetime, timezone

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
                return {"access_token": create_access_token(data=token_data), "role": user_role, "full_name": user_name}
    except HTTPException as ex:
        raise ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/me")
def get_my_info(current_user: dict = Depends(get_current_user)):
    return {"elector_id": current_user.get("elector_id"), "email": current_user.get("sub"), "full_name": current_user.get("full_name"), "role": current_user.get("role")}

# --- ROUTES ETUDIANTS (Oracle) ---

@app.get("/api/elections")
def list_elections(current_user: dict = Depends(get_current_user)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_election, titre, date_ouverture, date_cloture, statut FROM elections WHERE statut IN ('PUBLISHED', 'CLOSED') ORDER BY id_election DESC")
                elections = []
                for row in cursor:
                    elections.append({
                        "election_id": row[0], "title": row[1], "opens_at": str(row[2]), "closes_at": str(row[3]), "status": row[4]
                    })
                return elections
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/elections/{election_id}")
def get_election_details(election_id: int, current_user: dict = Depends(get_current_user)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_election, titre, date_ouverture, date_cloture, statut FROM elections WHERE id_election = :el_id", el_id=election_id)
                el_row = cursor.fetchone()
                if not el_row:
                    raise HTTPException(status_code=404, detail="Élection non trouvée")
                
                election = {"election_id": el_row[0], "title": el_row[1], "opens_at": str(el_row[2]), "closes_at": str(el_row[3]), "status": el_row[4]}
                
                cursor.execute("SELECT id_poste, nom, date_cloture, statut FROM postes WHERE id_election = :el_id", el_id=election_id)
                positions = []
                for p_row in cursor:
                    pos = {"position_id": p_row[0], "name": p_row[1], "closes_at": str(p_row[2]) if p_row[2] else None, "status": p_row[3], "candidates": []}
                    
                    cursor.execute("SELECT id_candidat, nom_complet, url_image FROM candidats WHERE id_poste = :pos_id", pos_id=p_row[0])
                    for c_row in cursor:
                        pos["candidates"].append({"candidate_id": c_row[0], "full_name": c_row[1], "image_url": c_row[2]})
                    
                    positions.append(pos)
                    
                return {"election": election, "positions": positions}
    except HTTPException as ex:
        raise ex
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/votes", status_code=201)
def cast_vote(request: VoteRequest, current_user: dict = Depends(get_current_user)):
    if not request.turnstile_token or request.turnstile_token != "captcha_valide":
        raise HTTPException(status_code=400, detail="CAPTCHA invalide")
    if current_user.get("role") != "ELECTOR":
        raise HTTPException(status_code=403, detail="Seuls les électeurs peuvent voter.")

    elector_id = current_user.get("elector_id")
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT statut, date_ouverture, date_cloture FROM elections WHERE id_election = :el_id", el_id=request.election_id)
                el = cursor.fetchone()
                if not el or el[0] != 'PUBLISHED':
                    raise HTTPException(status_code=400, detail="Élection non ouverte au vote")
                
                cursor.execute("SELECT SYSTIMESTAMP FROM dual")
                now_db = cursor.fetchone()[0]
                
                if now_db < el[1] or now_db > el[2]:
                     raise HTTPException(status_code=403, detail="Le vote est fermé (hors période).")
                
                # 👇 CORRECTION ICI : noms de variables longs pour éviter les conflits avec Oracle 👇
                cursor.execute("SELECT 1 FROM participations WHERE id_election = :election_id_val AND id_poste = :position_id_val AND id_electeur = :elector_id_val", 
                               election_id_val=request.election_id, position_id_val=request.position_id, elector_id_val=elector_id)
                if cursor.fetchone():
                    raise HTTPException(status_code=409, detail="Vous avez déjà voté pour ce poste.")
                
                cursor.execute("SELECT 1 FROM candidats WHERE id_candidat = :candidate_id_val AND id_poste = :position_id_val", candidate_id_val=request.candidate_id, position_id_val=request.position_id)
                if not cursor.fetchone():
                    raise HTTPException(status_code=400, detail="Candidat invalide pour ce poste.")
                
                cursor.execute("INSERT INTO participations (id_election, id_poste, id_electeur) VALUES (:election_id_val, :position_id_val, :elector_id_val)", 
                               election_id_val=request.election_id, position_id_val=request.position_id, elector_id_val=elector_id)
                
                cursor.execute("INSERT INTO bulletins (id_election, id_poste, id_candidat) VALUES (:election_id_val, :position_id_val, :candidate_id_val)", 
                               election_id_val=request.election_id, position_id_val=request.position_id, candidate_id_val=request.candidate_id)
                
                conn.commit()
                return {"message": "Vote enregistré avec succès"}
                
    except HTTPException as ex:
        raise ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur base de données : {str(e)}")

@app.get("/api/elections/{election_id}/results")
def get_results(election_id: int, current_user: dict = Depends(get_current_user)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT statut FROM elections WHERE id_election = :el_id", el_id=election_id)
                el = cursor.fetchone()
                if not el:
                     raise HTTPException(status_code=404, detail="Élection non trouvée")
                
                if el[0] != 'CLOSED' and current_user.get("role") not in ["ADMIN", "JURY"]:
                     raise HTTPException(status_code=403, detail="Les résultats ne sont pas encore publiés.")
                
                sql_counts = """
                    SELECT p.id_poste, p.nom, c.id_candidat, c.nom_complet, COUNT(b.id_bulletin) as total
                    FROM postes p
                    JOIN candidats c ON p.id_poste = c.id_poste
                    LEFT JOIN bulletins b ON c.id_candidat = b.id_candidat
                    WHERE p.id_election = :el_id
                    GROUP BY p.id_poste, p.nom, c.id_candidat, c.nom_complet
                    ORDER BY p.id_poste, total DESC
                """
                cursor.execute(sql_counts, el_id=election_id)
                rows = cursor.fetchall()
                
                results_dict = {}
                for row in rows:
                    pid, pname, cid, cname, count = row
                    if pid not in results_dict:
                        results_dict[pid] = {"position_id": pid, "name": pname, "total_votes": 0, "candidates": []}
                    
                    results_dict[pid]["candidates"].append({"candidate_id": cid, "full_name": cname, "total": count})
                    results_dict[pid]["total_votes"] += count

                final_results = []
                for pid, data in results_dict.items():
                    total = data["total_votes"]
                    max_votes = max([c["total"] for c in data["candidates"]]) if data["candidates"] else 0
                    
                    for cand in data["candidates"]:
                        cand["percentage"] = round((cand["total"] / total * 100), 2) if total > 0 else 0.0
                        max_count = sum(1 for c in data["candidates"] if c["total"] == max_votes)
                        cand["is_tie"] = 1 if (cand["total"] == max_votes and max_count > 1) else 0
                        
                    final_results.append(data)
                    
                return {"election_id": election_id, "status": el[0], "results": final_results}
    except HTTPException as ex:
         raise ex
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

# --- ROUTES ADMINISTRATEUR ---
@app.post("/api/admin/electors", status_code=201)
def create_elector(request: CreateElectorRequest, admin: dict = Depends(require_admin)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_electeur FROM electeurs WHERE email = :email", email=request.email)
                if cursor.fetchone():
                    raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
                hashed_pw = hash_password(request.password)
                sql = "INSERT INTO electeurs (email, nom_complet, hash_mot_de_passe, role, statut) VALUES (:email, :nom, :mdp, :role, 'ACTIVE') RETURNING id_electeur INTO :new_id"
                new_id = cursor.var(int)
                cursor.execute(sql, email=request.email, nom=request.full_name, mdp=hashed_pw, role=request.role, new_id=new_id)
                conn.commit()
                return {"message": "Électeur créé", "elector_id": new_id.getvalue()[0]}
    except HTTPException as ex: raise ex
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/elections", status_code=201)
def create_election(request: CreateElectionRequest, admin: dict = Depends(require_admin)):
    if request.closes_at <= request.opens_at:
        raise HTTPException(status_code=400, detail="La date de fin doit être après la date d'ouverture")
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                sql = "INSERT INTO elections (titre, date_ouverture, date_cloture, statut) VALUES (:titre, :ouverture, :cloture, 'DRAFT') RETURNING id_election INTO :new_id"
                new_id = cursor.var(int)
                cursor.execute(sql, titre=request.title, ouverture=request.opens_at, cloture=request.closes_at, new_id=new_id)
                conn.commit()
                return {"message": "Élection créée", "election_id": new_id.getvalue()[0], "status": "DRAFT"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/admin/elections/{election_id}")
def update_election(election_id: int, request: UpdateElectionRequest, admin: dict = Depends(require_admin)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_election FROM elections WHERE id_election = :el_id", el_id=election_id)
                if not cursor.fetchone(): 
                    raise HTTPException(status_code=404, detail="Élection non trouvée")
                
                if request.status: 
                    cursor.execute("UPDATE elections SET statut = :statut WHERE id_election = :el_id", statut=request.status, el_id=election_id)
                
                if request.opens_at: 
                    cursor.execute("UPDATE elections SET date_ouverture = :dt_ouv WHERE id_election = :el_id", dt_ouv=request.opens_at, el_id=election_id)
                if request.closes_at: 
                    cursor.execute("UPDATE elections SET date_cloture = :dt_clo WHERE id_election = :el_id", dt_clo=request.closes_at, el_id=election_id)
                
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
                cursor.execute("SELECT id_election FROM elections WHERE id_election = :el_id", el_id=election_id)
                if not cursor.fetchone(): raise HTTPException(status_code=404, detail="Élection non trouvée")
                sql = "INSERT INTO postes (id_election, nom, statut) VALUES (:eid, :nom, 'OPEN') RETURNING id_poste INTO :new_id"
                new_id = cursor.var(int)
                cursor.execute(sql, eid=election_id, nom=request.name, new_id=new_id)
                conn.commit()
                return {"message": "Poste créé", "position_id": new_id.getvalue()[0]}
    except HTTPException as ex: raise ex
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/positions/{position_id}/candidates", status_code=201)
def create_candidate(position_id: int, request: CreateCandidateRequest, admin: dict = Depends(require_admin)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id_poste FROM postes WHERE id_poste = :pos_id", pos_id=position_id)
                if not cursor.fetchone(): raise HTTPException(status_code=404, detail="Poste non trouvé")
                sql = "INSERT INTO candidats (id_poste, nom_complet, url_image) VALUES (:pid, :nom, :img) RETURNING id_candidat INTO :new_id"
                new_id = cursor.var(int)
                cursor.execute(sql, pid=position_id, nom=request.full_name, img=request.image_url, new_id=new_id)
                conn.commit()
                return {"message": "Candidat ajouté", "candidate_id": new_id.getvalue()[0]}
    except HTTPException as ex: raise ex
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/elections/{election_id}/stats")
def get_election_stats(election_id: int, admin: dict = Depends(require_admin)):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                sql = """
                    SELECT p.id_poste, p.nom, COUNT(pa.id_electeur) as count
                    FROM postes p
                    LEFT JOIN participations pa ON p.id_poste = pa.id_poste
                    WHERE p.id_election = :el_id
                    GROUP BY p.id_poste, p.nom
                """
                cursor.execute(sql, el_id=election_id)
                stats = []
                for row in cursor:
                    stats.append({"position_id": row[0], "name": row[1], "participation_count": row[2]})
                return {"election_id": election_id, "stats": stats}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

# ROUTE TEMPORAIRE POUR TESTER ORACLE
@app.get("/api/test-db")
def test_db():
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT SYSTIMESTAMP FROM dual")
                result = cursor.fetchone()
                return {"status": "Connexion Oracle réussie !", "db_time": str(result[0])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de connexion : {str(e)}")