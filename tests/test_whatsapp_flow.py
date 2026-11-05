from datetime import date

import services.dispatcher as d
from services.intent import parse_rule_based
from services.wa_client import ConsoleClient, parse_incoming

TODAY = date(2026, 11, 4)

def test_report_this_week():
    r = parse_rule_based("laporan kendaraan minggu ini", TODAY)
    assert r["intent"] == "laporan_kendaraan"
    assert (r["start_date"], r["end_date"]) == ("2026-11-02", "2026-11-04")

def test_report_last_week_and_last_month():
    r = parse_rule_based("rekap mobil minggu lalu", TODAY)
    assert (r["start_date"], r["end_date"]) == ("2026-10-26", "2026-11-01")
    r = parse_rule_based("laporan kendaraan bulan lalu", TODAY)
    assert (r["start_date"], r["end_date"]) == ("2026-10-01", "2026-10-31")

def test_status_and_plate_keyword():
    assert parse_rule_based("status kendaraan hari ini", TODAY)["intent"] == "status_kendaraan"
    assert parse_rule_based("laporan mobil B 1234 XX bulan ini", TODAY)["keyword"] == "B1234XX"

def test_unkown_message():
    assert parse_rule_based("sdalkjsalkjdvlaiueh", TODAY)["intent"] == "lainnya"

def test_parse_green_api_payloads():
    base = {
        "typeWebhook": "incomingMessageReceived",
        "senderData": {"chatId": "6281234567890@c.us", "sender": "6281234567890@c.us"}
    }
    plain = {
        **base, 
        "messageData": {"typeMessage": "textMessage", 
        "textMessageData": {"textMessage": "halo"}}
    }
    ext = {
        **base, 
        "messageData": {
            "typeMessage": "extendedTextMessage", 
            "extendedTextMessageData": {"text": "cek https://x.id"}
        }
    }
    assert parse_incoming(plain) == ("6281234567890@c.us", "halo")
    assert parse_incoming(ext)[1] == "cek https://x.id"
    assert parse_incoming({"typeWebhook": "outgoingMessageStatus"}) is None

def test_dispatch_report_sends_summary_and_file(monkeypatch, tmp_path):
    rows = [
        {
            "log_id": "a1", "vehicle_name": "Avanza", "license_plate": "L 1 AP", "driver_name": "Budi",
            "passengers": "-", "destination": "Bandara", "checkout_time": "2026-11-03 08:00:00",
            "checkin_time": "2026-11-03 10:00:00", "start_km": 100, "end_km": 150, "status": "Completed"
        }
    ]

    monkeypatch.setattr(d, "find_employee", lambda p: {"full_name": "Budi"})
    monkeypatch.setattr(d, "parse_intent", lambda t: {"intent": "laporan_kendaraan", "start_date": "2026-11-01","end_date": "2026-11-04", "keyword": None})
    monkeypatch.setattr(d.vehicle_service, "fetch_trips", lambda s, e, k=None: rows)
    monkeypatch.setattr(d.vehicle_service, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(d, "write_audit", lambda *a, **k: None)

    client = ConsoleClient()
    d.handle_message("6281234567890@c.us", "laoran kendaraan", client)
    kinds = [m["type"] for m in client.sent]
    assert "file" in kinds and kinds.count("text") >= 2

def test_unregistered_number_is_rejected(monkeypatch):
    monkeypatch.setattr(d, "find_employee", lambda p: None)
    monkeypatch.setattr(d, "write_audit", lambda *a, **k: None)
    client = ConsoleClient()
    d.handle_message("6280000000000@c.us", "laporan kendaraan", client)
    assert "belum terdaftar" in client.sent[0]["text"]

def test_default_period_is_today():
    r = parse_rule_based("laporan kendaraan", TODAY)
    assert (r["start_date"], r["end_date"]) == ("2026-11-04", "2026-11-04")

def test_this_month_still_works():
    r = parse_rule_based("laporan kendaraan bulan ini", TODAY)
    assert (r["start_date"], r["end_date"]) == ("2026-11-01", "2026-11-04")
    