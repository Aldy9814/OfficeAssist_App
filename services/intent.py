import os
import re
import json
import calendar
from datetime import date, timedelta
from typing import Optional

INTENTS = {"laporan_kendaraan", "status_kendaraan", "lainnya"}

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

    if has_vehicle and any(w in t for w in ("laporan", "rekap", "riwayat", "history")):
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
    }

def parse_with_gemini(text: str,today: date) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = f"""Kamu adalah pengurai pesan untuk asisten kantor OfficeAssist (bahasa Indonesia).
Hari ini: {today.isoformat()} ({calendar.day_name[today.weekday()]}). Minggu dimulai hari Senin.
Pesan: "{text}"
 
Keluarkan JSON murni dengan field:
- "intent": "laporan_kendaraan" (minta rekap/laporan perjalanan kendaraan),
  "status_kendaraan" (tanya kendaraan tersedia/sedang dipakai/siapa yang pakai), atau "lainnya"
- "start_date": YYYY-MM-DD (awal periode; default awal bulan ini)
- "end_date": YYYY-MM-DD (akhir periode; default hari ini)
- "keyword": plat nomor atau nama kendaraan jika disebut, selain itu null
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
