import json

import services.broadcast_service as bs
from services.wa_client import ConsoleClient

EMPLOYEES = [
    {"employee_id": "EMP-001", "full_name": "Budi Santoso", "whatsapp_number": "6281111111111", "division": "IT"},
    {"employee_id": "EMP-002", "full_name": "Siti Aminah", "whatsapp_number": "0812-2222-222", "division": "HR"},
    {"employee_id": "EMP-003", "full_name": "Candra", "whatsapp_number": "", "division": "IT"},
]

def make(**kw):
    base = {
        "id": 1,
        "scheduled_time": "2026-11-10 09:00:00",
        "message": "Halo semua",
        "attachment_type": "teks",
        "file_path": "",
        "target_audience": "ALL",
        "status": "pending"
    }
    base.update(kw)
    return base

def ids(recipients):
    return [e["employee_id"] for e in recipients]

def test_clean_phone():
    assert bs.clean_phone("0812-2222-222") == "628122222222"
    assert bs.clean_phone("+62 811 1111 1111") == "6281111111111"
    assert bs.clean_phone(None) == ""

def test_resolve_all_division_ids_and_unmatched():
    assert len(bs.resolve_recipients("ALL", EMPLOYEES)[0]) == 3
    assert ids(bs.resolve_recipients("IT", EMPLOYEES)[0]) == ["EMP-001", "EMP-003"]
    assert ids(bs.resolve_recipients("EMP-001, EMP-002", EMPLOYEES)[0]) == ["EMP-001", "EMP-002"]
    assert ids(bs.resolve_recipients('["EMP-002"]', EMPLOYEES)[0]) == ["EMP-002"]
    rec, unmatched = bs.resolve_recipients("IT, Keuangan", EMPLOYEES)
    assert ids(rec) == ["EMP-001", "EMP-003"] and unmatched == ["Keuangan"]

def test_dry_run_sends_nothing():
    client = ConsoleClient()
    r = bs.process_broadcast(make(), EMPLOYEES,  client, dry_run=True)
    assert client.sent == []
    assert r["ok"] == 2 and r["failed"] == 1
    assert r["recipients"][2]["result"].startswith("skipped")

def test_real_send_text_normalizes_numbers(monkeypatch):
    calls = []
    monkeypatch.setattr(bs, "_set_status", lambda i, s: calls.append((i, s)))
    client = ConsoleClient()
    r = bs.process_broadcast(make(), EMPLOYEES, client, dry_run=False, update_status=True)
    assert [m["to"] for m in client.sent] == ["6281111111111", "628122222222"]
    assert r["status_after"] == "sukses" and calls == [(1, "sukses")]

def test_send_with_file(tmp_path):
    f = tmp_path / "pengumuman.pdf"
    f.write_bytes(b"%PDF-1.4")
    client = ConsoleClient()
    bs.process_broadcast(make(
        attachment_type="pdf",
        file_path=str(f),
        target_audience="HR"
    ), EMPLOYEES, client, dry_run=False)
    assert client.sent[0]["type"] == "file" and client.sent[0]["caption"] == "Halo semua"

def test_missing_file_blocks_sending(monkeypatch):
    monkeypatch.setattr(bs, "_set_status", lambda i, s: None)
    client = ConsoleClient()
    r = bs.process_broadcast(make(
        attachment_type="pdf",
        file_path="tidak_ada.pdf"
    ), EMPLOYEES, client, dry_run=False, update_status=True)
    assert client.sent == [] and r["status_after"] == "gagal"

def test_no_recipients_marks_failed(monkeypatch):
    calls = []
    monkeypatch.setattr(bs, "_set_status", lambda i, s: calls.append((i, s)))
    r = bs.process_broadcast(make(
        target_audience="Keuangan"
    ), EMPLOYEES, ConsoleClient(), dry_run=False, update_status=True)
    assert r["ok"] == 0 and calls == [(1, "gagal")]

def tgt(type_, *values):
    return json.dumps({"type": type_, "values": list(values)})

def test_form_format_targets():
    assert len(bs.resolve_recipients(tgt("all"), EMPLOYEES)[0]) == 3
    assert ids(bs.resolve_recipients(tgt("divisions", "IT"), EMPLOYEES)[0]) == ["EMP-001", "EMP-003"]
    assert ids(bs.resolve_recipients(tgt("employees", "EMP-002"), EMPLOYEES)[0]) == ["EMP-002"]
    rec, unmatched = bs.resolve_recipients(tgt("divisions", "IT", "Keuangan"),EMPLOYEES)
    assert ids(rec) == ["EMP-001", "EMP-003"] and unmatched == ["Keuangan"]
    assert bs.resolve_recipients(tgt("divisions"), EMPLOYEES) == ([], [])

def test_form_format_end_to_end():
    client = ConsoleClient()
    r = bs.process_broadcast(make(
        target_audience=tgt("divisions", "HR")
    ), EMPLOYEES, client, dry_run=False)
    assert [m["to"] for m in client.sent] == ["628122222222"] and r["ok"] == 1