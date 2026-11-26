"""Grafik untuk skripsi + verifikasi silang metrik hasil eval_intent.py memakai scikit-learn.

Jalankan dari folder proyek (setelah eval_intent.py menghasilkan file *_detail.csv):
    pip install matplotlib scikit-learn        # sekali saja (lihat requirements-eval.txt)
    py plot_eval.py                            # memakai file *_detail.csv terbaru
    py plot_eval.py --detail eval/results/intent_eval_20261120_090000_detail.csv

Keluaran (folder eval/results/figures/): matriks konfusi per mesin, akurasi per mesin,
akurasi per kategori, F1 per intent, dan sebaran latensi.
Skrip juga menghitung ulang akurasi, presisi, recall, dan F1 dengan scikit-learn dan
membandingkannya dengan angka dari eval_intent.py (cek kebenaran perhitungan).
"""

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

from eval_intent import LABELS, summarize

ROOT = Path(__file__).resolve().parent
SLOT_METRICS = [
    ("intent", "intent_ok"), 
    ("Menyeluruh", "full_ok"),
    ("Tanggal", "date_ok"),
    ("Kata kunci", "keyword_ok"),
    ("Nama orang", "person_ok")
]

def latest_detail(results_dir: Path) -> Path:
    files = sorted(results_dir.glob("*_detail.csv"))
    if not files:
        sys.exit("Belum ada file *_detail.csv. Run eval_intent.py")
    return files[-1]

def load_rows(path: Path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            for k in ("intent_ok", "date_ok", "keyword_ok", "person_ok", "full_ok"):
                r[k] = {"True": True, "False": False}.get(r[k])
            r["run"] = int(r["run"])
            r["latncy_ms"] = float(r["latncy_ms"] or 0)
            rows.append(r)
    return rows

def cross_check(rows, s) -> list:
    y_true = [r["expected_intent"] for r in rows]
    y_pred = [r["predicted_intent"] for r in rows]
    problems = []
    acc = accuracy_score(y_true, y_pred)
    if abs(acc - s["intent_ok"][0]) > 1e-9:
        problems.append(f"akurasi intent: sklearn {acc:.4f} vs skrip {s['intent_ok'][0]:.4f}")
    p, rc, f1, sup = precision_recall_fscore_support(y_true, y_pred, labels=LABELS, zero_division=0)
    for i, lab in enumerate(LABELS):
        mp, mr, mf, ms = s["prf"][lab]
        for name, a, b in (("presisi", p[i], mp or 0.0), ("recall", rc[i], mr or 0.0), ("F1", f1[i], mf or 0.0)):
            if abs(a - b) > 1e-9:
                problems.append(f"{lab} {name}: sklearn {a:.4f} vs skrip {b:.4f}")
        if int(sup[i]) != ms:
            problems.append(f"{lab} jumlah: sklearn {int(sup[i])} vs skrip {ms}")
    return problems

def save(fig, path: Path):
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print("  ", path)

def plot_confusion(engine, s, out: Path):
    cols = LABELS + ["ERROR"]
    m = np.array([[s["confusion"].get((e, p), 0) for p in cols] for e in LABELS])
    fig, ax = plt.subplots(figsize=(7, 5.5))
    im = ax.imshow(m, cmap="Blues")
    ax.set_xticks(range(len(cols)), labels=cols, rotation=30, ha="right")
    ax.set_yticks(range(len(LABELS)), labels=LABELS)
    ax.set_xlabel("Prediksi")
    ax.set_ylabel("Seharusnya")
    ax.set_title(f"Confusion Matrix Intent: {engine}")
    top = m.max() or 1
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            ax.text(j, i, int(m[i, j]), ha="center", va="center", color="white" if m[i, j] > top / 2 else "black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    save(fig, out / f"confusion_{engine}.png")

def grouped_bars(ax, groups, series, ylabel):
    n = len(series)
    width = 0.8 / n
    x = np.arange(len(groups))
    for k, (name, vals) in enumerate(series.items()):
        vals = [np.nan if v is None else v for v in vals]
        bars = ax.bar(x + (k - (n - 1) / 2) * width, vals, width, label=name)
        for b, v in zip(bars, vals):
            if not np.isnan(v):
                ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}", ha="center", fontsize=8)
    ax.set_xticks(x, labels=groups)
    ax.set_ylim(0, 112)
    ax.set_ylabel(ylabel)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

def pc(v):
    return None if v is None else v * 100

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Grafik dan verifikasi silang hasil evaluasi intent")
    ap.add_argument("--detail", help="file *_detail.csv (bawaan: yang terbaru di eval/results)")
    ap.add_argument("--out", default=str(ROOT / "eval" / "results" / "figures"))
    args = ap.parse_args(argv)

    detail = Path(args.detail) if args.detail else latest_detail(ROOT / "eval" / "results")
    rows = load_rows(detail)
    engines = sorted({r["engine"] for r in rows}, key=["rules", "gemini"].index)
    sums = {e: summarize([r for r in rows  if r["engine"] == e]) for e in engines}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"membaca: {detail}")

    print("\nCross verification with scikit-learn")
    ok = True
    for e in engines:
        problems = cross_check([r for r in rows if r["engine"] == e], sums[e])
        print(f" {e}: {'OK, sama dengan perhitungan eval_intent.py' if not problems else 'TIDAK SAMA'}")
        for p in problems:
            print("    -", p)
        ok = ok and not problems

    print("\nGraph: ")
    for e  in engines: 
        plot_confusion(e, sums[e], out)

    fig, ax = plt.subplots(figsize=(8, 4.5))