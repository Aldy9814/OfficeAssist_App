import os
import json
import time
import traceback
from datetime import date
from typing import Optional

from sqlalchemy import create_engine ,text

from services import vehicle_service
from services.intent import parse_intent
from services.wa_client import normalize_phone
from services.settings import is_bot_enabled

_engine = None

HELP_TEXT = (
    "Halo! Saya adalah OfficeAssist. Contoh perintah:\n"
    "- laporan kendaraan minggu ini\n"
    "- rekap mobil bulan lalu\n"
    "- status kendaraan hari ini\n"
    "- siapa yang pakai mobil L 2222 TS hari ini\n"
    "- perjalanan Pak Anton minggu ini"
)

BOT_OFF_TEXT = "OfficeAssist sedang dinonaktifkan sementara. Silakan coba lagi nanti."

class RecordingClient:
    def __init__(self, inner):
        self.inner = inner
        self. texts = []
        self.files = []

    def send_text(self, to: str, text: str) -> None:
        self.texts.append(text)
        self.inner.send_text(to, text)

    def send_file(self, to: str, path: str, caption: str = "") -> None:
        self.files.append(os.path.basename(path))
        self.inner.send_file(to, path,  caption)

def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(os.getenv("DATABASE_URL"), pool_pre_ping=True, pool_recycle=1800)
    return _engine

def find_employee(phone: str):
    if os.getenv("DEV_ALLOW_ALL", "false").lower() == "true":
        return {"full_name": "Dev user", "division": "-", "role": "dev"}

    variants = {phone}
    if phone.startswith("62"):
        variants.add("0" + phone[2:])
    params = {f"v{i}": v for i, v in enumerate(variants)}
    placeholders = ", ".join(f":{k}" for k in params)
    with _get_engine().connect() as conn:
        row = conn.execute(
            text(f"SELECT full_name, division, role FROM employees WHERE whatsapp_number IN ({placeholders}) LIMIT 1"),
            params,
        ).fetchone()
    return dict(row._mapping) if row else None

def write_audit(phone: str, message: str, intent: str, status: str, response_message=None, response_file=None, parsed_params=None) -> None:
    try:
        with _get_engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_logs (whatsapp_number, incoming_message, detected_intent, "
                    "response_status, response_message, response_file, parsed_params) "
                    "VALUES (:wa, :msg, :intent, :status, :resp, :file, :params)"
                ),
                {"wa": phone, "msg": message, "intent": intent, "status": status,
                 "resp": response_message, "file": response_file, "params": parsed_params},
            )

    except Exception as e:
        print(f"[audit] gagal menulis log: {e}")

def handle_message(sender: str, message: str, client, meta: Optional[dict] = None) -> None:
    phone = normalize_phone(sender)
    client = RecordingClient(client)
    intent, status, parsed = "lainnya", "sukses", None
    timings = {}
    t_start = time.perf_counter()
    try:
        t_auth = time.perf_counter()
        if not is_bot_enabled():
            intent = "bot_nonaktif"
            client.send_text(phone, BOT_OFF_TEXT)
            return
        employee = find_employee(phone)
        timings["auth_ms"] = int((time.perf_counter() - t_auth) * 1000)
        if not employee:
            intent, status = "tidak_terdaftar", "gagal"
            client.send_text(phone, "Maaf, nomor anda belum terdaftar. Hubungi HR untuk pendaftaran")
            return

        t_intent = time.perf_counter()
        parsed = parse_intent(message)
        timings["intent_ms"] = int((time.perf_counter()-t_intent) * 1000)
        intent = parsed["intent"]

        if intent == "laporan_kendaraan":
            start = date.fromisoformat(parsed["start_date"])
            end = date.fromisoformat(parsed["end_date"])
            client.send_text(phone, "Baik, laporan sedang disiapkan")
            rows = vehicle_service.fetch_trips(start, end, parsed.get("keyword"), parsed.get("person"))
            summary = vehicle_service.format_summary(rows, start, end)
            client.send_text(phone, summary)
            if rows:
                path = vehicle_service.build_excel(rows, start, end)
                client.send_file(phone, path, caption="Laporan kendaraan (Excel)")
        elif intent == "pemakaian_kendaraan":
            start = date.fromisoformat(parsed["start_date"])
            end = date.fromisoformat(parsed["end_date"])
            rows = vehicle_service.fetch_trips(start, end, parsed.get("keyword"), parsed.get("person"))
            client.send_text(phone, vehicle_service.format_usage(rows, start, end))
            if len(rows) > vehicle_service.USAGE_MAX_ROWS:
                path = vehicle_service.build_excel(rows, start, end)
                client.send_file(phone, path, caption="Detail pemakaian kendaraan (Excel)")
        elif intent == "status_kendaraan":
            client.send_text(phone, vehicle_service.get_status_summary())
        else:
            client.send_text(phone, HELP_TEXT)

    except Exception:
        status = "gagal"
        traceback.print_exc()
        try: 
            client.send_text(phone, "Maaf terjadi kesalahan saat memproses permintaan Anda")
        except Exception:
            pass

    finally:
        t_audit = time.perf_counter()
        write_audit(
                    phone, message, intent, status,
                    response_message="\n\n".join(client.texts) or None,
                    response_file=", ".join(client.files) or None,
                    parsed_params=json.dumps(parsed, ensure_ascii=False) if parsed else None
                )
        timings["audit_ms"] = int((time.perf_counter() - t_audit) * 1000)
        timings["total_ms"] = int((time.perf_counter() - t_start) * 1000)
        timings["rest_ms"] = timings["total_ms"] - timings.get("intent_ms", 0)
        print(f"[timing] intent={timings.get('intent_ms', '-')}ms auth={timings.get('auth_ms', '-')}ms " 
              f"audit={timings['audit_ms']}ms total={timings['total_ms']}ms ({intent})")
        if meta is not None:
            meta.update(intent=intent, status=status, parsed=parsed, timings=timings)
        