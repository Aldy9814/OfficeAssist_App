from datetime import date

import services.dispatcher as d
import services.vehicle_service as vs
from services.intent import parse_rule_based
from services.wa_client import ConsoleClient

TODAY = date(2026, 11, 18)

def row(**kw):
    base = {
        "log_id": "a1", 
        "vehicle_name": "Test Innova", 
        "license_plate": "L 2222 TS",
        "driver_name": "Pak Budi",
        "passengers": "Siti Test (90001)",
        "passenger_names": "Siti Test",
        "destination": "Bandara Juanda",
        "checkout_time": "2026-11-17 08:15:00",
        "checkin_time": "-",
        "start_km": 100,
        "end_km": None,
        "status": "In Progress"
    }
    base.update(kw)
    return base

def test_usage_intent_variants():
    r = parse_rule_based("siapa yang pakai mobil hari ini", TODAY)
    assert r["intent"] == "pemakaian_kendaraan"
    assert (r["start_date"], r["end_date"]) == ("2026-11-18", "2026-11-18")

    r = parse_rule_based("siapa saja yang pakai L 2222 TS minggu ini", TODAY)
    assert r["intent"] == "pemakaian_kendaraan" and r["keyword"] == "L2222TS"

    r = parse_rule_based("perjalanan Pak Anton minggu ini", TODAY)
    assert r["intent"] == "pemakaian_kendaraan" and r["person"] == "Anton"

def test_laporan_penggunaan_is_a_report_not_usage():
    r = parse_rule_based("tolong kirim laporan penggunaan kendaraan minggu ini", TODAY)
    assert r["intent"] == "laporan_kendaraan"

def test_existing_intents_unchanged():
    assert parse_rule_based("laporan kendaraan minggu ini", TODAY)["intent"] == "laporan_kendaraan"
    assert parse_rule_based("status kendaraan", TODAY)["intent"] == "status_kendaraan"
    assert parse_rule_based("mobil yang sedang dipakai", TODAY)["intent"] == "status_kendaraan"
    assert parse_rule_based("tempat makan deket kantor dimana", TODAY)["intent"] == "lainnya"
    r = parse_rule_based("laporan perjalanan Pak Anton bulan ini", TODAY)
    assert r["intent"] == "laporan_kendaraan" and r["person"] == "Anton"

def test_row_matches_keyword_and_person():
    r  = row()
    assert vs._row_matches(r, keyword="L2222TS")
    assert not vs._row_matches(r, keyword="B9999XX")
    assert vs._row_matches(r, person="budi")
    assert vs._row_matches(r, person="Siti")
    assert not vs._row_matches(r, person="Anton")
    assert not vs._row_matches(r, person="90001")
    assert vs._row_matches(r, keyword="L2222TS", person="Siti")

def test_format_usage_content_and_privacy():
    text = vs.format_usage([row()], date(2026, 11, 18), date(2026, 11, 18))
    assert "Driver: Pak Budi" in text and "Penumpang: Siti Test" in text
    assert "Bandara Juanda" in text and "sedang berjalan" in text
    assert "17/11 08:15" in text
    assert "90001" not in text

def test_format_usage_truncates_and_empty():
    rows = [row(log_id=str(i)) for i in range(13)]
    text = vs.format_usage(rows, date(2026, 11, 1), date(2026, 11, 18), max_rows=10)
    assert text.count("Driver:") == 10 and "dan 3 perjalanan lain" in text
    assert "Tidak ada perjalanan" in vs.format_usage([], date(2026, 11, 18), date(2026, 11, 18))

def test_dispatch_usage_sends_text_and_file_when_long(monkeypatch, tmp_path):
    monkeypatch.setattr(d, "find_employee", lambda p: {"full_name": "Budi"})
    monkeypatch.setattr(d, "write_audit", lambda *a, **k: None)
    monkeypatch.setattr(d, "parse_intent", lambda t:{
        "intent": "pemakaian_kendaraan",
        "start_date": "2026-11-18",
        "end_date": "2026-11-18",
        "keyword": None,
        "person": None
    })
    monkeypatch.setattr(d.vehicle_service, "build_excel", lambda r, s, e: str(tmp_path / "x.xlsx"))

    monkeypatch.setattr(d.vehicle_service, "fetch_trips", lambda *a ,**k: [row()])
    client = ConsoleClient()
    d.handle_message("6281234567890@c.us", "siapa yang pakai mobil", client)
    assert [m["type"] for m in client.sent] == ["text"] and "Pemakaian Kendaraan" in client.sent[0]["text"]

    monkeypatch.setattr(d.vehicle_service, "fetch_trips", lambda *a, **k: [row() for _ in range(12)])
    client = ConsoleClient()
    d.handle_message("6281234567890@c.us", "siapa yang pakai mobil", client)
    assert [m["type"] for m in client.sent] == ["text", "file"]