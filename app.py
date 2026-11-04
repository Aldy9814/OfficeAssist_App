import os, json, jwt, requests, hmac, asyncio, jwt
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials

load_dotenv()

from google import genai
from routers import hr, disposition, vehicle
from services.dispatcher import handle_message
from services.poller import run_poller
from services.wa_client import ConsoleClient, get_client, parse_incoming

DB_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASS = os.getenv("ADMIN_PASS")
INTERNAL_API_KEY= os.getenv("INTERNAL_API_KEY")
engine = create_engine(DB_URL)

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)


if not firebase_admin._apps:
    cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH","ServiceAccountKey.json"))
    firebase_admin.initialize_app(cred)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if os.getenv("WA_PROVIDER", "console").lower() == "greenapi" and os.getenv("WA_MODE", "polling").lower() == "polling":
        task = asyncio.create_task(run_poller())
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

# Setup Green API
GREEN_API_URL = os.getenv("GREEN_API_URL")
GREEN_API_ID = os.getenv("GREEN_API_ID")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")

app = FastAPI(title="OfficeAssist Super App")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(hr.router)
app.include_router(disposition.router)
app.include_router(vehicle.router)

# ==================== MIDDLEWARE AUTH (DASHBOARD) ====================
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    public_paths = ["/login", "/api/login", "/api/logout", "/webhook"]
    if path in public_paths or path.startswith("/static") or path.startswith("/download"):
        return await call_next(request)

    key = request.headers.get("X-API-Key")
    if INTERNAL_API_KEY and key and hmac.compare_digest(key, INTERNAL_API_KEY):
        return await call_next(request)

    token = request.cookies.get("access_token")
    if not token:
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"pesan": "Akses ditolak."})
        return RedirectResponse(url="/login")

    try:
        jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return RedirectResponse(url="/login")
    return await call_next(request)
    

# ==================== LOGIN & DASHBOARD (ROOT) ====================
class LoginData(BaseModel):
    username: str
    password: str

@app.get("/login", response_class=HTMLResponse)    
async def view_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/api/login")
async def process_login(data: LoginData):
    if data.username == ADMIN_USER and data.password == ADMIN_PASS:
        token = jwt.encode(
            {"sub": data.username, "exp": datetime.utcnow() + timedelta(hours=24)}, 
            SECRET_KEY, 
            algorithm="HS256"
        )
        response = JSONResponse(content={"status": "success", "pesan": "Login berhasil"})
        response.set_cookie(key="access_token", value=token, httponly=True, max_age=86400)
        return response
    return JSONResponse(status_code=401, content={"status": "error", "pesan": "Username/Password salah."})

@app.post("/api/logout")
async def process_logout():
    response = JSONResponse(content={"status": "success", "pesan": "Logout berhasil."})
    response.delete_cookie("access_token")
    return response

@app.get("/", response_class=HTMLResponse)
async def view_dashboard(request: Request):
    with engine.connect() as conn:
        total_emp = conn.execute(text("SELECT COUNT(*) FROM employees")).scalar() or 0
        total_interactions = conn.execute(text("SELECT COUNT(*) FROM audit_logs WHERE DATE(timestamp) = CURDATE()")).scalar() or 0
        logs = [dict(row._mapping) for row in conn.execute(text(
            "SELECT timestamp, whatsapp_number, incoming_message, detected_intent, response_status FROM audit_logs ORDER BY timestamp DESC LIMIT 10")).fetchall()]
        for log in logs:
            log['timestamp'] = log['timestamp'].strftime("%Y-%m-%d %H:%M:%S")

    # Variabel total_inventory DIHAPUS dari dashboard!
    return templates.TemplateResponse(request=request, name="index.html", context={
        "total_employees": total_emp,
        "total_interactions": total_interactions,
        "audit_logs_json": json.dumps(logs)
    })

# ==================== WHATSAPP & GEMINI WEBHOOK ====================
@app.get("/webhook")
async def verify_webhook(request: Request):
    return int(request.query_params.get("hub.challenge", 0))
 
 
# Webhook mode (Green API webhook or later Meta). Not used in polling mode.
@app.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    parsed = parse_incoming(body)
    if parsed:
        background_tasks.add_task(handle_message, parsed[0], parsed[1], get_client())
    return {"status": "ok"}
 
 
# Dev/test endpoint: no WhatsApp needed. Requires dashboard login (open /docs after logging in).
class SimulatedMessage(BaseModel):
    sender: str = "6281234567890"
    text: str
 
 
@app.post("/webhook/simulate")
def simulate_message(msg: SimulatedMessage):
    client = ConsoleClient()
    handle_message(msg.sender, msg.text, client)
    return {"replies": client.sent}
 
 
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)