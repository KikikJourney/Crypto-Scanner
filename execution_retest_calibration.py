"""Shadow retest execution calibration for scalping actions.

This is research-only. It does not alter live signal, entry, stop, or target rules.
Model:
1) wait for the first fully closed 5m confirmation candle preserving direction;
2) after confirmation, wait for a later closed candle to retest the confirmation
   close and close back in the signal direction;
3) enter at that retest close;
4) derive stop from the retest candle and original stop, capped at 2% risk;
5) target = 2R from the actual retest entry;
6) resolve only on candles strictly after the retest candle.
"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTION_HISTORY_FILE = Path("data/scalping_action_history.csv")
MARKET_FILE = Path("data/scalping_market_5m.csv")
REPORT_FILE = Path("data/scalping_execution_retest_report.csv")
DETAIL_FILE = Path("data/scalping_execution_retest.csv")
STRATEGY_VERSION = "scalp-structure-v1"
HORIZON_MINUTES = 120
MAX_RISK_PCT = 2.0
REWARD_R = 2.0
MIN_SAMPLE_FOR_REVIEW = 30

REPORT_FIELDS = ["model","sample","eligible","resolved","wins","losses","ambiguous","unresolved","skipped","win_rate_pct","net_r","expectancy_r","max_drawdown_r","max_risk_pct","min_sample_for_review"]
DETAIL_FIELDS = ["id","timestamp","symbol","direction","confirmation_timestamp","confirmation_close","retest_timestamp","retest_close","calibrated_entry","calibrated_stop","calibrated_target","risk_pct","status","outcome","outcome_r","outcome_timestamp","reason"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts(v):
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _load(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _close_ts(row):
    return _ts(row["close_timestamp"]) if row.get("close_timestamp") else _ts(row["timestamp"]) + timedelta(minutes=5)


def _future(action, market):
    start = _ts(action["timestamp"])
    end = start + timedelta(minutes=HORIZON_MINUTES)
    return [
        r for r in market
        if r.get("provider") == action.get("provider")
        and r.get("symbol") == action.get("symbol")
        and start < _ts(r["timestamp"])
        and _close_ts(r) <= end
    ]


def _touch(direction, candle, stop, target):
    high, low = _f(candle.get("high")), _f(candle.get("low"))
    stop, target = _f(stop), _f(target)
    if None in (high, low, stop, target):
        return None
    favorable = high >= target if direction == "LONG" else low <= target
    adverse = low <= stop if direction == "LONG" else high >= stop
    if favorable and adverse:
        return "AMBIGUOUS"
    if favorable:
        return "EXPANSION"
    if adverse:
        return "FAIL"
    return None


def calibrate(actions=None, market_rows=None):
    actions = _load(ACTION_HISTORY_FILE) if actions is None else actions
    market = _load(MARKET_FILE) if market_rows is None else market_rows
    actions = [r for r in actions if r.get("strategy_version") == STRATEGY_VERSION and r.get("direction") in {"LONG", "SHORT"}]
    market = sorted(market, key=lambda r: _ts(r["timestamp"]))
    detail = []

    for action in sorted(actions, key=lambda r: r.get("timestamp", "")):
        row = {k: "" for k in DETAIL_FIELDS}
        row.update({"id": action.get("id", ""), "timestamp": action.get("timestamp", ""), "symbol": action.get("symbol", ""), "direction": action.get("direction", ""), "status": "SKIPPED"})
        candles = _future(action, market)
        if len(candles) < 2:
            row["reason"] = "insufficient future closed candles"
            detail.append(row)
            continue

        direction = action["direction"]
        entry0, stop0, close0 = _f(action.get("entry")), _f(action.get("stop")), _f(candles[0].get("close"))
        if None in (entry0, stop0, close0):
            row["reason"] = "invalid numeric execution fields"
            detail.append(row)
            continue

        confirmed = close0 >= entry0 if direction == "LONG" else close0 <= entry0
        if not confirmed:
            row["reason"] = "first closed 5m confirmation did not preserve direction"
            detail.append(row)
            continue

        confirmation = candles[0]
        confirmation_close = close0
        if _touch(direction, confirmation, _f(action.get("stop")), _f(action.get("target"))):
            row.update({
                "confirmation_timestamp": _close_ts(confirmation).isoformat(),
                "confirmation_close": f"{confirmation_close:.12g}",
                "reason": "confirmation candle already touched original stop/target",
            })
            detail.append(row)
            continue
        retest = None
        for candle in candles[1:]:
            high, low, close = _f(candle.get("high")), _f(candle.get("low")), _f(candle.get("close"))
            if None in (high, low, close):
                continue
            touched = low <= confirmation_close <= high
            preserved = close >= entry0 if direction == "LONG" else close <= entry0
            if touched and preserved:
                retest = candle
                break

        if retest is None:
            row.update({"confirmation_timestamp": _close_ts(confirmation).isoformat(), "confirmation_close": f"{confirmation_close:.12g}", "reason": "no closed-candle retest within 120m"})
            detail.append(row)
            continue

        retest_close = _f(retest.get("close"))
        retest_low, retest_high = _f(retest.get("low")), _f(retest.get("high"))
        if None in (retest_close, retest_low, retest_high):
            row["reason"] = "invalid retest candle"
            detail.append(row)
            continue

        entry = retest_close
        stop = min(stop0, retest_low) if direction == "LONG" else max(stop0, retest_high)
        risk = entry - stop if direction == "LONG" else stop - entry
        if risk <= 0:
            row["reason"] = "non-positive retest risk"
            detail.append(row)
            continue
        risk_pct = risk / entry * 100
        row.update({
            "confirmation_timestamp": _close_ts(confirmation).isoformat(),
            "confirmation_close": f"{confirmation_close:.12g}",
            "retest_timestamp": _close_ts(retest).isoformat(),
            "retest_close": f"{retest_close:.12g}",
            "calibrated_entry": f"{entry:.12g}",
            "calibrated_stop": f"{stop:.12g}",
            "risk_pct": f"{risk_pct:.6f}",
        })
        if risk_pct > MAX_RISK_PCT:
            row.update({"reason": "retest stop exceeds 2% risk cap", "status": "SKIPPED"})
            detail.append(row)
            continue

        target = entry + REWARD_R * risk if direction == "LONG" else entry - REWARD_R * risk
        row.update({"calibrated_target": f"{target:.12g}", "status": "ELIGIBLE_UNRESOLVED", "reason": "confirmed then retested"})
        retest_index = candles.index(retest)
        for candle in candles[retest_index + 1:]:
            outcome = _touch(direction, candle, stop, target)
            if outcome:
                row.update({
                    "status": "RESOLVED",
                    "outcome": outcome,
                    "outcome_r": "2.0" if outcome == "EXPANSION" else "-1.0" if outcome == "FAIL" else "",
                    "outcome_timestamp": _close_ts(candle).isoformat(),
                })
                break
        detail.append(row)
    return detail


def _summary(detail):
    resolved = [r for r in detail if r["outcome"] in {"EXPANSION", "FAIL", "AMBIGUOUS"}]
    vals = [2.0 if r["outcome"] == "EXPANSION" else -1.0 if r["outcome"] == "FAIL" else 0.0 for r in resolved]
    eq = peak = dd = 0.0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {
        "sample": len(detail),
        "eligible": sum(r["status"] != "SKIPPED" for r in detail),
        "resolved": len(resolved),
        "wins": sum(r["outcome"] == "EXPANSION" for r in resolved),
        "losses": sum(r["outcome"] == "FAIL" for r in resolved),
        "ambiguous": sum(r["outcome"] == "AMBIGUOUS" for r in resolved),
        "unresolved": sum(r["status"] == "ELIGIBLE_UNRESOLVED" for r in detail),
        "skipped": sum(r["status"] == "SKIPPED" for r in detail),
        "win_rate_pct": round(100 * sum(r["outcome"] == "EXPANSION" for r in resolved) / len(resolved), 4) if resolved else 0.0,
        "net_r": round(sum(vals), 4),
        "expectancy_r": round(sum(vals) / len(resolved), 6) if resolved else 0.0,
        "max_drawdown_r": round(dd, 4),
        "max_risk_pct": MAX_RISK_PCT,
        "min_sample_for_review": MIN_SAMPLE_FOR_REVIEW,
    }


def write(detail=None):
    detail = calibrate() if detail is None else detail
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    s = _summary(detail)
    with REPORT_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        w.writeheader()
        w.writerow({"model": "CONFIRM_RETEST_5M_SHADOW", **s})
    with DETAIL_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        w.writeheader()
        w.writerows(detail)
    return s


if __name__ == "__main__":
    s = write()
    print(f"Execution retest shadow: eligible={s['eligible']} resolved={s['resolved']} wins={s['wins']} losses={s['losses']} net_r={s['net_r']:.2f} expectancy_r={s['expectancy_r']:.4f}")
