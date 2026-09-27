"""Historical execution thesis audit.

Reads persisted repository history only. It does not alter signals or trades.
"""
import csv
from pathlib import Path
from statistics import median

ACTION = Path("data/scalping_action_history.csv")
ENTRY = Path("data/scalping_entry_location_100.csv")


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def action_audit(rows):
    ratios, exact_2r = [], 0
    for r in rows:
        e, s, t = f(r.get("entry")), f(r.get("stop")), f(r.get("target"))
        if None in (e, s, t):
            continue
        risk = abs(e - s)
        if risk <= 0:
            continue
        rr = abs(t - e) / risk
        ratios.append(rr)
        exact_2r += abs(rr - 2.0) < 1e-9
    return {
        "rows": len(rows),
        "valid_geometry": len(ratios),
        "exact_2r": exact_2r,
        "exact_2r_pct": round(100 * exact_2r / len(ratios), 2) if ratios else 0.0,
        "rr_median": round(median(ratios), 4) if ratios else 0.0,
        "rr_min": round(min(ratios), 4) if ratios else 0.0,
        "rr_max": round(max(ratios), 4) if ratios else 0.0,
        "rr_le_3_5_pct": round(100 * sum(x <= 3.5 for x in ratios) / len(ratios), 2) if ratios else 0.0,
    }


def entry_audit(rows):
    reward = [f(r.get("reward_r")) for r in rows if f(r.get("reward_r")) is not None]
    statuses = {}
    for r in rows:
        statuses[r.get("status", "")] = statuses.get(r.get("status", ""), 0) + 1
    exact_2r = sum(abs(x - 2.0) < 1e-9 for x in reward)
    return {
        "rows": len(rows),
        "reward_rows": len(reward),
        "exact_2r": exact_2r,
        "exact_2r_pct": round(100 * exact_2r / len(reward), 2) if reward else 0.0,
        "reward_median": round(median(reward), 4) if reward else 0.0,
        "statuses": statuses,
    }


def main():
    a = action_audit(load(ACTION))
    e = entry_audit(load(ENTRY))
    print("HISTORICAL EXECUTION THESIS")
    print("action_history:", a)
    print("entry_location_100:", e)
    if e["exact_2r_pct"] >= 90.0:
        print("THESIS: legacy 100-candle shadow is fixed-R contaminated; do not use its 2R ladder as strategy evidence.")
    print("THESIS: production execution must derive TP from structural target and report realized Entry->SL->TP R.")
    print("THESIS: 100-candle location remains timing; ATR remains volatility/risk geometry; RR is a feasibility gate and measurement.")
    print("THESIS: historical validation must use point-in-time candles and include fees/slippage before claiming an edge.")


if __name__ == "__main__":
    main()
