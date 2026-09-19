"""Signal Funnel Diagnostic for the MTF scalping scanner.

This module is diagnostic-only. It does not change V2.2 or MTF signal rules.
It explains where scanned symbols are filtered out before ACTION.
"""
import csv
from collections import Counter
from pathlib import Path

from scalping_intelligence import infer_direction, build_plan

SUMMARY_FILE = Path("data/signal_funnel_summary.csv")
SYMBOL_FILE = Path("data/signal_funnel_symbols.csv")

SUMMARY_FIELDS = [
    "timestamp", "provider", "universe", "deep_scan", "data_valid",
    "data_errors", "direction_long", "direction_short", "no_direction",
    "alignment_failed", "location_failed", "reversal_failed",
    "confidence_failed", "risk_failed", "plan_data_failed", "invalid", "actions", "v2_extreme_reversals",
]

SYMBOL_FIELDS = [
    "timestamp", "symbol", "provider", "stage", "direction",
    "confidence", "alignment", "risk_pct", "v2_score", "reason",
]


def diagnose(results, errors, universe_count, scan_count, provider, timestamp):
    """Return one funnel summary and one row per successfully scanned symbol."""
    rows = []
    counts = Counter()

    for x in results:
        counts["data_valid"] += 1
        direction = infer_direction(x["scalping_rows_15m"], x["scalping_rows_5m"])
        extreme = x["extreme"]
        if extreme["status"].startswith("EXTREME REVERSAL"):
            counts["v2_extreme_reversals"] += 1

        if not direction:
            counts["no_direction"] += 1
            rows.append({
                "timestamp": timestamp, "symbol": x["symbol"], "provider": provider,
                "stage": "NO_DIRECTION", "direction": "", "confidence": "",
                "alignment": "", "risk_pct": "", "v2_score": extreme.get("score", ""),
                "reason": "MTF infer_direction returned None",
            })
            continue

        counts[f"direction_{direction.lower()}"] += 1
        v2_score = (
            extreme.get("score", 0.0)
            if extreme["status"].startswith("EXTREME REVERSAL")
            and extreme["direction"] == direction else 0.0
        )
        plan = build_plan(
            direction, x["scalping_rows_15m"], x["scalping_rows_5m"],
            v2_score, x["extreme_features"], require_v2_direction=False,
        )
        status = plan.get("status")
        reason = plan.get("reason", "")
        alignment = sum(float(plan.get(k, 0.0) or 0.0)
                        for k in ("trend_4h", "trend_1h", "structure_30m", "structure_15m"))
        confidence = plan.get("confidence", "")
        risk_pct = plan.get("risk_pct", "")

        if status in {"ACTION LONG", "ACTION SHORT"}:
            stage = "ACTION"
            counts["actions"] += 1
        elif status == "WAIT" and "location" in reason:
            stage = "LOCATION_FAILED"
            counts["location_failed"] += 1
        elif status == "WAIT" and "reversal" in reason:
            stage = "REVERSAL_FAILED"
            counts["reversal_failed"] += 1
        elif status == "WAIT" and "alignment" in reason:
            stage = "ALIGNMENT_FAILED"
            counts["alignment_failed"] += 1
        elif status == "WAIT" and "confidence" in reason:
            stage = "CONFIDENCE_FAILED"
            counts["confidence_failed"] += 1
        elif status == "NO-TRADE" and "risk" in reason:
            stage = "RISK_FAILED"
            counts["risk_failed"] += 1
        elif status == "DATA-LIMITED":
            stage = "PLAN_DATA_FAILED"
            counts["plan_data_failed"] += 1
        elif status == "INVALID":
            stage = "INVALID"
            counts["invalid"] += 1
        else:
            stage = status or "UNKNOWN"
            counts[stage.lower()] += 1

        rows.append({
            "timestamp": timestamp, "symbol": x["symbol"], "provider": provider,
            "stage": stage, "direction": direction, "confidence": confidence,
            "alignment": round(alignment, 3), "risk_pct": risk_pct,
            "v2_score": extreme.get("score", ""), "reason": reason,
        })

    summary = {
        "timestamp": timestamp, "provider": provider,
        "universe": universe_count, "deep_scan": scan_count,
        "data_valid": counts["data_valid"], "data_errors": len(errors),
        "direction_long": counts["direction_long"],
        "direction_short": counts["direction_short"],
        "no_direction": counts["no_direction"],
        "alignment_failed": counts["alignment_failed"],
        "location_failed": counts["location_failed"],
        "reversal_failed": counts["reversal_failed"],
        "confidence_failed": counts["confidence_failed"],
        "risk_failed": counts["risk_failed"],
        "plan_data_failed": counts["plan_data_failed"],
        "invalid": counts["invalid"], "actions": counts["actions"],
        "v2_extreme_reversals": counts["v2_extreme_reversals"],
    }
    return summary, rows


def write(summary, rows):
    """Append one run summary and replace per-symbol detail for the latest run."""
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    summary_exists = SUMMARY_FILE.exists() and SUMMARY_FILE.stat().st_size > 0
    with SUMMARY_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        if not summary_exists:
            writer.writeheader()
        writer.writerow(summary)

    with SYMBOL_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SYMBOL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
