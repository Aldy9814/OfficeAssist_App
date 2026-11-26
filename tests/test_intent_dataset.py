import csv
from collections import Counter
from datetime import date
from pathlib import Path

from services.intent import INTENTS, parse_rule_based

DATASET = Path(__file__).resolve().parent.parent / "eval" / "intent_testset.csv"
PERIODS = {"", "today", "yesterday", "this_week", "last_week", "this_month", "last_month", "last_3_days", "custom"}

def load():
    with open(DATASET, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def test_dataset_is_well_formed():
    rows = load()
    assert len(rows) == 50
    assert len({r["id"] for r in rows}) == 50
    for r in rows: 
        assert r["message"].strip()
        assert r["expected_intent"] in INTENTS
        assert r["expected_period"] in PERIODS
        slot = r["expected_intent"] in {"laporan_kendaraan", "pemakaian_kendaraan"}
        assert bool(r["expected_period"]) == slot, r["id"]
        if r["expected_period"] == 'custom':
            date.fromisoformat(r["expected_start"])
            date.fromisoformat(r["expected_end"])

def test_every_intent_has_enough_example():
    counts = Counter(r["expected_intent"] for r in load())
    assert set(counts) == INTENTS
    assert all(n >= 8 for n in counts.values()), counts

def test_rule_based_runs_on_every_message():
    for r in load():
        out = parse_rule_based(r["message"], date(2026, 11, 18))
        assert out["intent"] in INTENTS