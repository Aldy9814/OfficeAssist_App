import services.dispatcher as d
import services.settings as st
from services.wa_client import ConsoleClient

def test_default_enabled_when_no_row(monkeypatch):
    monkeypatch.setattr(st, "_read_setting", lambda: None)
    assert st.is_bot_enabled(force=True) is True

def test_off_and_on_values(monkeypatch):
    for raw in ("off", "OFF", "false", "0"):
        monkeypatch.setattr(st, "_read_setting", lambda raw=raw: raw)
        assert st.is_bot_enabled(force=True) is False
    monkeypatch.setattr(st, "_read_setting", lambda: "on")
    assert st.is_bot_enabled(force=True) is True

def test_db_error_defaults_to_enabled(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(st, "_read_setting", boom)
    assert st.is_bot_enabled(force=True) is True

def test_set_updates_cache(monkeypatch):
    written = []
    monkeypatch.setattr(st, "_write_setting", lambda v: written.append(v))
    st.set_bot_enabled(False)
    assert written == ["off"] and st.is_bot_enabled() is False
    st.set_bot_enabled(True)
    assert written == ["off", "on"] and st.is_bot_enabled() is True

def test_dispatcher_replies_off_message_and_skips_everything(monkeypatch):
    audits = []

    def must_not_run(*a, **k):
        raise AssertionError("tidak boleh dijalankan saat bot nonaktif")

    monkeypatch.setattr(d, "is_bot_enabled", lambda: False)
    monkeypatch.setattr(d, "write_audit", lambda *a, **k: audits.append(a))
    monkeypatch.setattr(d, "find_employee", must_not_run)
    monkeypatch.setattr(d, "parse_intent", must_not_run)
    client = ConsoleClient()
    d.handle_message("6281234567890@c.us", "status kendaraan", client)
    assert len(client.sent) == 1 and "dinonaktifkan" in client.sent[0]["text"]
    assert audits[0][2] == "bot_nonaktif"
