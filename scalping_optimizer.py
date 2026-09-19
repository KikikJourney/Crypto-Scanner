"""Evidence-driven optimizer report for the scalping scanner.

This module never changes trading rules automatically. It turns resolved
forward-test outcomes into measurable diagnostics so threshold changes are
made only after enough observations exist.
"""
import csv
from collections import defaultdict
from pathlib import Path

INPUT = Path("data/scalping_forward_test.csv")
OUTPUT = Path("data/scalping_optimization_report.csv")
HORIZONS = ("h15", "h30", "h60", "h120")
FIELDS = ["dimension", "bucket", "resolved", "expansion", "fail", "ambiguous",
          "expansion_rate", "fail_rate", "min_sample_for_review"]


def _rows():
    if not INPUT.exists():
        return []
    with INPUT.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _outcome(row):
    for h in HORIZONS:
        value = row.get(h, "")
        if value:
            return value
    return ""


def _bucket(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if v < 85:
        return "80-84.9"
    if v < 90:
        return "85-89.9"
    return "90-100"


def build_report(rows=None):
    rows = _rows() if rows is None else rows
    groups = defaultdict(list)
    for row in rows:
        outcome = _outcome(row)
        if outcome not in {"EXPANSION", "FAIL", "AMBIGUOUS"}:
            continue
        groups[("confidence", _bucket(row.get("confidence")))].append(outcome)
        groups[("location_15m", row.get("location_15m", "unknown"))].append(outcome)
        groups[("reversal_5m", row.get("reversal_5m", "unknown"))].append(outcome)

    report = []
    for (dimension, bucket), outcomes in sorted(groups.items()):
        n = len(outcomes)
        expansion = outcomes.count("EXPANSION")
        fail = outcomes.count("FAIL")
        ambiguous = outcomes.count("AMBIGUOUS")
        report.append({
            "dimension": dimension, "bucket": bucket, "resolved": n,
            "expansion": expansion, "fail": fail, "ambiguous": ambiguous,
            "expansion_rate": round(expansion / n, 4) if n else 0,
            "fail_rate": round(fail / n, 4) if n else 0,
            "min_sample_for_review": 30,
        })
    return report


def write(rows=None):
    report = build_report(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(report)
    return report


if __name__ == "__main__":
    report = write()
    print("SCALPING OPTIMIZATION REPORT:")
    if not report:
        print("No resolved actions yet; collect forward-test outcomes before tuning.")
    for row in report:
        print(
            f"{row['dimension']}={row['bucket']} | n={row['resolved']} | "
            f"EXPANSION={row['expansion_rate']:.1%} | FAIL={row['fail_rate']:.1%} | "
            f"review_after_n={row['min_sample_for_review']}"
        )
