from datetime import date

import pytest

import services.intent as it

TODAY = date(2026, 11, 25) # Rabu

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("INTENT_ENGINE", "hybrid")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setenv(it, "_gemini_down_until", 0.0)

def _boom(*a, **k):
    raise AssertionError("Gemini tidak boleh dipanggil untuk pesan sederhana")

@pytest.mark.parametrize("text,intent",[
    ("status kendaraan", "status_kendaraan"),
    ("lapopran kendaraan minggu lalu", "laporan_kendaraan"),
    ("siapa yang pakai mobil hari ini", "pemakaian_kendaraan"),
    ("rekap mobil bulan lalu", "laporan_kendaraan"),
    ("halo", "lainnya"),
])
def test_simple_message_skip_llm(monkeypatch, text, intent):
    monkeypatch.setattr(it, "parse_with_gemini", _boom)
    r = it.parse_intent(text, TODAY)
    assert r["intent"] == intent and r["engine"] == "rules"

def test_unparsed_date_goes_to_llm(monkeypatch):
    fake = {
        "intent": "laporan_kendaraan",
        "start_date": "2026-11-10",
        "end_date": "2026-11-10",
        "keyword": None,
        "person": None
    }
    monkeypatch.setattr(it, "parse_with_gemini", lambda t, today: dict(fake))
    r = it.parse_intent("laporan mobil tanggal 10 november", TODAY)
    assert r["engine"] == "gemini" and r["start_date"] == "2026-11-10"

def test_llm_failure_falls_back_and_cools_down(monkeypatch):
    calls = []

    def fail(tm, today):
        calls.append(t)
        raise TimeoutError("lambat")

    monkeypatch.setattr(it, "parse_with_gemini", fail)
    r1 = it.parse_intent("laporan mobil tanggal 10 november", TODAY)
    r2 = it.parse_intent("laporan mobil tanggal 11 november", TODAY)
    assert r1["engine"] == r2["engine"] == "rules-fallback"
    assert len(calls) == 1

def test_date_and_plate_are_not_confused():
    assert it._extract_keyword("status mobil di 10 mei") is None
    assert it._extract_keyword("laporan ke 2 jam") is None
    assert it._extract_keyword("siapa pakai b 1234 xyz") == "B1234XYZ"
    