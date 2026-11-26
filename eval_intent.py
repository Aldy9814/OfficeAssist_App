"""Evaluasi akurasi pengurai intent: Gemini dibandingkan parser aturan.

Jalankan dari folder proyek (di samping app.py):
    python eval_intent.py                       # kedua mesin (Gemini hanya bila GEMINI_API_KEY ada)
    python eval_intent.py --engines rules       # tanpa internet
    python eval_intent.py --runs 3 --sleep 4    # Gemini 3x untuk mengukur konsistensi, jeda 4 detik

Definisi penilaian:
  - intent_ok  : intent prediksi = intent yang diharapkan.
  - date_ok    : start_date dan end_date sama (hanya untuk intent laporan dan pemakaian).
  - keyword_ok : plat atau nama kendaraan cocok (sama persis, atau salah satunya memuat yang lain).
  - person_ok  : nama orang cocok (sapaan Pak/Bu diabaikan).
  - full_ok    : intent benar DAN semua slot yang relevan benar (untuk status dan lainnya: cukup intent).
  - Gagal panggilan (error jaringan, kuota, JSON tidak valid) dihitung salah dan dilaporkan terpisah.
Tanggal acuan dibuat tetap (--today) agar hasil bisa diulang.
"""

import argparse
import csv
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from services.intent import INTENTS, parse_rule_based, parse_with_gemini, resolve_period

ROOT = Path(__file__).resolve().parent
LABELS = ["laporan_kendaraan", "pemakaian_kendaraan", "status_kendaraan", "lainnya"]
SLOT_INTENTS = {"laporan_kendaraan", "pemakaian_kendaraan"}
PERIOD_CODES = {"", "today", "yesterdat", "this_week", "last_week", "this_month", "last_month", "last_3_days", "custom"}
DEFAULT_TODAY = "2026-11-18"


# ---------- data ----------

def load_dataset(path: Path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def expected_dates(item: dict, today: date):
    code = item["expected_period"]
    if not code:
        return None
    if code == "custom":
        return item["expected_start"], item["expected_end"]
    if code == "last_3_days":
        return (today - timedelta(days=2)).isoformat(), today.isoformat()
    s, e = resolve_period(code, today)
    return s.isoformat(), e.isoformat()


# ---------- normalisasi dan penilaian ----------

def norm_kw(x) -> str:
    return re.sub(r"\s+", "", str(x or "")).upper()

def norm_person(x) -> str:
    s = str(x or "").strip().lower()
    return re.sub(r"^(pak|bu|bapak|ibu|mas|mbak|sdr|saudara)\s+", "", s)

def text_match(expected: str, predicted: str, normalizer) -> bool:
    e, p = normalizer(expected), normalizer(predicted)
    if not e and not p:
        return True
    if not e or not p:
        return False
    return e == p or e in p or p in e

def score(item: dict, pred: dict, today: date) -> dict:
    exp = item["expected_intent"]
    r = {"intent_ok": pred.get("intent") == exp, "date_ok": None, "keyword_ok": None, "person_ok": None}
    if exp in SLOT_INTENTS:
        exp_dates = expected_dates(item, today)
        r["date_ok"] = (pred.get("start_date"), pred.get("end_date")) == exp_dates
        r["keyword_ok"] = text_match(item["expected_intent"], pred.get("keyword"), norm_kw)
        r["person_ok"] = text_match(item["expected_person"], pred.get("person"), norm_person)
        r["full_ok"] = r["intent_ok"] and r["date_ok"] and r["keyword_ok"] and r["person_ok"]
    else:
        r["full_ok"] = r["intent_ok"]
    return r

def predict(engine: str, text: str, today: date, retries: int):
    """Return (hasil, error, latensi_ms). Latensi = percobaan terakhir."""
    out, err, latency = None, None, 0.0
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            out = parse_rule_based(text, today) if engine == "rules" else parse_with_gemini(text, today)
            err = None
        except Exception as e:
            out, err = None, f"{type(e).__name__}: {str(e)[:160]}"
        latency = (time.perf_counter() - t0) * 1000
        if err is None:
            break
        if attempt < retries:
            time.sleep(5 * (attempt + 1))
    return out, err, latency


# ---------- agregasi ----------

def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return s[max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))]

