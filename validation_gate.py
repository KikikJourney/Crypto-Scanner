"""Statistical validation gate for persisted scanner forward-test evidence.

This module is research/QA only. It never changes scanner rules or emits trades.
It evaluates resolved R outcomes chronologically, reports stability across
walk-forward time segments, and estimates uncertainty with deterministic bootstrap.
Ambiguous outcomes are reported separately and are not counted as wins/losses.
"""
import csv
import math
import random
from datetime import datetime
from pathlib import Path

INPUT = Path("data/scalping_forward_test.csv")
OUTPUT = Path("data/scalping_validation_report.csv")
MIN_SAMPLE = 30
BOOTSTRAP_SAMPLES = 2000
SEED = 20260921


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def load_rows(path=INPUT):
    if not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def resolved_r(rows):
    out = []
    for row in rows:
        value = _f(row.get("outcome_r"))
        if value is None:
            continue
        outcome = row.get("first_touch", "")
        if outcome not in {"EXPANSION", "FAIL"}:
            continue
        out.append((_ts(row["timestamp"]), value))
    return sorted(out, key=lambda x: x[0])


def _max_drawdown(values):
    equity = peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return round(drawdown, 6)


def _profit_factor(values):
    gross_win = sum(v for v in values if v > 0)
    gross_loss = -sum(v for v in values if v < 0)
    if gross_loss == 0:
        return math.inf if gross_win > 0 else 0.0
    return gross_win / gross_loss


def _bootstrap_mean(values, samples=BOOTSTRAP_SAMPLES, seed=SEED):
    if not values:
        return None, None, None
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(samples):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[max(0, int(0.025 * samples) - 1)]
    hi = means[min(samples - 1, int(0.975 * samples))]
    return round(sum(values) / n, 6), round(lo, 6), round(hi, 6)


def metrics(values):
    n = len(values)
    if not n:
        return {
            "n": 0, "win_rate": 0.0, "expectancy_r": 0.0,
            "profit_factor": 0.0, "net_r": 0.0, "max_drawdown_r": 0.0,
        }
    wins = sum(v > 0 for v in values)
    return {
        "n": n,
        "win_rate": round(wins / n, 6),
        "expectancy_r": round(sum(values) / n, 6),
        "profit_factor": round(_profit_factor(values), 6) if math.isfinite(_profit_factor(values)) else "inf",
        "net_r": round(sum(values), 6),
        "max_drawdown_r": _max_drawdown(values),
    }


def walk_forward(values, segments=3):
    """Split chronologically; no future sample is used to score an earlier segment."""
    if not values:
        return []
    segments = max(1, min(segments, len(values)))
    size = math.ceil(len(values) / segments)
    report = []
    for index in range(segments):
        chunk = values[index * size:(index + 1) * size]
        if not chunk:
            continue
        m = metrics(chunk)
        m["segment"] = index + 1
        report.append(m)
    return report


def evidence_status(report):
    """Classify evidence separately from sample sufficiency.
    
    This is descriptive research status only; it never changes scanner behavior.
    """
    if report["resolved_trades"] < MIN_SAMPLE:
        return "INSUFFICIENT_SAMPLE"
    low = report["bootstrap_ci95_low"]
    high = report["bootstrap_ci95_high"]
    if low is None or high is None:
        return "INSUFFICIENT_SAMPLE"
    if high < 0:
        return "NEGATIVE_CI"
    if low > 0:
        return "POSITIVE_CI"
    return "INCONCLUSIVE_CI"


def build_report(rows=None):
    rows = load_rows() if rows is None else rows
    resolved = resolved_r(rows)
    values = [value for _, value in resolved]
    ambiguous = sum(1 for r in rows if r.get("first_touch") == "AMBIGUOUS")
    mean, ci_low, ci_high = _bootstrap_mean(values)
    base = metrics(values)
    return {
        "sample_total": len(rows),
        "resolved_trades": len(values),
        "ambiguous": ambiguous,
        "unresolved": max(0, len(rows) - len(values) - ambiguous),
        "ambiguous_rate": round(ambiguous / len(rows), 6) if rows else 0.0,
        "min_sample_for_gate": MIN_SAMPLE,
        "sample_gate_pass": len(values) >= MIN_SAMPLE,
        "evidence_status": evidence_status({
            "resolved_trades": len(values),
            "bootstrap_ci95_low": ci_low,
            "bootstrap_ci95_high": ci_high,
        }),
        "bootstrap_expectancy_r": mean,
        "bootstrap_ci95_low": ci_low,
        "bootstrap_ci95_high": ci_high,
        **base,
        "walk_forward": walk_forward(values),
    }


def write(rows=None, path=OUTPUT):
    report = build_report(rows)
    flat = {k: v for k, v in report.items() if k != "walk_forward"}
    flat["walk_forward_segments"] = len(report["walk_forward"])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat))
        writer.writeheader()
        writer.writerow(flat)
    return report


if __name__ == "__main__":
    report = write()
    print("SCALPING VALIDATION:")
    print(
        f"resolved={report['resolved_trades']} ambiguous={report['ambiguous']} "
        f"expectancy_R={report['expectancy_r']:.4f} net_R={report['net_r']:.2f} "
        f"maxDD_R={report['max_drawdown_r']:.2f} "
        f"bootstrap95=[{report['bootstrap_ci95_low']}, {report['bootstrap_ci95_high']}] "
        f"sample_gate={'PASS' if report['sample_gate_pass'] else 'COLLECTING'} "
        f"evidence_status={report['evidence_status']}"
    )
    for segment in report["walk_forward"]:
        print(
            f"segment={segment['segment']} n={segment['n']} "
            f"expectancy_R={segment['expectancy_r']:.4f} "
            f"net_R={segment['net_r']:.2f}"
        )
