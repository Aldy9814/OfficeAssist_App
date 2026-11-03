import os, json, jwt, requests
from contextlib import asynccontextmanager, supress
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, HTTPException, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
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

DB_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASS = os.getenv("ADMIN_PASS")
engine = create_engine(DB_URL)

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)


cred = credentials.Certificate("ServiceAccountKey.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

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

# Registrasi Router
app.include_router(hr.router)
app.include_router(disposition.router)
app.include_router(vehicle.router)

# ==================== MIDDLEWARE AUTH (DASHBOARD) ====================
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public_paths = ["/login", "/api/login", "/api/logout", "/webhook"]
    if request.url.path in public_paths or request.url.path.startswith("/static") or request.url.path.startswith("/download"):
        return await call_next(request)

    token = request.cookies.get("access_token")
    if not token:
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"pesan": "Akses ditolak."})
        return RedirectResponse(url="/login")

    try:
        jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except:
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
        token = jwt.encode({"sub": data.username, "exp": datetime.utcnow() + timedelta(hours=24)}, SECRET_KEY, algorithm="HS256")
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
        logs = [dict(row._mapping) for row in conn.execute(text("SELECT timestamp, whatsapp_number, incoming_message, detected_intent, response_status FROM audit_logs ORDER BY timestamp DESC LIMIT 10")).fetchall()]
        for log in logs:
            log['timestamp'] = log['timestamp'].strftime("%Y-%m-%d %H:%M:%S")

    # Variabel total_inventory DIHAPUS dari dashboard!
    return templates.TemplateResponse(request=request, name="index.html", context={
        "total_employees": total_emp,
        "total_interactions": total_interactions,
        "audit_logs_json": json.dumps(logs)
    })

# ==================== WHATSAPP & GEMINI WEBHOOK ====================
def format_phone_number(phone: str) -> str:
    return phone if phone.endswith("@c.us") else f"{phone}@c.us"

def send_wa_text(to_number: str, text: str):
    requests.post(f"{GREEN_API_URL}/waInstance{GREEN_API_ID}/sendMessage/{GREEN_API_TOKEN}", json={"chatId": format_phone_number(to_number), "message": text})

def process_wa_message(sender_phone: str, message_text: str):
    # Prompt sementara (Nanti kita perbarui untuk mengelola intent disposisi & kendaraan)
    prompt_instruction = f"""
        Kamu adalah asisten AI HR OfficeAssist. 
        Analisis pesan ini: "{message_text}".
        Keluarkan output format JSON murni:
        {{"intent": "lainnya", "format": "excel", "keyword": null}}
    """
    try:
        response = client.models.generate_content(model='gemini-3.6-flash', contents=prompt_instruction)
        raw_json = response.text.strip().replace("```json", "").replace("```", "")
        extraction_result = json.loads(raw_json)
        
        intent = extraction_result.get("intent", "lainnya")
        
        # Logika sementara sebelum modul disposisi disambung
        send_wa_text(sender_phone, "Pesan diterima. Modul Super App sedang diintegrasikan.")
        
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO audit_logs (whatsapp_number, incoming_message, detected_intent, response_status) VALUES (:wa, :msg, :intent, 'sukses')"),
                         {"wa": sender_phone, "msg": message_text, "intent": intent})
    except Exception as e:
        print(f"Error Gemini: {e}")

@app.get("/webhook")
async def verify_webhook(request: Request):
    return int(request.query_params.get("hub.challenge", 0))

@app.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    if body.get("typeWebhook") in ["incomingMessageReceived"]:
        msg_data = body.get("messageData", {})
        msg_text = msg_data.get("textMessageData", {}).get("textMessage") or msg_data.get("extendedTextMessage", {}).get("text")
        if msg_text:
            background_tasks.add_task(process_wa_message, body["senderData"]["sender"], msg_text)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8080, reload=True)