import os
import re
import json
import calendar
from datetime import date, timedelta
from typing import Optional

INTENTS = {"laporan_kendaraan", "status_kendaraan", "pemakaian_kendaraan", "lainnya"}

USAGE_WORDS = ("siapa", "pemakai", "pengguna", "yang pakai", "yang makai", "yang menggunakan", "yang bawa", "dipakai oleh", "dibawa oleh")
REPORT_WORDS = ("laporan", "rekap", "riwayat", "history")
PERSON_RE = re.compile(r"\b(?:pak|bu|bapak|ibu|mas|mbak|sdr|saudara)\s+([a-z]+)\b")

def _extract_person(t: str) -> Optional[str]:
    m = PERSON_RE.search(t)
    return m.group(1).title() if m else None

def resolve_period(period: str, today: date):
    monday = today - timedelta(days=today.weekday())
    if period == "today":
        return today, today
    elif period == "yesterday":
        d = today - timedelta(days=1)
        return d, d
    if period == "this_week":
        return monday, today
    elif period == "last_week":
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if period == "last_month":
        last_day_prev = today.replace(day=1) - timedelta(days=1)
        return last_day_prev.replace(day=1), last_day_prev

    return today.replace(day=1), today

def _extract_keyword(t: str) -> Optional[str]:
    m = re.search(r"\b([a-z]{1,2})\s?(\d{1,4})\s?([a-z]{1,3})\b", t)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}".upper() if m else None

def parse_rule_based(text: str, today: Optional[date] = None) -> dict:
    today = today or date.today()
    t = text.lower()
    vehicle_words = ("kendaraan", "mobil", "trip", "perjalanan")
    has_vehicle = any(w in t for w in vehicle_words)
    keyword = _extract_keyword(t)
    person = _extract_person(t)

    if any(w in t for w in USAGE_WORDS) and (has_vehicle or keyword):
        intent = "pemakaian_kendaraan"
    elif person and has_vehicle and not any(w in t for w in REPORT_WORDS):
        intent = "pemakaian_kendaraan"
    elif has_vehicle and any(w in t for w in REPORT_WORDS):
        intent = "laporan_kendaraan"
    elif has_vehicle and any(w in t for w in ("status", "tersedia", "available", "dipakai", "pakai")):
        intent = "status_kendaraan"
    else:
        intent = "lainnya"
 
    if "kemarin" in t:
        period = "yesterday"
    elif "minggu lalu" in t or "pekan lalu" in t:
        period = "last_week"
    elif "minggu ini" in t or "pekan ini" in t:
        period = "this_week"
    elif "bulan lalu" in t:
        period = "last_month"
    elif "bulan ini" in t:
        period = "this_month"
    elif "hari ini" in t:
        period = "today"
    else:
        period = "today"
 
    start, end = resolve_period(period, today)
    return {
        "intent": intent,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "keyword": _extract_keyword(t),
        "person": person,
    }

def parse_with_gemini(text: str,today: date) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = f"""Kamu adalah pengurai pesan untuk asisten kantor OfficeAssist (bahasa Indonesia).
Hari ini: {today.isoformat()} ({calendar.day_name[today.weekday()]}). Minggu dimulai hari Senin.
Pesan: "{text}"

Jika pesan tidak menyebut waktu sama sekali, pakai hari ini untuk start_date dan end_date.
 
Keluarkan JSON murni dengan field:
- "intent": "laporan_kendaraan" (minta rekap/laporan perjalanan kendaraan),
  "status_kendaraan" (tanya kendaraan tersedia/sedang dipakai sekarang),
  "pemakaian_kendaraan" (tanya SIAPA yang memakai/membawa kendaraan, atau perjalanan seseorang tertentu),
  atau "lainnya"
- "start_date": YYYY-MM-DD (awal periode; default hari ini)
- "end_date": YYYY-MM-DD (akhir periode; default hari ini)
- "keyword": plat nomor atau nama kendaraan jika disebut, selain itu null
- "person": nama orang (driver atau penumpang) jika disebut, tanpa sapaan seperti Pak/Bu, selain itu null
"""
    resp = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    data = json.loads(resp.text)
    if data.get("intent") not in INTENTS:
        raise ValueError(f"intent not valid: {data.get('intent')}")
    s = date.fromisoformat(data["start_date"])
    e = date.fromisoformat(data["end_date"])
    if s > e:
        s, e = e, s
    return {
        "intent": data["intent"],
        "start_date": s.isoformat(),
        "end_date": e.isoformat(),
        "keyword": data.get("keyword") or None,
        "person": data.get("person") or None,
    }

def parse_intent(text: str, today: Optional[date] = None) -> dict:
    today = today or date.today()
    engine = os.getenv("INTENT_ENGINE", "gemini").lower()
    if engine == "gemini" and os.getenv("GEMINI_API_KEY"):
        try:
            return parse_with_gemini(text, today)
        except Exception as e: 
            print(f"[intent] Gemini gagal ({e}); pakai rule-based")
    return parse_rule_based(text, today)
