import os

import services.dispatcher as d
from services.intent import parse_intent
from services.wa_client import ConsoleClient

def test_dispatcher_records_timings(monkeypatch):
    monkeypatch.setattr(d, "write_audit", lambda *a, **k: None)
    monkeypatch.setattr(d, "find_employee", lambda p: {"full_name": "Budi"})
    monkeypatch.setattr(d, "parse_intent", lambda t: {"intent": "lainnya", "start_date": "2026-11-18", "end_date": "2026-11-18", "keyword": None, "person": None})
    meta = {}
    d.handle_message("6281234567890", "halo", ConsoleClient(), meta=meta)
    t = meta["timings"]
    assert {"intent_ms", "rest_ms", "total_ms"} <= set(t)
    assert t["total_ms"] >= t["intent_ms"] >= 0

def test_parse_intent_marks_engine(monkeypatch):
    monkeypatch.setenv("INTENT_ENGINE", "rules")
    assert parse_intent("status kendaraan")["engine"] == "rules"

    monkeypatch.setenv("INTENT_ENGINE", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "palsu")
    monkeypatch.setenv("services.intent.parse_with_gemini", lambda text, today: {
        "intent": "lainnya",
        "start_date": "2026-11-18",
        "end_date": "2026-11-18",
        "keyword": None,
        "person": None
    })
    assert parse_intent("halo")["engine"] == "gemini"

    def gagal(text, today):
        raise RuntimeError("timeout")
    monkeypatch.setattr("services.intent.parse_with_gemini", gagal)
    assert parse_intent("status kendaraan")["engine"] == "rules"