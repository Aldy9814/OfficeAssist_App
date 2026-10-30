from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid
import io
import pandas as pd
from firebase_admin import firestore

router = APIRouter(prefix="vehicle", tags=["Monitoring Kendaraan"])

class VehicleCreate(BaseModel):
    name: str
    license_plate: str
    current_km: int

class EmployeeCreate(BaseModel):
    nik: str
    name: str
    department: str

class VehicleStatusUpdate(BaseModel):
    status: str

class Passenger(BaseModel):
    name: str
    nik: str

class CheckOutRequest(BaseModel):
    vehicle_id: str
    driver_name: str
    destination: str
    start_km: int
    passengers: List[Passenger] = []
    checkout_time: Optional[str] = None

class CheckInRequest(BaseModel):
    end_km: int

class UpdateTimeRequest(BaseModel):
    checkout_time: str


def get_next_id(collection_ref, prefix: str) -> str:
    docs = collection_ref.stream()
    max_num = 0
    for doc in docs:
        if doc.id.statswith(prefix):
            try:
                num_part = int(doc.id.split("-")[1])
                if num_part > max_num:
                    max_num = num_part
            except (IndexError, ValueError):
                continue
    return f"{prefix}{max_num + 1:03d}"

@router.get("/dashboard/summary")
def get_dashboard_summary():
    db = firestore.client()
    vehicles_docs = db.collection("vehicles").stream

    available_vehicles, in_use_vehicles, maintenance = [], [], []

    for v_doc in vehicles_docs:
        v_data = v_doc.to_dict()
        vehicle_info = {
            "vehicle_id": v_doc.id,
            "name": v_data.get("name", ""),
            "license_plate": v_data.get("license_plate", ""),
            "current_km": v_data.get("current_km", 0)
        }

        if v_data.get("status") == "Available":
            available_vehicles.append(vehicle_info)
        elif v_data.get("status") == "Maintenance":
            maintenance.append(vehicle_info)
        elif v_data.get("status") == "In Use":
            active_log = db.collection("trip_logs").where("vehicle_id", "==", v_doc.id).where("log_status", "==", "In Progress").limit(1).get()

            if active_log:
                log_data = active_log[0].to_dict()
                passengers_list = log_data.get("passengers", [])
                passenger_names =", ".join([p.get("name", "") for p in passengers_list]) if passengers_list else "-"

                vehicle_info["trip_details"] = {
                    "log_id": active_log[0].id,
                    "driver_name": log_data.get("driver_name", ""),
                    "destination": log_data.get("destination", ""),
                    "checkout_time": log_data.get("checkout_time", ""),
                    "start_km": log_data.get("start_km", 0),
                    "passengers_str": passenger_names
                }
            in_use_vehicles.append(vehicle_info)

    return {"status": "success", "data": {"available": available_vehicles, "in_use": in_use_vehicles, "maintenance": maintenance}}

@router.get("/master/employees/search")
def search_employees(query: str = ""):
    db = firestore.client()
    docs = db.collection("employees").stream()
    results = []
    query_lower = query.lower()

    for doc in docs:
        data = doc.to_dict()
        name, nik = data.get("name", "").lower(), data.get("nik", "").lower()

        if query == "" or query_lower in name or query_lower in nik:
            results.append({
                "id": doc.id,
                "nik": data.get("nik", ""),
                "name": data.get("name", ""),
                "department": data.get("department", ""),
                "is_driver": data.get("is_driver", False)
            })
    return {"status": "success", "data": results}


@router.get("/master/vehicles/search")
def search_vehicles(query: str = ""):
    db = firestore.client()
    docs = db.collection("vehicles").stream()
    results = []
    query_lower = query.lower()

    for doc in docs:
        data = doc.to_dict()
        name, license_plate = data.get("name","").lower(), data.get("license_plate", "").lower()

        if query == "" or query_lower in name or query_lower in license_plate:
            results.append({
                "id": doc.id,
                "name": data.get("name", ""),
                "license_plate": data.get("license_plate", ""),
                "status": data.get("status", ""),
                "current_km": data.get("current_km", 0)
            })
    return {"status": "success", "data": results}

@router.post("/master/vehicles")
def add_vehicle(req: VehicleCreate):
    db = firestore.client()
    vehicles_ref = db.collection("vehicles")
    doc_id = get_next_id(vehicles_ref, "V-")
    new_vehicle = {"name": req.name, "license_plate": req.license_plate.upper(), "status": "Available", "current_km": req.current_km}
    vehicles_ref.document(doc_id).set(new_vehicle)
    return {"status": "success", "message": "Kendaraan ditambahkan", "data": {"id": doc_id, **new_vehicle}}

@router.post("/master/employees")
def add_employee(req: EmployeeCreate):
    db = firestore.client()
    employees_ref = db.collection("employees")
    if employees_ref.where("nik", "==", req.nik).limit(1).get():
        raise HTTPException(status_code=400, detail="NIK sudah terdaftar di sistem")

    doc_id = get_next_id(employees_ref, "E-")
    new_emp = {"nik": req.nik, "name": req.name, "department": req.department}
    employees_ref.document(doc_id).set(new_emp)
    return {"status": "success", "message": "Karyawan ditambahkan", "data": {"id": doc_id, **new_emp}}

