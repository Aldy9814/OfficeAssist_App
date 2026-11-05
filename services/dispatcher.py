import os
import json
import traceback
from datetime import date

from sqlalchemy import create_engine ,text

from services import vehicle_service
from services.intent import parse_intent
from services.wa_client import normalize_phone

_engine = None

HELP_TEXT = (
    "Halo! Saya adalah OfficeAssist. Contoh perintah:\n"
    "- laporan kendaraan minggu ini\n"
    "- rekap mobil bulan lalu\n"
    "- status kendaraan hari ini"
)

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
        _engine = create_engine(os.getenv("DATABASE_URL"))
    return _engine

def find_employee(phone: str):
    if os.getenv("DEV_ALLOW_ALL", "false").lower() == "true":
        return {"full_name": "Dev user", "division": "-", "role": "dev"}

    variants = {phone, f"{phone}"}
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

def handle_message(sender: str, message: str, client) -> None:
    phone = normalize_phone(sender)
    client = RecordingClient(client)
    intent, status, parsed = "lainnya", "sukses", None
    try:
        employee = find_employee(phone)
        if not employee:
            intent, status = "tidak_terdaftar", "gagal"
            client.send_text(phone, "Maaf, nomor anda belum terdaftar. Hubungi HR untuk pendaftaran")
            return

        parsed = parse_intent(message)
        intent = parsed["intent"]

        if intent == "laporan_kendaraan":
            start = date.fromisoformat(parsed["start_date"])
            end = date.fromisoformat(parsed["end_date"])
            client.send_text(phone, "Baik, laporan sedang disiapkan")
            rows = vehicle_service.fetch_trips(start, end, parsed.get("keyword"))
            summary = vehicle_service.format_summary(rows, start, end)
            client.send_text(phone, summary)
            if rows:
                path = vehicle_service.build_excel(rows, start, end)
                client.send_file(phone, path, caption="Laporan kendaraan (Excel)")
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
        write_audit(
            phone, message, intent, status,
            response_message="\n\n".join(client.texts) or None,
            response_file=", ".join(client.files) or None,
            parsed_params=json.dumps(parsed, ensure_ascii=False) if parsed else None
        )