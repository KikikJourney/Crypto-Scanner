"""Descriptive audit of persisted forward-test evidence.

Research/QA only. This module does not alter signals, thresholds, or execution.
It measures independence proxies, stratification, temporal concentration,
MFE/MAE coverage, and whether execution-friction fields are actually recorded.
"""
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

INPUT = Path("data/scalping_forward_test.csv")
OUTPUT = Path("data/scalping_evidence_audit.csv")
CURRENT = "scalp-structure-v1"


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


def _bucket_confidence(value):
    x = _f(value)
    if x is None:
        return "UNKNOWN"
    if x < 85:
        return "<85"
    if x < 90:
        return "85-89.9"
    return "90-100"


def _summary(rows, key):
    groups = {}
    for r in rows:
        group = key(r)
        groups.setdefault(group, []).append(r)
    out = []
    for group, values in sorted(groups.items(), key=lambda x: str(x[0])):
        resolved = [r for r in values if r.get("first_touch") in {"EXPANSION", "FAIL"}]
        net = sum(_f(r.get("outcome_r")) or 0 for r in resolved)
        out.append((str(group), len(values), len(resolved), round(net, 6)))
    return out


def build_report(rows=None):
    rows = [r for r in (load_rows() if rows is None else rows)
            if r.get("strategy_version") == CURRENT]
    timestamps = sorted(_ts(r["timestamp"]) for r in rows if r.get("timestamp"))
    symbols = Counter(r.get("symbol", "") for r in rows)
    providers = Counter(r.get("provider", "") for r in rows)
    direction = _summary(rows, lambda r: r.get("direction", "UNKNOWN"))
    confidence = _summary(rows, lambda r: _bucket_confidence(r.get("confidence")))
    location = _summary(rows, lambda r: r.get("location_15m", "UNKNOWN"))
    reversal = _summary(rows, lambda r: r.get("reversal_5m", "UNKNOWN"))

    horizons = {}
    for h in (15, 30, 60, 120):
        key = f"h{h}"
        horizons[key] = Counter(r.get(key, "") for r in rows)

    resolved = [r for r in rows if r.get("first_touch") in {"EXPANSION", "FAIL"}]
    mfe = [_f(r.get("mfe_pct")) for r in resolved]
    mae = [_f(r.get("mae_pct")) for r in resolved]
    mfe = [x for x in mfe if x is not None]
    mae = [x for x in mae if x is not None]

    friction_fields = ("fee", "spread", "slippage", "funding", "cost_r")
    observed_friction = [f for f in friction_fields if any(_f(r.get(f)) is not None for r in rows)]

    time_buckets = Counter(
        f"{_ts(r['timestamp']).strftime('%Y-%m-%d %H')}:00"
        for r in rows if r.get("timestamp")
    )
    top_symbol_share = (symbols.most_common(1)[0][1] / len(rows)) if rows else 0.0
    top_hour_share = (time_buckets.most_common(1)[0][1] / len(rows)) if rows else 0.0

    return {
        "strategy_version": CURRENT,
        "sample_total": len(rows),
        "resolved": len(resolved),
        "unique_symbols": len([k for k in symbols if k]),
        "providers": dict(providers),
        "top_symbol": symbols.most_common(1)[0][0] if symbols else "",
        "top_symbol_share": round(top_symbol_share, 6),
        "top_time_hour": time_buckets.most_common(1)[0][0] if time_buckets else "",
        "top_time_hour_share": round(top_hour_share, 6),
        "direction": direction,
        "confidence": confidence,
        "location_15m": location,
        "reversal_5m": reversal,
        "horizons": {k: dict(v) for k, v in horizons.items()},
        "mfe_mean_pct": round(sum(mfe) / len(mfe), 6) if mfe else "",
        "mae_mean_pct": round(sum(mae) / len(mae), 6) if mae else "",
        "mfe_observed": len(mfe),
        "mae_observed": len(mae),
        "friction_status": "OBSERVED" if observed_friction else "NOT_OBSERVED",
        "friction_fields_observed": ",".join(observed_friction),
        "timestamp_start": timestamps[0].isoformat() if timestamps else "",
        "timestamp_end": timestamps[-1].isoformat() if timestamps else "",
    }


def write(rows=None, path=OUTPUT):
    report = build_report(rows)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(report))
        writer.writeheader()
        writer.writerow(report)
    return report


if __name__ == "__main__":
    report = write()
    print("SCALPING EVIDENCE AUDIT:")
    print(f"sample={report['sample_total']} resolved={report['resolved']} "
          f"symbols={report['unique_symbols']} top_symbol_share={report['top_symbol_share']:.3f} "
          f"top_hour_share={report['top_time_hour_share']:.3f} "
          f"friction={report['friction_status']}")
