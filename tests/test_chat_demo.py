import os
import pytest

import services.chat_demo as cd
import services.dispatcher as d
from services.wa_client import ConsoleClient

def fake_handler(phone, text, client, meta=None):
    fake_handler.calls.append((phone, text))
    client.send_text(phone, "Halo dari bot")
    client.send_file(phone, os.path.join("uploads", "reports", "Laporan_Kendaraan_2026-11-01_2026-11-18.xlsx"), caption="Laporan kendaraan (Excel)")
    meta.update(intent="laporan_kendaraan", status="sukses", parsed={"intent": "laporan_kendaraan"})

fake_handler.calls = []

def test_run_chat_converts_replies_and_meta():
    fake_handler.calls.clear()
    out = cd.run_chat("0812-3456-789", " laporan kendaraan ", handler=fake_handler)
    assert fake_handler.calls == [("62812345678" + "9", "laporan kendaraan")]
    assert [r["type"] for r in out["replies"]] == ["text", "file"]
    f = out["replies"][1]
    assert f["filename"] == "Laporan_Kendaraan_2026-11-01_2026-11-18.xlsx"
    assert f["url"] == "/api/chat/file/Laporan_Kendaraan_2026-11-01_2026-11-18.xlsx"
    assert out["meta"]["intent"] == "laporan_kendaraan" and out["meta"]["status"] == "sukses"
    assert isinstance(out["meta"]["duration_ms"], int)

def test_run_chat_rejects_bad_input():
    with pytest.raises(cd.ChatError):
        cd.run_chat("6281234567890", "   ", handler=fake_handler)
    with pytest.raises(cd.ChatError):
        cd.run_chat("6281234567890", "x" * 501, handler=fake_handler)
    with pytest.raises(cd.ChatError):
        cd.run_chat("", "halo", handler=fake_handler)

def test_resolve_report_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cd.vehicle_service, "REPORT_DIR", str(tmp_path))
    (tmp_path / "ok.xlsx").write_bytes(b"x")
    (tmp_path / "rahasia.txt").write_bytes(b"x")
    assert cd.resolve_report_file("ok.xlsx") == str(tmp_path / "ok.xlsx")
    assert cd.resolve_report_file("rahasia.txt") is None
    assert cd.resolve_report_file("../ok.xlsx") is None
    assert cd.resolve_report_file("tidak_ada.xlsx") is None
    assert cd.resolve_report_file("") is None

def test_dispatcher_fills_meta_normal_and_bot_off(monkeypatch):
    monkeypatch.setattr(d, "write_audit", lambda *a, **k: None)
    monkeypatch.setattr(d, "find_employee", lambda p: {"full_name": "Budi"})
    monkeypatch.setattr(d, "parse_intent", lambda t: {
        "intent": "lainnya", 
        "start_date": "2026-11-18", 
        "end_date": "2026-11-18",
        "keyword": None,
        "person": None
    })
    monkeypatch.setattr(d, "is_bot-enabled", lambda *a, **k: True)
    meta = {}
    d.handle_message("6281234567890", "halo", ConsoleClient(), meta=meta)
    assert meta["intent"] == "lainnya" and meta["status"] == "sukses" and meta["parsed"]["intent"] == "lainnya"
    monkeypatch.setattr(d, "is_bot_enabled", lambda *a, **k: False)
    meta = {}
    client = ConsoleClient()
    d.handle_message("6281234567890", "halo", client, meta=meta)
    assert meta["intent"] == "bot_nonaktif" and "dinonaktifkan"in client.sent[0]["text"]

def test_handle_message_still_works_without_meta(monkeypatch):
    monkeypatch.setattr(d, "write_audit", lambda *a, **k: None)
    monkeypatch.setattr(d, "find_employee", lambda p: None)
    client = ConsoleClient()
    d.handle_message("6280000000000", "halo", client)
    assert "belum terdaftar" in client.sent[0]["text"]