def frac(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    return (sum(1 for v in vals if v) / len(vals), len(vals)) if vals else (None, 0)

def fmt(x):
    return "-" if x is None else f"{x * 100:.1f}%"

def summarize(rows):
    s = {"n": len(rows)}
    for key in ["intent_ok", "full_ok", "date_ok", "keyword_ok", "person_ok"]:
        s[key] = frac(rows, key)
    s["errors"] = sum(1 for r in rows if r["error"])
    lat = [r["latency_ms"] for r in rows if not r["error"]]
    s["lat_mean"] = sum(lat) / len(lat) if lat else None
    s["lat_median"] = pct(lat, 50)
    s["lat_p95"] = pct(lat, 95)

    # precission, recall, F1 per intent
    prf = {}
    for lab in LABELS:
        tp = sum(1 for r in rows if r["expected_intent"] == lab and r["predicted_intent"] == lab)
        fp = sum(1 for r in rows if r["expected_intent"] == lab and r["predicted_intent"] == lab)
        fn = sum(1 for r in rows if r["expected_intent"] == lab and r["predicted_intent"] == lab)
        p = tp / (tp + fp) if tp + fp else None
        rc = tp / (tp + fn) if tp + fn else None
        f1 = 2 * p * rc / (p + rc) if p and rc else (0.0 if p is not None and rc is not None else None)
        prf[lab] = (p, rc, f1, tp + fn)
    s["prf"] = prf
    s["confusion"] = Counter((r['expected_intent'], r["predicted_intent"]) for r in rows)
    cats = defaultdict(list)
    for r in rows:
        cats[r["category"]].append(r)
    s["by_category"] = {c: (frac(v, "intent_ok")[0], frac(v, "full_ok")[0], len(v)) for c, v in sorted(cats.items())}

    by_id = defaultdict(set)
    runs = {r["run"] for r in rows}
    for r in rows:
        by_id[r["id"]].add((
            r["predicted_intent"],
            r["predicted_start"],
            r["predicted_end"],
            norm_kw(r["predicted_keyword"]), norm_person(r["predicted_person"])
        ))
    s["runs"] = len(runs)
    s["consistency"] = (sum(1 for v  in by_id.values() if len(v) == 1) / len(by_id)) if by_id and len(runs) > 1 else None
    s["per_run_intent"] = [frac([r for r in rows if r["run"] == k], "intent_ok")[0] for k in sorted(runs)]
    return s


# ---------- output ----------

def render_markdown(meta, sums, failures):
    L = [
        f"# Hasil Evaluasi Intent\n",
        f"- Tanggal evaluasi: {meta['when']}",
        f"- Tanggal acuan (hari ini): {meta['today']}",
        f"- Jumlah pesan: {meta['n_items']}",
        f"- Model Gemini: {meta['model']} (suhu 0)",
        f"- Jumlah run Gemini: {meta['runs']}\n"
    ]
    engines = list(sums)
    L += ["## Ringkasan\n", "| Metrik | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    rows = [
        ("Akurasi intent", "intent_ok"),
        ("Akurasi menyeluruh (intent + slot)", "full_ok"),
        ("Akurasi tanggal", "date_ok"),
        ("Akurasi kata kunci (plat/kendaraan)", "keyword_ok"),
        ("Akurasi nama orang", "person_ok")
    ]
    for label, key in rows:
        L.append(f"| {label} | " + " | ".join(fmt(sums[e][key][0]) + f" ({sums[e][key][1]})" for e in engines) + " |")
    L.append("| Gagal panggilan | " + " | ".join(str(sums[e]["errors"]) for e in engines) + " |")
    L.append("| Latency rata-rata (ms) | " + " | ".join("-" if sums[e]["lat_mean"] is None else f"{sums[e]['lat_mean']:.1f}" for e in engines) + " |")
    L.append("| Latensi median (ms) | " + " | ".join("-" if sums[e]["lat_median"] is None else f"{sums[e]['lat_median']:.1f}" for e in engines) + " |")
    L.append("| Latensi p95 (ms) | " + " | ".join("-" if sums[e]["lat_p95"] is None else f"{sums[e]['lat_p95']:.1f}"for e in engines) + " |")
    if any(sums[e]["consistency"] is not None for e in engines):
        L.append("| Konsistensi antar-run | " + " | ".join(fmt(sums[e]["consistency"]) for e in engines) + " |")
    for e in engines:
        s = sums[e]
        L += [f"\n## Presisi, recall, F1 per intent: {e}\n", "| Intent | Presisi | Recall | F1 | Jumlah |", "|---|---|---|---|---|"]
        for lab in LABELS:
            p, rc, f1, support = s["prf"][lab]
            L.append(f"| {lab} | {fmt(p)} | {fmt(rc)} | {fmt(f1)} | {support} |")
        L += [f"\n### Confusion Matrix: {e}\n",
              "| | " + " | ".join(LABELS + ["ERROR"]) + " |", "|---|" + "---|" * (len(LABELS) + 1)]
        for exp in LABELS:
            L.append(f"| {exp} | " + " | ".join(str(s["confusion"].get((exp, pr), 0)) for pr in LABELS + ["ERROR"]) + " |")
        L += [f"\n### Akurasi pe kategori: {e}\n", "| Kategori | Intent | Menyeluruh | Jumlah |", "|---|---|---|---|"]
        for c, (ia, fa, n) in s["by_category"].items():
            L.append(f"| {c} | {fmt(ia)} | {fmt(fa)} | {n} |")
    for e in engines:
        L += [f"\n## Kesalahan: {e}\n"]
        if not failures[e]:
            L.append("Tidak ada.")
            continue
        L += ["| ID | Pesan | Seharusnya | Prediksi | Catatan |", "|---|---|---|---|---|"]
        for r in failures[e]:
            exp = f"{r['expected_intent']} {r['expected_start']}..{r['expected_end']} kw={r['expected_keyword'] or '-'} orang={r['expected_person'] or '-'}"
            prd = f"{r['predicted_intent']} {r['predicted_start']}..{r['predicted_end']} kw={r['predicted_keyword'] or '-'} orang={r['predicted_person'] or '-'}"
            L.append(f"| {r['id']} | {r['message']} | {exp} | {prd} | {r['error'] or ''} |")
    return "\n".join(L) + "\n"

DETAIL_COLS = ["engine", "run", "id", "category", "message", "expected_intent", "predicted_intent",
               "expected_start", "expected_end", "predicted_start", "predicted_end",
               "expected_keyword", "predicted_keyword", "expected_person", "predicted_person",
               "intent_ok", "date_ok", "keyword_ok", "person_ok", "full_ok", "latency_ms", "error"]


# ---------- main ----------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluasi akurasi pengurai intent")
    ap.add_argument("--dataset", default=str(ROOT / "eval" / "intent_testset.csv"))
    ap.add_argument("--engines", nargs="+", choices=["rules", "gemini"])
    ap.add_argument("--runs", type=int, default=1, help="jumlah pengulangan untuk Gemini")
    ap.add_argument("--sleep", type=float, default=1.0, help="jeda (detik) antar panggilan Gemini")
    ap.add_argument("--retries", type=int, default=2, help="percobaan ulang bila Gemini gagal")
    ap.add_argument("--today", default=DEFAULT_TODAY, help="tanggal acuan YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=0, help="hanya N pesan pertama (uji cepat)")
    ap.add_argument("--out", default=str(ROOT / "eval" / "results"))
    args = ap.parse_args(argv)

    today = date.fromisoformat(args.today)
    items = load_dataset(Path(args.dataset))
    if args.limit:
        items = items[:args.limit]
    engines = args.engines or (["rules", "gemini"] if os.getenv("GEMINI_API_KEY") else ["rules"])
    if "gemini" in engines and not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY belum diisi; mesin gemini dilewati.")
        engines = [e for e in engines if e != "gemini"]
    if not engines:
        print("Tidak ada mesin untuk dijalankan.")
        return 1
    assert set(LABELS) == INTENTS, "daftar intent di eval_intent.py berbeda dari services/intent.py"

    all_rows = {}
    for engine in engines:
        n_runs = max(1, args.runs) if engine == "gemini" else 1
        rows = []
        for run in range(1, n_runs + 1):
            for i, item in enumerate(items, start=1):
                pred, err, lat = predict(engine, item["message"], today, args.reetries if engine == "gemini" else 0)
                p = pred or {}
                sc = score(item, p, today) if pred else {
                    "intent_ok": False,
                    "date_ok": None,
                    "keyword_ok": None,
                    "person_ok": None,
                    "full_ok": False
                }
                if pred is None and item["expected_intent"] in SLOT_INTENTS:
                    sc.update(date_ok=False, keyword_ok=False, person_ok=False)
                exp_d = expected_dates(item, today)
                rows.append({
                    "engine": engine,
                    "run": run,
                    "id": item["id"],
                    "category": item["category"],
                    "message": item["message"],
                    "expected_intent": item["expected_intent"],
                    "predicted_intent": p.get("intent", "ERROR"),
                    "expected_start": exp_d[0] if exp_d else "", 
                    "expected_end": exp_d[1] if exp_d else "",
                    "predicted_start": p.get("start_date", ""),
                    "predicted_end": p.get("end_date", ""),
                    "expected_keyword": item["expected_keyword"],
                    "predicted_keyword": p.get("keyword") or "",
                    "expected_person": item["expected_person"],
                    "predicted_person": p.get("person") or "",
                    **sc, "latency_ms": round(lat, 1), "error": err or "",
                })
                if engine == "gemini" and args.sleep:
                    time.sleep(args.sleep)
                if i % 10 == 0:
                    print(f"[{engine} run {run}] {i}/{len(items)}")
        all_rows[engine] = rows

    sums = {e: summarize(r) for e, r in all_rows.items()}
    failures = {e: [r for r in rows if not r["full_ok"] and r["run"] == 1] for e, rows in all_rows.items()}
    meta = {
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"), 
        "today": args.today, 
        "n_items": len(items),
        "model": os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        "runs": max(1, args.runs) if "gemini" in engines else 0
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_path = out / f"intent_eval_{stamp}_detail.csv"
    summary_path = out / f"intent_eval_{stamp}_ringkasan.md"
    with open(detail_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_COLS)
        w.writeheader()
        for rows in all_rows.values():
            w.writerows(rows)
    summary_path.write_text(render_markdown(meta, sums, failures), encoding="utf-8")

    print("\n=== RINGKASAN ===")
    print(f"{'mesin':<8} {'intent':>8} {'menyeluruh':>11} {'tanggal':>8} {'error':>6} {'lat.med(ms)':>12}")

    for e, s in sums.items():
        lat = "-" if s["lat_median"] is None else f"{s['lat_median']:.0f}"
        print(f"{e:<8} {fmt(s['intent_ok'][0]):>8} {fmt(s['full_ok'][0]):>11} {fmt(s['date_ok'][0]):>8} {s['errors']:>6} {lat:>12}")
        if s["consistency"] is not None:
            print(f"        konsistensi antar run: {fmt(s['consistency'])}")
    print(f"\nDetail    : {detail_path}\nRingkasan: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
