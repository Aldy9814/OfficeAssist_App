import os
import json
import re
import time
import logging
from datetime import datetime
from typing import List, Optional, Tuple

from services.wa_client import ConsoleClient

log = logging.getLogger("broadcast")
_engine = None

ALL_KEYWORDS = {"all", "semua", "semua karyawan", "all employees", "*"}
PREFIXES = ("divisi:", "division:", "div:", "karyawan:", "employee:")

def _get_engine():
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine
        _engine = create_engine(os.getenv("DATABASE_URL"))
    return _engine

def clean_phone(raw) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits

def _tokens(target) -> List[str]:
    t = (target or "").strip()
    if not t:
        return []
    if t.startswith("["):
        try:
            data = json.loads(t)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except ValueError:
            pass
    return [x.strip() for x in re.split(r"[,;\n]",t) if x.strip()]

def _parse_form_target(target):
    t = (target or "").strip()
    if not t.startswith("{"):
        return None
    try:
        data = json.loads(t)
    except ValueError:
        return None
    if not isinstance(data, dict) or "type" not in data:
        return None
    values = data.get("values") or []
    return str(data["type"]).lower(), [str(v).strip() for v in values if str(v).strip()]

def resolve_recipients(target, employees: List[dict]) -> Tuple[List[dict], List[str]]:
    form = _parse_form_target(target)
    if form is not None:
        ttype, values = form
        if ttype == "all":
            return list(employees), []
        if ttype not in ("divisions", "employees"):
            return [], [f"type tidak dikenal: {ttype}"]
        field = "division" if ttype == "divisions" else "employee_id"
        matched, seen, unmatched = [], set(), []
        for v in values:
            hits = [e for e in employees if str(e.get(field, "")).strip().lower() == v.lower()]
            if not hits:
                unmatched.append(v)
            for e in hits:
                if e.get("employee_id") not in seen:
                    seen.add(e.get("employee_id"))
                    matched.append(e)
        return matched, unmatched
    tokens = _tokens(target)
    if not tokens:
        return [], []
    if any(tok.lower() in ALL_KEYWORDS for tok in tokens):
        return list(employees), []

    matched, seen, unmatched = [], set(), []
    for tok in tokens:
        key = tok.lower()
        for p in PREFIXES:
            if key.startswith(p):
                key = key[len(p):].strip()
        hits = [
            e for e in employees
            if key in (str(e.get("employee_id", "")).lower(),
                       str(e.get("full_name", "")).lower(),
                       str(e.get("division", "")).lower())
        ]
        if not hits:
            unmatched.append(tok)
            continue
        for e in hits:
            if e.get("employee_id") not in seen:
                seen.add(e.get("employee_id"))
                matched.append(e)
    return matched, unmatched

def _set_status(broadcast_id: int, status: str) -> None:
    from sqlalchemy import text
    with _get_engine().begin() as conn:
        conn.execute(text("UPDATE broadcast_schedules SET status = :s WHERE id = :id"),
                     {"s": status, "id": broadcast_id})

def process_broadcast(b: dict, employees: List[dict], client, dry_run: bool = True,
                      update_status: bool = False, delay: float = 0.0) -> dict:
    recipients, unmatched = resolve_recipients(b.get("target_audience"), employees)
    message = b.get("message") or ""
    atype = (b.get("attachment_type") or "teks").lower()
    path = b.get("file_path") or ""
    use_file = atype != "teks" and bool(path)

    notes = []
    if atype != "teks" and not path:
        notes.append(f"attachment_type '{atype}' tapi file_path kosong; dikirim sebagai teks")
    file_error = f"file tidak ditemukan: {path}" if use_file and not os.path.exists(path) else None
    if file_error:
        notes.append(file_error)
    if unmatched:
        notes.append(f"target tidak cocok: {', '.join(unmatched)}")
    if not recipients:
        notes.append("target tidak cocok dengan karyawan mana pun")
    if not message.strip() and not use_file:
        notes.append("pesan kosong")

    results, ok, failed = [], 0, 0
    for i, emp in enumerate(recipients):
        phone = clean_phone(emp.get("whatsapp_number"))
        row = {"employee_id": emp.get("employee_id"), "name": emp.get("full_name"), "phone": phone}
        if not phone:
            row["result"] = "skipped: nomor kosong"
            failed += 1
        elif file_error:
            row["result"] = ("would_fail: " if dry_run else "failed: ") + file_error
            failed += 1
        elif dry_run:
            row["result"] = "would_send"
            ok += 1
        else:
            try:
                if use_file:
                    client.send_file(phone, path, caption=message)
                else:
                    client.send_text(phone, message)
                row["result"] = "sent"
                ok += 1
            except Exception as e:
                row["result"] = f"failed: {e}"
                failed += 1
            if delay and  i < len(recipients) - 1:
                time.sleep(delay)
        results.append(row)

    status_after = None
    if not dry_run and update_status:
        status_after = "sukses" if ok > 0 else "gagal"
        try:
            _set_status(b["id"], status_after)
        except Exception as e:
            notes.append(f"gagal update status: {e}")
            status_after = None

    return {
        "id": b.get("id"),
        "scheduled_time": str(b.get("scheduled_time")),
        "status_before": b.get("status"),
        "status_after": status_after,
        "attachment_type": atype,
        "target_audience": b.get("target_audience"),
        "message": message,
        "ok": ok,
        "failed": failed,
        "recipients": results,
        "notes": notes,
    }

def run_due(client, dry_run: bool = True, broadcast_id: Optional[int] = None, only_due: bool = True,
            update_status: bool = True, force: bool = False) -> List[dict]:
    from sqlalchemy import text
    with _get_engine().connect() as conn:
        if broadcast_id is not None:
            rows = conn.execute(text(
                "SELECT * FROM broadcast_schedules WHERE id = :id"
            ),{"id": broadcast_id}).fetchall()
        else:
            q = "SELECT * FROM broadcast_schedules WHERE status = 'pending'"
            params = {}
            if only_due:
                q += " AND scheduled_time <= :now"
                params["now"] = datetime.now()
            rows = conn.execute(text(
                q + " ORDER BY scheduled_time ASC"
            ), params).fetchall()
        employees = [dict(r._mapping) for r in conn.execute(text(
            "SELECT employee_id, full_name, whatsapp_number, division FROM employees"
        )).fetchall()]

    if broadcast_id is not None and not rows:
        return [{"id": broadcast_id, "skipped": "broadcast tidak ditemukan"}]

    delay = 0.0 if isinstance(client, ConsoleClient) else float(os.getenv("BROADCAST_DELAY_SECONDS", "2"))
    results = []
    for r in rows:
        b = dict(r._mapping)
        if not dry_run and update_status and str(b.get("status")).lower() != "pending" and not force:
            results.append({
                "id": b.get("id"),
                "skipped": f"status '{b.get('status')}' bukan pending (pakai force=true untuk kirim ulang)"
            })
            continue
        results.append(process_broadcast(b, employees, client, dry_run, update_status, delay))
    return results
        
