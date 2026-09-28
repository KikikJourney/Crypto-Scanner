"""100-candle 5m execution shadow model.

Research-only. The 100-candle anchor is an entry-location/timing model:
- LONG anchor = lowest low of the 100 fully closed pre-signal candles.
- SHORT anchor = highest high of the 100 fully closed pre-signal candles.
- Entry uses a small ATR-aware buffer inside the extreme.
- Stop uses a larger ATR-aware noise buffer beyond the same extreme.
- TP is ALWAYS the action's structural target. No synthetic R ladder is used.
- Realized R is measured from the recalibrated entry -> stop -> structural target.
- OHLC ambiguity is never resolved by guessing intrabar order.

This module is deliberately independent from live signal generation.
"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from margin_risk_model import DEFAULT_LEVERAGE, DEFAULT_MARGIN_USDT, MAX_MARGIN_LOSS_PCT, MIN_MARGIN_TP_PCT, MAX_MARGIN_TP_PCT, TP1_MARGIN_PCT, target_margin_pct_from_price, stop_margin_pct_from_price, build_margin_plan
from entry_calibration import calibrate_entry
from entry_geometry import build_anchor_stop, build_entry_geometry

ACTION_HISTORY_FILE = Path("data/scalping_action_history.csv")
MARKET_FILE = Path("data/scalping_market_5m.csv")
REPORT_FILE = Path("data/scalping_entry_location_100_report.csv")
DETAIL_FILE = Path("data/scalping_entry_location_100.csv")

CURRENT_STRATEGY_VERSION = "scalp-structure-v1"
LOOKBACK_CANDLES = 100
ATR_PERIOD = 14
ENTRY_BUFFER_ATR = 0.25
ENTRY_BUFFER_FLOOR_PCT = 0.02
STOP_BUFFER_ATR = 0.45
STOP_BUFFER_FLOOR_PCT = 0.08
MAX_RISK_PCT = MAX_MARGIN_LOSS_PCT
MIN_TP_MARGIN_PCT = MIN_MARGIN_TP_PCT
MAX_TP_MARGIN_PCT = MAX_MARGIN_TP_PCT
# Backward-compatible report aliases; values now represent margin ROI bands.
MIN_REWARD_R = MIN_TP_MARGIN_PCT
MAX_REWARD_R = MAX_TP_MARGIN_PCT

HORIZON_MINUTES = 120
MIN_SAMPLE_FOR_REVIEW = 30

REPORT_FIELDS = [
    "model", "sample", "anchored", "eligible", "filled", "resolved", "wins", "losses",
    "ambiguous", "unfilled", "rejected_geometry", "skipped", "win_rate_pct", "fill_rate_pct",
    "net_r", "expectancy_r", "max_drawdown_r", "avg_entry_improvement_pct",
    "max_risk_pct", "min_reward_r", "max_reward_r", "min_sample_for_review",
]

DETAIL_FIELDS = [
    "id", "timestamp", "symbol", "direction", "baseline_entry", "baseline_stop",
    "baseline_target", "anchor_100", "entry_buffer", "stop_buffer", "planned_entry",
    "entry_improvement_pct", "planned_stop", "planned_target", "risk_pct", "reward_r",
    "stop_margin_pct", "tp_margin_pct", "status", "fill_timestamp", "outcome", "outcome_r", "outcome_timestamp", "reason",
]


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ts(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _load(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _close_ts(row):
    if row.get("close_timestamp"):
        return _ts(row["close_timestamp"])
    return _ts(row["timestamp"]) + timedelta(minutes=5)


def _atr(rows, period=ATR_PERIOD):
    if len(rows) < period:
        return None
    trs = []
    previous = None
    for row in rows:
        high, low, close = _f(row.get("high")), _f(row.get("low")), _f(row.get("close"))
        if None in (high, low, close):
            return None
        tr = high - low if previous is None else max(
            high - low, abs(high - previous), abs(low - previous)
        )
        trs.append(tr)
        previous = close
    return sum(trs[-period:]) / period


def _same_market(row, action):
    return row.get("provider") == action.get("provider") and row.get("symbol") == action.get("symbol")


def _pre_signal_market(action, market):
    signal_ts = _ts(action["timestamp"])
    rows = [
        row for row in market
        if _same_market(row, action) and _close_ts(row) <= signal_ts
    ]
    return sorted(rows, key=lambda r: _close_ts(r))


def _future_market(action, market):
    signal_ts = _ts(action["timestamp"])
    deadline = signal_ts + timedelta(minutes=HORIZON_MINUTES)
    return [
        row for row in sorted(market, key=lambda r: _ts(r["timestamp"]))
        if _same_market(row, action)
        and _ts(row["timestamp"]) > signal_ts
        and _close_ts(row) <= deadline
    ]


def _touch(direction, candle, stop, target):
    high, low = _f(candle.get("high")), _f(candle.get("low"))
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


def _entry_touched(direction, candle, entry):
    high, low = _f(candle.get("high")), _f(candle.get("low"))
    if None in (high, low, entry):
        return False
    return low <= entry if direction == "LONG" else high >= entry


def _geometry(direction, anchor, current_price, atr_value):
    """Compose research calibration + geometry without mixing responsibilities."""
    # The anchor/current price are already selected by the calibration layer.
    calibrated = {
        "anchor": anchor,
        "entry": (
            anchor + max(ENTRY_BUFFER_ATR * atr_value, current_price * ENTRY_BUFFER_FLOOR_PCT / 100.0)
            if direction == "LONG"
            else anchor - max(ENTRY_BUFFER_ATR * atr_value, current_price * ENTRY_BUFFER_FLOOR_PCT / 100.0)
        ),
        "current_price": current_price,
    }
    stop = build_anchor_stop(
        direction, anchor, current_price, atr_value,
        stop_buffer_atr=STOP_BUFFER_ATR,
        stop_floor_pct=STOP_BUFFER_FLOOR_PCT,
    )
    # Research shadow geometry is intentionally isolated from the live
    # 10USDT/20x/10% contract so historical evidence remains comparable.
    legacy_stop_margin_pct = 5.0
    legacy_leverage = 25.0
    geometry = build_margin_plan(
        direction,
        calibrated["entry"],
        DEFAULT_MARGIN_USDT,
        legacy_leverage,
        legacy_stop_margin_pct,
        TP1_MARGIN_PCT,
    )
    return calibrated["entry"], geometry["stop"], abs(calibrated["entry"] - anchor), abs(calibrated["entry"] - geometry["stop"])

def _summary(detail):
    anchored = [r for r in detail if r.get("anchor_100")]
    filled_statuses = {"AMBIGUOUS_FILL", "FILLED_UNRESOLVED", "RESOLVED"}
    filled = [r for r in anchored if r["status"] in filled_statuses]
    eligible = [r for r in anchored if r["status"] in {"UNFILLED", *filled_statuses}]
    resolved = [r for r in detail if r.get("outcome") in {"EXPANSION", "FAIL", "AMBIGUOUS"}]
    values = [
        _f(r.get("outcome_r")) if r["outcome"] == "EXPANSION"
        else -1.0 if r["outcome"] == "FAIL"
        else 0.0
        for r in resolved
    ]
    equity = peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    improvements = [_f(r["entry_improvement_pct"]) for r in filled if _f(r["entry_improvement_pct"]) is not None]
    return {
        "sample": len(detail), "anchored": len(anchored), "eligible": len(eligible),
        "filled": len(filled), "resolved": len(resolved),
        "wins": sum(r["outcome"] == "EXPANSION" for r in resolved),
        "losses": sum(r["outcome"] == "FAIL" for r in resolved),
        "ambiguous": sum(r["outcome"] == "AMBIGUOUS" for r in resolved),
        "unfilled": sum(r["status"] == "UNFILLED" for r in detail),
        "rejected_geometry": sum(r["status"] == "REJECTED_GEOMETRY" for r in detail),
        "skipped": sum(not r.get("anchor_100") for r in detail),
        "win_rate_pct": round(100.0 * sum(r["outcome"] == "EXPANSION" for r in resolved) / len(resolved), 4) if resolved else 0.0,
        "fill_rate_pct": round(100.0 * len(filled) / len(eligible), 4) if eligible else 0.0,
        "net_r": round(sum(values), 4),
        "expectancy_r": round(sum(values) / len(resolved), 6) if resolved else 0.0,
        "max_drawdown_r": round(drawdown, 4),
        "avg_entry_improvement_pct": round(sum(improvements) / len(improvements), 6) if improvements else 0.0,
        "max_risk_pct": MAX_RISK_PCT, "min_reward_r": MIN_REWARD_R,
        "max_reward_r": MAX_REWARD_R, "min_sample_for_review": MIN_SAMPLE_FOR_REVIEW,
    }


def calibrate(actions=None, market_rows=None):
    actions = _load(ACTION_HISTORY_FILE) if actions is None else actions
    market = _load(MARKET_FILE) if market_rows is None else market_rows
    actions = [
        row for row in actions
        if row.get("strategy_version") == CURRENT_STRATEGY_VERSION
        and row.get("direction") in {"LONG", "SHORT"}
    ]
    detail = []

    for action in sorted(actions, key=lambda r: r.get("timestamp", "")):
        direction = action["direction"]
        baseline_entry = _f(action.get("entry"))
        baseline_stop = _f(action.get("stop"))
        baseline_target = _f(action.get("target"))
        row = {field: "" for field in DETAIL_FIELDS}
        row.update({
            "id": action.get("id", ""), "timestamp": action.get("timestamp", ""),
            "symbol": action.get("symbol", ""), "direction": direction,
            "baseline_entry": action.get("entry", ""), "baseline_stop": action.get("stop", ""),
            "baseline_target": action.get("target", ""), "status": "SKIPPED",
        })

        if None in (baseline_entry, baseline_stop, baseline_target) or baseline_entry <= 0:
            row["reason"] = "invalid baseline execution fields"
            detail.append(row)
            continue

        pre = _pre_signal_market(action, market)
        if len(pre) < LOOKBACK_CANDLES:
            row["reason"] = "fewer than 100 fully closed 5m candles before signal"
            detail.append(row)
            continue

        window = pre[-LOOKBACK_CANDLES:]
        atr_value = _atr(window)
        lows = [_f(r.get("low")) for r in window]
        highs = [_f(r.get("high")) for r in window]
        closes = [_f(r.get("close")) for r in window]
        if atr_value is None or any(v is None for v in lows + highs + closes):
            row["reason"] = "invalid 100-candle market window"
            detail.append(row)
            continue

        current_price = closes[-1]
        anchor = min(lows) if direction == "LONG" else max(highs)
        planned_entry, planned_stop, entry_buffer, stop_buffer = _geometry(
            direction, anchor, current_price, atr_value
        )
        row.update({
            "anchor_100": f"{anchor:.12g}", "entry_buffer": f"{entry_buffer:.12g}",
            "stop_buffer": f"{stop_buffer:.12g}", "planned_entry": f"{planned_entry:.12g}",
            "entry_improvement_pct": f"{((baseline_entry - planned_entry) / baseline_entry * 100.0 if direction == 'LONG' else (planned_entry - baseline_entry) / baseline_entry * 100.0):.6f}",
        })

        if direction == "LONG" and planned_entry >= current_price:
            row["status"], row["reason"] = "REJECTED_GEOMETRY", "100-candle long entry is not below current price"
            detail.append(row)
            continue
        if direction == "SHORT" and planned_entry <= current_price:
            row["status"], row["reason"] = "REJECTED_GEOMETRY", "100-candle short entry is not above current price"
            detail.append(row)
            continue

        risk = planned_entry - planned_stop if direction == "LONG" else planned_stop - planned_entry
        risk_pct = risk / planned_entry * 100.0 if planned_entry else None
        stop_margin_pct = stop_margin_pct_from_price(planned_entry, planned_stop, direction, DEFAULT_LEVERAGE) if planned_entry else None
        if risk <= 0 or risk_pct is None:
            row["status"], row["reason"] = "REJECTED_GEOMETRY", "non-positive execution risk"
            detail.append(row)
            continue
        geometry_repairs = []
        if stop_margin_pct > MAX_MARGIN_LOSS_PCT:
            repaired = build_entry_geometry(direction, planned_entry)
            planned_stop = repaired["stop"]
            risk = planned_entry - planned_stop if direction == "LONG" else planned_stop - planned_entry
            risk_pct = risk / planned_entry * 100.0
            stop_margin_pct = repaired["stop_margin_pct"]
            geometry_repairs.append("stop_to_canonical_risk")

        target = baseline_target
        reward_r = abs((target - planned_entry) / risk) if risk > 0 else 0.0
        tp_margin_pct = target_margin_pct_from_price(planned_entry, target, direction, DEFAULT_LEVERAGE)
        direction_valid = (
            (direction == "LONG" and target > planned_entry)
            or (direction == "SHORT" and target < planned_entry)
        )
        target_valid = direction_valid and MIN_TP_MARGIN_PCT <= tp_margin_pct <= MAX_TP_MARGIN_PCT
        if not target_valid:
            repaired = build_entry_geometry(
                direction, planned_entry, selected_tp_margin_pct=MIN_TP_MARGIN_PCT
            )
            target = repaired["target"]
            tp_margin_pct = repaired["tp_margin_pct"]
            geometry_repairs.append("target_to_canonical_min_tp")

        reward_r = abs((target - planned_entry) / risk) if risk > 0 else 0.0
        row.update({
            "planned_stop": f"{planned_stop:.12g}", "planned_target": f"{target:.12g}",
            "risk_pct": f"{risk_pct:.6f}", "reward_r": f"{reward_r:.6f}",
            "stop_margin_pct": f"{stop_margin_pct:.6f}", "tp_margin_pct": f"{tp_margin_pct:.6f}",
            "status": "UNFILLED",
            "reason": ";".join(geometry_repairs),
        })

        future = _future_market(action, market)
        fill_index = next((i for i, candle in enumerate(future) if _entry_touched(direction, candle, planned_entry)), None)
        if fill_index is None:
            detail.append(row)
            continue

        fill_candle = future[fill_index]
        row["fill_timestamp"] = _close_ts(fill_candle).isoformat()
        fill_touch = _touch(direction, fill_candle, planned_stop, target)
        if fill_touch:
            row["status"], row["outcome"] = "AMBIGUOUS_FILL", "AMBIGUOUS"
            row["outcome_timestamp"] = _close_ts(fill_candle).isoformat()
            row["reason"] = "fill candle also touched stop or target; intrabar order is unknowable"
            detail.append(row)
            continue

        row["status"] = "FILLED_UNRESOLVED"
        for candle in future[fill_index + 1:]:
            outcome = _touch(direction, candle, planned_stop, target)
            if outcome:
                row["status"], row["outcome"] = "RESOLVED", outcome
                row["outcome_r"] = f"{reward_r:.6f}" if outcome == "EXPANSION" else "-1.0" if outcome == "FAIL" else ""
                row["outcome_timestamp"] = _close_ts(candle).isoformat()
                break
        if row["status"] == "FILLED_UNRESOLVED":
            row["reason"] = "horizon ended before structural target or stop resolved"
        detail.append(row)

    return detail


def write(detail=None):
    detail = calibrate() if detail is None else detail
    summary = _summary(detail)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerow({"model": "ENTRY_100C_5M_GEOMETRY_SHADOW", **summary})
    with DETAIL_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(detail)
    return summary


if __name__ == "__main__":
    result = write()
    print(
        "100-candle structural shadow: "
        f"sample={result['sample']} anchored={result['anchored']} eligible={result['eligible']} "
        f"filled={result['filled']} resolved={result['resolved']} wins={result['wins']} "
        f"losses={result['losses']} ambiguous={result['ambiguous']} net_r={result['net_r']:.2f} "
        f"expectancy_r={result['expectancy_r']:.4f}"
    )
