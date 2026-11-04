import os
from collections import Counter
from datetime import date
from typing import List, Optional

import pandas as pd 
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

REPORT_DIR = "uploads/reports"

EXCEL_COLUMNS = {
    "log_id": "Log ID", "vehicle_name": "Mobil", "license_plate": "Plat Nomor",
    "driver_name": "Driver", "passengers": "Penumpang", "destination": "Tujuan",
    "checkout_time": "Waktu Keluar", "checkin_time": "Waktu Kembali",
    "start_km": "KM Awal", "end_km": "KM Akhir", "status": "Status",
}

def fetch_trips(start: date, end: date, keyword: Optional[str]= None) -> List[dict]:
    db = firestore.client()
    start_s = f"{start.isoformat()} 00:00:00"
    end_s = f"{end.isoformat()} 23:59:59"

    vehicles = {d.id: d.to_dict() for d in db.collection("vehicles").stream()}
    query = (
        db.collection("trip_logs")
        .where(filter=FieldFilter("checkout_time", ">=", start_s))
        .where(filter=FieldFilter("checkout_time", "<=", end_s))
    )

    rows = []
    for doc in query.stream():
        d = doc.to_dict()
        v = vehicles.get(d.get("vehicle_id", ""), {})
        row = {
            "log_id": doc.id,
            "vehicle_name": v.get("name", "Unknown"),
            "license_plate": v.get("license_plate", "-"),
            "driver_name": d.get("driver_name", "-"),
            "passengers": ", ".join(f"{p.get('name')} ({p.get('nik')})" for p in d.get("passengers", [])) or "-",
            "destination": d.get("destination", "-"),
            "checkout_time": d.get("checkout_time", ""),
            "checkin_time": d.get("checkin_time") or "-",
            "start_km": d.get("start_km", 0),
            "end_km": d.get("end_km"),
            "status": d.get("log_status", ""),
        }
        if keyword:
            k = keyword.lower().replace(" ", "")
            hay = f"{row['vehicle_name']} {row['license_plate']}".lower().replace(" ", "")
            if k not in hay:
                continue
        rows.append(row)

    rows.sort(key=lambda x: x["checkout_time"], reverse=True)

    return rows

def build_excel(rows: List[dict], start: date, end: date):
    os.makedirs(REPORT_DIR, exist_ok=True)
    df = pd.DataFrame(rows, columns=list(EXCEL_COLUMNS.keys()))
    df["end_km"] = df["end_km"].apply(lambda v: "-" if v is None or pd.isna(v) else v)
    df = df.rename (columns=EXCEL_COLUMNS)
    path = os.path.join(REPORT_DIR, f"Laporan_kendaraan_{start.isoformat()}_{end.isoformat()}.xlsx")
    with pd.ExcelWriter(path ,engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Laporan")
    return path

def format_summary(rows: List[dict], start: date, end: date) -> str:
    period = f"{start:%d-%m-%Y}" if start == end else f"{start:%d-%m-%Y} s.d. {end:%d-%m-%Y}"
    if not rows:
        return f"Laporan Kendaraan ({period})\nTidak ada perjalanan pada periode ini."

    done = [r for r in rows if r["status"] == "Completed"]
    active = [r for r in rows if r["status"] == "In Progress"]
    total_km = sum(
        r["end_km"] - r["start_km"]
        for r in done
        if isinstance(r["end_km"], int) and isinstance(r["start_km"], int)
    )
    top = Counter(r["destination"] for r in rows).most_common(3)
    top_txt = "\n".join(f" - {name} ({n}x)" for name, n in top)
    return (
        f"Laporan Kendaraan ({period})\n"
        f"Total perjalanan: {len(rows)}\n"
        f"Selesai: {len(done)} | Sedang Berjalan: {len(active)}\n"
        f"Total jarak (selesai): {total_km} km\n"
        f"Tujuan terbanyak:\n{top_txt}"
    )

def get_status_summary() -> str:
    db = firestore.client()
    available, maintenance, in_use = [], [], []
    for d in db.collection("vehicles").stream():
        v = d.to_dict()
        label = f"{v.get('name', '?')} ({v.get('license_plate', '-')})"
        status = v.get("status")
        if status == "Available":
            available.append(label)
        elif status == "Maintenance":
            maintenance.append(label)
        elif status == "In Use":
            in_use.append((d.id, label))

    active_logs = {}
    for doc in db.collection("trip_logs").where(filter=FieldFilter("log_status", "==", "In Progress")).stream():
        x = doc.to_dict()
        active_logs[x.get("vehicle_id")] = x

    lines = ["Status Kendaraan Saat Ini", f"Tersedia ({len(available)})"]
    lines += [f" - {a}" for a in available] or [" -"]
    lines.append(f"Sedang dipakai ({len(in_use)}):")
    for vid, label in in_use:
        log = active_logs.get(vid, {})
        lines.append(f" - {label} | {log.get('driver_name', '-')} -> {log.get('destination', '-')}")
    if not in_use:
        lines.append(" -")
    lines.append(f"Maintenance ({len(maintenance)}):")
    lines += [f" - {m}" for m in maintenance] or [" -"]
    return "\n".join(lines)