from fastapi import APIRouter, Request, HTTPException, Form, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import os, json, shutil
from datetime import datetime
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL)

router = APIRouter(tags=["HR & Broadcast"])
templates = Jinja2Templates(directory="templates")

def serialize_row(row):
    d = dict(row._mapping)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
    return d

# ==================== MODULE: EMPLOYEE ====================
class EmployeeCreate(BaseModel):
    employee_id: str
    auto_id: bool
    full_name: str
    whatsapp_number: str
    division: str
    role: str

class EmployeeUpdate(BaseModel):
    full_name: str
    whatsapp_number: str
    division: str
    role: str

@router.get("/karyawan", response_class=HTMLResponse)
async def view_employees(request: Request):
    with engine.connect() as conn:
        query = text("SELECT employee_id, full_name, whatsapp_number, division, role FROM employees ORDER BY employee_id ASC")
        employee_list = [serialize_row(row) for row in conn.execute(query).fetchall()]
    return templates.TemplateResponse(request=request, name="karyawan.html", context={"employee_list_json": json.dumps(employee_list)})

@router.post("/api/employees")
async def create_employee(emp: EmployeeCreate):
    with engine.begin() as conn:
        wa_check = conn.execute(text("SELECT employee_id FROM employees WHERE whatsapp_number = :wa"), {"wa": emp.whatsapp_number}).fetchone()
        if wa_check:
            return JSONResponse(status_code=400, content={"status": "error", "pesan": "Nomor WhatsApp ini sudah terdaftar."})

        final_id = emp.employee_id
        if emp.auto_id:
            last_id_row = conn.execute(text("SELECT employee_id FROM employees WHERE employee_id LIKE 'EMP-%' ORDER BY CAST(SUBSTRING(employee_id, 5) AS UNSIGNED) DESC LIMIT 1")).fetchone()
            final_id = f"EMP-{int(last_id_row[0].split('-')[1]) + 1:03d}" if last_id_row else "EMP-001"
        else:
            if conn.execute(text("SELECT employee_id FROM employees WHERE employee_id = :id"), {"id": final_id}).fetchone():
                return JSONResponse(status_code=400, content={"status": "error", "pesan": f"ID {final_id} sudah digunakan."})

        conn.execute(text("INSERT INTO employees (employee_id, full_name, whatsapp_number, division, role) VALUES (:emp_id, :name, :wa, :div, :role)"),
                     {"emp_id": final_id, "name": emp.full_name, "wa": emp.whatsapp_number, "div": emp.division, "role": emp.role})
    return JSONResponse(content={"status": "success", "pesan": "Karyawan berhasil ditambahkan."})

@router.delete("/api/employees/{employee_id}")
async def delete_employee(employee_id: str):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM employees WHERE employee_id = :id"), {"id": employee_id})
    return JSONResponse(content={"status": "sukses", "pesan": f"Karyawan {employee_id} dihapus."})

@router.put("/api/employees/{employee_id}")
async def update_employee(employee_id: str, emp: EmployeeUpdate):
    with engine.begin() as conn:
        conn.execute(text("UPDATE employees SET full_name = :name, whatsapp_number = :wa, division = :div, role = :role WHERE employee_id = :id"),
                     {"name": emp.full_name, "wa": emp.whatsapp_number, "div": emp.division, "role": emp.role, "id": employee_id})
    return JSONResponse(content={"status": "success", "pesan": "Data diperbarui."})

# ==================== MODULE: BROADCAST ====================
UPLOAD_DIR = "uploads/broadcast"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.get("/broadcast", response_class=HTMLResponse)
async def view_broadcast(request: Request):
    with engine.connect() as conn:
        broadcast_list = [serialize_row(row) for row in conn.execute(text("SELECT * FROM broadcast_schedules ORDER BY scheduled_time DESC")).fetchall()]
        employee_list = [serialize_row(row) for row in conn.execute(text("SELECT employee_id, full_name, division FROM employees ORDER BY full_name ASC")).fetchall()]
    return templates.TemplateResponse(request=request, name="broadcast.html", context={"broadcast_list_json": json.dumps(broadcast_list), "employee_list_json": json.dumps(employee_list)})

@router.post("/api/broadcast")
async def create_broadcast(scheduled_time: str = Form(...), message: str = Form(...), attachment_type: str = Form(...), target_audience: str = Form(...), file: UploadFile = File(None)):
    with engine.begin() as conn:
        save_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if scheduled_time == "NOW" else scheduled_time
        file_path_db = ""
        if attachment_type != "teks" and file:
            file_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
            file_path_db = os.path.join(UPLOAD_DIR, file_name)
            with open(file_path_db, "wb+") as f:
                shutil.copyfileobj(file.file, f)
        
        conn.execute(text("INSERT INTO broadcast_schedules (scheduled_time, message, attachment_type, target_audience, file_path, status) VALUES (:time, :msg, :type, :target, :path, 'pending')"),
                     {"time": save_time, "msg": message, "type": attachment_type, "target": target_audience, "path": file_path_db})
    return JSONResponse(content={"status": "sukses", "pesan": "Jadwal disimpan!"})

@router.delete("/api/broadcast/{broadcast_id}")
async def delete_broadcast(broadcast_id: int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM broadcast_schedules WHERE id = :id"), {"id": broadcast_id})
    return JSONResponse(content={"status": "sukses"})

# ==================== MODULE: AUDIT LOG ====================
@router.get("/audit-log", response_class=HTMLResponse)
async def view_audit_log(request: Request):
    with engine.connect() as conn:
        audit_list = [serialize_row(row) for row in conn.execute(text("SELECT timestamp, whatsapp_number, incoming_message, detected_intent, response_status FROM audit_logs ORDER BY timestamp DESC")).fetchall()]
    return templates.TemplateResponse(request=request, name="audit_log.html", context={"audit_list_json": json.dumps(audit_list)})