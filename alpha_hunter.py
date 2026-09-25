"""Shadow-mode Alpha Hunter for the Zorathvael futures scanner.

This module does not import or modify the core scanner. It reads the latest
signal-funnel dataset and converts near-miss observations into opportunity
states for research/monitoring. It never upgrades a candidate to a trade
signal and never changes existing scanner decisions.
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VERSION = "alpha-hunter-v1"
DEFAULT_INPUT = Path("data/signal_funnel_symbols.csv")
DEFAULT_OUTPUT = Path("data/alpha_hunter_watchlist.csv")
DEFAULT_SUMMARY = Path("data/alpha_hunter_summary.csv")

STAGE_EXCLUDED = {"ACTION"}
BLOCKER_WEIGHTS = {
    "location": 16.0, "exhaustion": 12.0, "flow": 14.0, "reclaim": 12.0,
    "expansion": 8.0, "structure": 12.0, "risk": 8.0, "confirmation": 8.0,
}

def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _timestamp(value):
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)

def _latest(rows):
    if not rows:
        return []
    latest = max(_timestamp(r.get("timestamp")) for r in rows)
    return [r for r in rows if _timestamp(r.get("timestamp")) == latest]

def _parse_blockers(row):
    text = " ".join(str(row.get(k, "")) for k in
                    ("reason", "blocker", "long_blocker", "short_blocker", "early_blocker")).lower()
    patterns = {
        "location": r"location|entry location", "exhaustion": r"exhaustion",
        "flow": r"flow", "reclaim": r"reclaim|rejection", "expansion": r"expansion",
        "structure": r"structure", "risk": r"risk|stop distance",
        "confirmation": r"confirm|reversal trigger|trigger",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, text)]

def _direction(row):
    direction = str(row.get("direction") or "").upper().strip()
    if direction in {"LONG", "SHORT"}:
        return direction
    early = str(row.get("early_direction") or "").upper().strip()
    if early in {"LONG", "SHORT"}:
        return early
    bias = str(row.get("bias") or "").upper().strip()
    return bias if bias in {"LONG", "SHORT"} else "NONE"

def score_candidate(row, persistence_count=1):
    """Return a transparent opportunity score, never a trade signal."""
    confidence = max(0.0, min(100.0, _num(row.get("confidence"))))
    v2 = max(0.0, min(100.0, _num(row.get("v2_score"))))
    early = max(0.0, min(1.0, _num(row.get("early_reversal_score")))) * 100.0
    alignment = max(0.0, min(4.0, _num(row.get("alignment")))) / 4.0 * 100.0
    feature_values = []
    for key in ("location_15m", "exhaustion_15m", "base_15m", "structure_shift_5m", "reversal_trigger_5m"):
        if str(row.get(key, "")).strip() != "":
            feature_values.append(max(0.0, min(1.0, _num(row.get(key)))) * 100.0)
    feature_mean = sum(feature_values) / len(feature_values) if feature_values else 0.0
    blockers = _parse_blockers(row)
    blocker_penalty = min(35.0, sum(BLOCKER_WEIGHTS.get(x, 5.0) for x in blockers) * 0.35)
    persistence_bonus = min(8.0, max(0, persistence_count - 1) * 2.0)
    raw = (0.24 * confidence + 0.18 * v2 + 0.24 * early + 0.14 * alignment +
           0.16 * feature_mean + 0.04 * persistence_bonus - blocker_penalty)
    score = max(0.0, min(100.0, raw))
    if score >= 80 and _direction(row) != "NONE":
        state = "ALPHA_READY_SHADOW"
    elif score >= 65 and _direction(row) != "NONE":
        state = "DEVELOPING"
    elif score >= 50:
        state = "WATCH"
    else:
        state = "LOW_POTENTIAL"
    return {
        "alpha_score": round(score, 2), "state": state, "direction": _direction(row),
        "blockers": ",".join(blockers), "persistence_count": persistence_count,
        "confidence": round(confidence, 2), "v2_score": round(v2, 2),
        "early_score": round(early, 2), "alignment_score": round(alignment, 2),
        "structural_score": round(feature_mean, 2),
    }

def run(input_path=DEFAULT_INPUT, output_path=DEFAULT_OUTPUT, summary_path=DEFAULT_SUMMARY):
    input_path, output_path, summary_path = map(Path, (input_path, output_path, summary_path))
    if not input_path.exists():
        raise FileNotFoundError(f"required funnel dataset missing: {input_path}")
    with input_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError("signal funnel dataset is empty")
    latest_rows = _latest(rows)
    counts = Counter(str(r.get("symbol", "")).upper() for r in rows if r.get("symbol"))
    candidates = []
    for row in latest_rows:
        stage = str(row.get("stage") or "").upper()
        if stage in STAGE_EXCLUDED or not row.get("symbol"):
            continue
        scored = score_candidate(row, counts[str(row.get("symbol")).upper()])
        if scored["state"] == "LOW_POTENTIAL":
            continue
        candidates.append({"timestamp": row.get("timestamp", ""), "symbol": row.get("symbol", ""),
                           "provider": row.get("provider", ""), "stage": stage, **scored,
                           "reason": row.get("reason", "")})
    candidates.sort(key=lambda r: (-float(r["alpha_score"]), r["symbol"]))
    fields = ["timestamp", "symbol", "provider", "stage", "state", "direction",
              "alpha_score", "confidence", "v2_score", "early_score", "alignment_score",
              "structural_score", "persistence_count", "blockers", "reason"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidates)
    summary_fields = ["timestamp", "version", "input_rows", "latest_rows", "candidates",
                      "alpha_ready_shadow", "developing", "watch"]
    summary = {
        "timestamp": max(r.get("timestamp", "") for r in latest_rows), "version": VERSION,
        "input_rows": len(rows), "latest_rows": len(latest_rows), "candidates": len(candidates),
        "alpha_ready_shadow": sum(r["state"] == "ALPHA_READY_SHADOW" for r in candidates),
        "developing": sum(r["state"] == "DEVELOPING" for r in candidates),
        "watch": sum(r["state"] == "WATCH" for r in candidates),
    }
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerow(summary)
    return summary, candidates

if __name__ == "__main__":
    summary, candidates = run()
    print("Alpha Hunter", VERSION)
    print(summary)
    for row in candidates[:20]:
        print(row["state"], row["direction"], row["symbol"], row["alpha_score"], row["blockers"])
