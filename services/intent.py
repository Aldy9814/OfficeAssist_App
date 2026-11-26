import os
import re
import json
import calendar
import time
from datetime import date, timedelta
from functools import lru_cache
from typing import Optional

INTENTS = {"laporan_kendaraan", "status_kendaraan", "pemakaian_kendaraan", "lainnya"}

USAGE_RE = re.compile(r"\b(?:siapa|pemakai|pengguna|yang pakai|yang memakai|yang menggunakan|"
                      r"yang bawa|dipakai oleh|dibawa oleh)\b")
REPORT_WORDS = ("laporan", "rekap", "riwayat", "history")
VEHICLE_WORDS = ("kendaraan", "mobil", "trip", "perjalanan")
STATUS_WORDS = ("status", "tersedia", "available", "dipakai, pakai")
PERSON_RE = re.compile(r"\b(?:pak|bu|bapak|ibu|mas|mbak|sdr|saudara)\s+([a-z]+)\b")

PLATE_RE = re.compile(r"\b([a-z]{1,2})\s?(\d{1,4})\s?([a-z]{1,3})\b")
MONTH_WORDS = {"jan", "feb", "mar", "apr", "mei", "jun", "jul", "agu", "sep", "okt", "nov", "des"}
IGNORED_SUFFIX = MONTH_WORDS | {"jam", "org"}
IGNORED_PREFIX = {"di", "ke", "se"}

PERIODS = (
    ("yesterday", ("kemarin",)),
    ("last_week", ("minggu lalu", "pekan lalu")),
    ("this_week", ("minggu ini", "pekan ini")),
    ("last_month", ("bulan lalu",)),
    ("this_month", ("bulan ini",)),
    ("today", ("hari ini",)),
)
HANDLED_RE = re.compile("|".join(re.escape(p) for _, ps in PERIODS for p in ps))

_MONTHS = r"jan(?:uari)?|feb(?:ruari)?|mar(?:et)?|apr(?:il)?|mei|juni?|juli?|agu(?:stus)?|sep(?:tember)?|okt(?:ober)?|nov(?:ember)?|des(?:ember)?"
DATE_HINT_RE = re.compile(
    r"(?:\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b|"
    r"\b(?:tanggal|tgl|lusa|tadi|sampai|s/d|hingga|antara|senin|selasa|rabu|kamis|jumat|jum'at|sabtu|minggu|pekan|"
    r"bulan|tahun|kemarin|" + _MONTHS + r")\b|"
    r"\b\d+\s+(?:hari|minggu|pekan|bulan)\b)"
)
DOMAIN_HINT_RE =  re.compile(
    r"\b(?:armada|driver|supir|sopir|plat|nopol|pakai|dipakai|bawa|dibawa|motor|"
    r"kendaraan|mobil|trip|perjalanan)\b"
)

def _extract_person(t: str) -> Optional[str]:
    m = PERSON_RE.search(t)
    return m.group(1).title() if m else None

def _extract_keyword(t: str) -> Optional[str]:
    for m in PLATE_RE.finditer(t):
        prefix, digits, suffix = m.groups()
        if prefix in IGNORED_PREFIX or suffix in IGNORED_SUFFIX:
            continue
        return f"{prefix}{digits}{suffix}".upper()
    return None

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

def _detect_period(t: str) -> str:
    for name, phrases in PERIODS:
        if any(p in t for p in phrases):
            return name
    return "today"

def _extract_keyword(t: str) -> Optional[str]:
    m = re.search(r"\b([a-z]{1,2})\s?(\d{1,4})\s?([a-z]{1,3})\b", t)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}".upper() if m else None

def parse_rule_based(text: str, today: Optional[date] = None) -> dict:
    today = today or date.today()
    t = text.lower()
    has_vehicle = any(w in t for w in VEHICLE_WORDS)
    keyword = _extract_keyword(t)
    person = _extract_person(t)

    if USAGE_RE.search(t) and (has_vehicle or keyword):
        intent = "pemakaian_kendaraan"
    elif person and has_vehicle and not any(w in t for w in REPORT_WORDS):
        intent = "pemakaian_kendaraan"
    elif has_vehicle and any(w in t for w in REPORT_WORDS):
        intent = "laporan_kendaraan"
    elif has_vehicle and any(w in t for w in STATUS_WORDS):
        intent = "status_kendaraan"
    else:
        intent = "lainnya"

    start, end = resolve_period(_detect_period(t), today)
    return {
        "intent": intent,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "keyword": keyword,
        "person": person,
    }

def _needs_llm(text: str, rule_result: dict) -> bool:
    """True bila aturan berisiko salah, sehingga layak membayar latensi Gemini."""
    t = text.lower()
    if DATE_HINT_RE.search(HANDLED_RE.sub(" ", t)):
        return True
    if rule_result["intent"] == "lainnya" and DOMAIN_HINT_RE.search(t):
        return True
    return False


# ------------------- Gemini ---------------------
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS"))
GEMINI_COOLDOWN_S = int(os.getenv("GEMINI_COOLDOWN_S"))
_gemini_down_until = 0.0

@lru_cache(maxsize=1)
def _gemini_client():
    from google import genai
    from google.genai import types
    return genai.Client(
        api_key=os.getenv("GEMII_API_KEY"),
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
    )

@lru_cache(maxsize=256)
def _gemini_cached(text: str,today_iso: str) -> tuple:
    from google.genai import types
    
    today = date.fromisoformat(today_iso)
    prompt = f"""Kamu adalah pengurai pesan untuk asisten kantor OfficeAssist (bahasa Indonesia).
Hari ini: {today.isoformat()} ({calendar.day_name[today.weekday()]}). Minggu dimulai hari Senin.
Pesan (string JSON): {json.dumps(text, ensure_ascii=False)}

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
    cfg = {"response_mime_type": "application/json", "temperature": 0}
    budget = os.getenv("GEMINI_THINING_BUDGET")
    if budget is not None:
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=int(budget))
    resp = _gemini_client().models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(**cfg),
    )
    data = json.loads(resp.text)
    if not isinstance(data, dict) or data.get("intent") not in INTENTS:
        raise ValueError(f"intent tidak valid: {data!r}")
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

def parse_with_gemini(text: str, today: date):
    intent, s, e, keyword, person = _gemini_cached(" ".join(text.split()), today.isoformat())
    return {
        "intent": intent,
        "start_date": s,
        "end_date": e,
        "keyword": keyword,
        "person": person
    }

def parse_intent(text: str, today: Optional[date] = None) -> dict:
    """INTENT_ENGINE: hybrid (default) = aturan dulu, Gemini hanya bila ambigu;
    gemini = selalu Gemini; rules = tanpa Gemini."""
    global _gemini_down_until
    today = today or date.today()
    engine = os.getenv("INTENT_ENGINE", "hybrid").lower()

    result = parse_rule_based(text, today)
    result["engine"] = "rules"
    if engine == "rules" or not os.getenv("GEMIN_API_KEY"):
        return result
    if engine == "hybrid" and not _needs_llm(text, result):
        return result

    if time.monotonic() < _gemini_down_until:
        result["engine"] = "rules-fallback"
        return result
    try:
        llm = parse_with_gemini(text, today)
        llm["engine"] = "gemini"
        return llm
    except Exception as e:
        _gemini_down_until = time.monotonic() + GEMINI_COOLDOWN_S
        print(f"[intent] Gemini gagal ({e!r}); pakai rule-based selama {GEMINI_COOLDOWN_S} detik")
        result["engine"] = "rules-fallback"
        return result