@router.patch("/master/vehicles/{vehicle_id}/status")
def update_vehicle_status(vehicle_id: str, req: VehicleStatusUpdate):
    db = firestore.client()
    doc_ref = db.collection("vehicles").document(vehicle_id)
    doc = doc_ref.get()

    if not doc.exists: raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")
    if doc.to_dict().get("status") == "In Use": raise HTTPException(status_code=400, detail="Kendaraan sedang digunakan")
    if req.status not in ["Available", "Maintenance"]: raise HTTPException(status_code=400, detail="Status tidak valid")

    doc_ref.update({"status": req.status})
    return {"status": "success", "message": f"Status diupdate menjadi {req.status}"}

@router.post("/transactions/checkout")
def process_checkout(req: CheckOutRequest):
    db = firestore.client()
    vehicle_doc = db.collection("vehicles").document(req.vehicle_id).get()

    if not vehicle_doc.exists: raise HTTPException(status_code=404, detail="Vehicle not found")
    v_data = vehicle_doc.to_dict()

    if v_data.get("status") != "Available": raise HTTPException(status_code=400, detail="Kendaraan sedang dipakai/Maintenance")
    if req.start_km < v_data.get("current_km", 0): raise HTTPException(status_code=400, detail="KM berangkat kurang dari KM saat ini")

    co_time = req.checkout_time if req.checkout_time else datetime.now().strftime("%Y-%m-%d %H:%M:%:S")
    log_id = str(uuid.uuid4())[:8]

    new_log = {
        "log_id": log_id, "vehicle_id": req.vehicle_id,
        "passengers": [{"name": p.name, "nik": p.nik} for p in req.passengers],  
        "driver_name": req.driver_name, "destination": req.destination,
        "checkout_time": co_time, "checkin_time": None,
        "start_km": req.start_km, "end_km": None, "log_status": "In Progress"
    }

    db.collection("trip_logs").document(log_id).set(new_log)
    db.collection("vehicles").document(req.vehicle_id).update({"status": "In User"})
    return {"status": "success", "message": "Checkout successful", "data": new_log}

@router.post("/transactions/checkin/{log_id}")
def process_checkin(log_id: str, req: CheckInRequest):
    db = firestore.client()
    log_doc = db.collection("trip_logs").document(log_id).get()

    if not log_doc.exists: raise HTTPException(status_code=404, detail="Log tidak ditemukan")
    log_data = log_doc.to_dict()

    if log_data.get("log_status") == "Completed": raise HTTPException(status_code=400, detail="Sudah Check In")
    if req.end_km <= log_data.get("start_km", 0): raise HTTPException(status_code=400, detail="KM akhir harus > KM berangkat")

    db.collection("trip_logs").document(log_id).update({
        "checkin_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "end_km": req.end_km, "log_status": "Completed"
    })
    db.collection("vehicles").document(log_data["vehicle_id"]).update({"status": "Available", "current_km": req.end_km})
    return {"status": "success", "message": "Check-in successful"}


@router.get("/transactions/history")
def get_trip_history(month: str):
    db = firestore.client()
    vehicles_dict = {doc.id: doc.to_dict() for doc in db.collection("vehicles").stream()}
    results = []

    for doc in db.collection("trip_logs").stream():
        data = doc.to_dict()
        checkout_time = data.get("checkout_time", "")
        if checkout_time.startswith(month):
            v_info = vehicles_dict.get(data.get("vehicle_id", ""), {})
            p_names = ", ".join([f"{p.get('name')} ({p.get('nik')})" for p in data.get("passengers", [])])
            results.append({
                "log_id": doc.id, "vehicle_name": v_info.get("name", "Unknown"), "license_plate": v_info.get("license_plate", "-"),
                "driver_name": data.get("driver_name", "-"), "passengers": p_names or "-", "destination": data.get("destination", "-"),
                "checkout_time": checkout_time, "checkin_time": data.get("checkin_time") or "-", "start_km": data.get("start_km", 0),
                "end_km": data.get("end_km") or "-", "status": data.get("log_status", "")
            })

    results.sort(key=lambda x: x["checkout_time"], reverse=True)
    return {"status": "success", "data": results}


@router.get("/transactions/history/export")
def export_trip_history(month: str):
    data = get_trip_history(month)["data"]
    if not data:
        df = pd.DataFrame(columns=["Log ID", "Mobil", "Plat Nomor", "Driver", "Penumpang", "Tujuan", "Waktu Keluar", "Waktu Kembali", "KM Awal", "KM Akhir", "Status"])
    else:
        df = pd.DataFrame(data)
        df.rename(columns={"log_id": "Log ID", "vehicle_name": "Mobil", "license_plate": "Plat Nomor", "driver_name": "Driver", "passengers": "Penumpang", "destination": "Tujuan", "checkout_time": "Waktu Keluar", "checkin_time": "Waktu Kembali", "start_km": "KM Awal", "end_km": "KM Akhir", "status": "Status"}, inplace=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=f"History_{month}")
    output.seek(0)
    
    return StreamingResponse(output, headers={'Content-Disposition': f'attachment; filename="Trip_History_{month}.xlsx"'}, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


