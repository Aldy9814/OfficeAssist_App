import os
import time
from urllib.parse import quote

from services import vehicle_service
from services.broadcast_service import clean_phone
from services.dispatcher import handle_message
from services.wa_client import ConsoleClient

MAX_LEN = 500
REPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

class ChatError(ValueError):
    """Masukan tidak valid (akan dijadikan HTTP 400)."""

def run_chat(sender, text, handler=handle_message) -> dict:
    text = (text or "").strip()
    if not text:
        raise ChatError("Pesan kosong")
    if len(text) > MAX_LEN:
        raise ChatError(f"Pesan terlalu panjang (maksimal {MAX_LEN} karakter)")
    phone = clean_phone(sender)
    if not phone:
        raise ChatError("Nomor pengiriman kosong")

    client = ConsoleClient()
    meta = {}
    t0 = time.perf_counter()
    handler(phone, text, client, meta=meta)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    replies = []
    for m in client.sent:
        if m["type"] == "text":
            replies.append({"type": "text", "text": m["text"]})
        else:
            name = os.path.basename(m["path"])
            replies.append({
                "type": "file", 
                "filename": name, 
                "caption": m.get("caption", ""), 
                "url": f"/api/chat/file/{quote(name)}"
            })
    return {
        "replies": replies,
        "meta": {
            "intent": meta.get("intent"),
            "status": meta.get("status"),
            "parsed": meta.get("parsed"),
            "timings": meta.get("timings"),
            "duration_ms": duration_ms
        },
    }

def resolve_report_file(filename):
    safe = os.path.basename(filename or "")
    if not safe or safe != filename or not safe.lower().endswith(".xlsx"):
        return None
    path = os.path.join(vehicle_service.REPORT_DIR, safe)
    return path if os.path.isfile(path) else None