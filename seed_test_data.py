import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

from services.intent import resolve_period

load_dotenv()
if not firebase_admin._apps:
    firebase_admin.initialize_app(
        credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "ServiceAccountKey.json"))
    )
db = firestore.client()

VEHICLES = {
    "TEST-V1": {"name": "Test Avanza", "license_plate": "L 1111 TS", "status": "Available", "current_km": 10000},
    "TEST-V2": {"name": "Test Innova", "license_plate": "L 2222 TS", "status": "In Use", "current_km": 20000},
    "TEST-V3": {"name": "Test Xenia", "license_plate": "L 3333 TS", "status": "Maintenance", "current_km": 30000},
}

PAX = [{"name": "Siti Test", "nik": "90001"}, {"name": "Dewi Test", "nik": "90002"}]

TRIPS = [
    (0, 8, "TEST-V2", "Pak Budi", "Bandara Juanda", PAX[:1], "In Progress", None),
    (1, 9, "TEST-V1", "Pak Anton", "Agrinisia", PAX, "Completed", 45),
    (2, 13, "TEST-V1", "Pak Candra", "Kantor Pusat", [], "Completed", 30),
    (5, 10, "TEST-V2", "Pak Budi", "Bandara Juanda", PAX[:1], "Completed", 60),
    (9, 14, "TEST-V1", "Pak Anton", "Tanjung Perak", [], "Completed", 25),
    (20, 8, "TEST-V2", "Pak Candra", "Agrinisia", PAX, "Completed", 80),
    (40, 11, "TEST-V1", "Pak Budi", "Bandara Juanda", PAX[1:], "Completed", 55),
]

def clean():
    n = 0
    for d in db.collection("vehicles").stream():
        if d.id.startswith("TEST-"):
            d.reference.delete(); n += 1
    for d in db.collection("trip_logs").stream():
        if d.id.startswith("seed-"):
            d.reference.delete(); n += 1
    print(f"Deleted {n} test documents.")

def seed():
    today = date.today()
    for vid, data in VEHICLES.items():
        db.collection("vehicles").document(vid).set(data)

    dates = []
    for i, (ago, hour, vid, driver, dest, pax, status, km) in enumerate(TRIPS, start=1):
        out = datetime.combine(today - timedelta(days=ago), datetime.min.time()).replace(hour=hour)
        start_km = VEHICLES[vid]["current_km"] = i * 100
        log_id = f"seed-{i:03d}"
        db.collection("trip_logs").document(log_id).set({
            "log_id": log_id,
            "vehicle_id": vid,
            "driver_name": driver,
            "destination": dest,
            "passengers": pax,
            "checkout_time": out.strftime("%Y-%m-%d %H:%M:%S"),
            "checkin_time": None if status == "In Progress" else (out + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            "start_km": start_km,
            "end_km": None if km is None else start_km + km,
            "log_status": status,
        })
        dates.append(out.date())

        print(f"Seeded {len(VEHICLES)} vehicles and {len(TRIPS)} trips. \n")
        print("Expected trip counts for the bot (if you ask for each period):")
        for label, period in [
            ("hari ini", "today"),
            ("kemarin", "yesterday"),
            ("minggu ini", "this_week"),
            ("minggu lalu", "last_week"),
            ("bulan ini", "this_month"),
            ("bulan lalu", "last_month")
        ]:
            s, e = resolve_period(period, today)
            print(f" {label:<12} {s} .. {e} -> {sum(1 for d in dates if s <= d <= e)} trips")

if __name__ == "__main__":
    clean() if "--clean" in sys.argv else seed()

