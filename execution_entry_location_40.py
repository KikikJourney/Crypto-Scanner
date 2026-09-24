"""Shadow calibration for a 40-candle 5m entry-location model.

Research-only: this module does not alter live signal generation or execution.
The direction and baseline execution fields remain the scanner reference outputs.
The 40-candle model is evaluated independently for entry/stop geometry.
TP is evaluated separately as an independent 2R-8R ladder.

Model:
- use the 40 fully closed 5m candles immediately before the signal;
- LONG anchor = lowest low, planned entry slightly above that anchor;
- SHORT anchor = highest high, planned entry slightly below that anchor;
- derive the small offset from pre-signal 5m ATR (with a tiny price floor);
- derive the stop from the same anchor/buffer geometry;
- evaluate every TP level from 2R through 8R from the same filled entry and risk;
- fill only when a future candle reaches the planned entry;
- if the fill candle also touches stop/target for a given TP level, that level is
  ambiguous rather than guessing intrabar order.

No future candle is used to construct the 40-candle anchor.
"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTION_HISTORY_FILE = Path("data/scalping_action_history.csv")
MARKET_FILE = Path("data/scalping_market_5m.csv")
REPORT_FILE = Path("data/scalping_entry_location_40_report.csv")
DETAIL_FILE = Path("data/scalping_entry_location_40.csv")

CURRENT_STRATEGY_VERSION = "scalp-structure-v1"
LOOKBACK_CANDLES = 40
ATR_PERIOD = 14
ENTRY_BUFFER_ATR = 0.10
ENTRY_BUFFER_FLOOR_PCT = 0.02
MAX_RISK_PCT = 2.0
MIN_REWARD_R = 2.0
MAX_REWARD_R = 8.0
HORIZON_MINUTES = 120
MIN_SAMPLE_FOR_REVIEW = 30
REWARD_LEVELS = tuple(range(int(MIN_REWARD_R), int(MAX_REWARD_R) + 1))

REPORT_FIELDS = [
    "model", "sample", "anchored", "eligible", "filled", "resolved", "wins", "losses",
    "ambiguous", "unfilled", "rejected_geometry", "skipped", "win_rate_pct", "fill_rate_pct",
    "net_r", "expectancy_r", "max_drawdown_r", "avg_entry_improvement_pct",
    "max_risk_pct", "min_reward_r", "max_reward_r", "min_sample_for_review",
]
for level in REWARD_LEVELS:
    REPORT_FIELDS.extend([
        f"{level}r_wins", f"{level}r_losses", f"{level}r_ambiguous",
        f"{level}r_resolved", f"{level}r_net_r", f"{level}r_expectancy_r",
    ])

DETAIL_FIELDS = [
    "id", "timestamp", "symbol", "direction", "baseline_entry",
    "baseline_stop", "baseline_target", "anchor_40", "buffer",
    "planned_entry", "entry_improvement_pct", "planned_stop", "planned_target",
    "risk_pct", "reward_r", "status", "fill_timestamp", "outcome",
    "outcome_r", "outcome_timestamp", "reason",
]
for level in REWARD_LEVELS:
    DETAIL_FIELDS.extend([f"target_{level}r", f"outcome_{level}r"])


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
    return (
        _ts(row["close_timestamp"])
        if row.get("close_timestamp")
        else _ts(row["timestamp"]) + timedelta(minutes=5)
    )


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
    return (
        row.get("provider") == action.get("provider")
        and row.get("symbol") == action.get("symbol")
    )


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


def _level_summary(detail, level):
    outcome_key = f"outcome_{level}r"
    resolved = [r for r in detail if r.get(outcome_key) in {"EXPANSION", "FAIL", "AMBIGUOUS"}]
    values = [
        float(level) if r[outcome_key] == "EXPANSION"
        else -1.0 if r[outcome_key] == "FAIL"
        else 0.0
        for r in resolved
    ]
    return {
        f"{level}r_wins": sum(r[outcome_key] == "EXPANSION" for r in resolved),
        f"{level}r_losses": sum(r[outcome_key] == "FAIL" for r in resolved),
        f"{level}r_ambiguous": sum(r[outcome_key] == "AMBIGUOUS" for r in resolved),
        f"{level}r_resolved": len(resolved),
        f"{level}r_net_r": round(sum(values), 4),
        f"{level}r_expectancy_r": round(sum(values) / len(resolved), 6) if resolved else 0.0,
    }


def _summary(detail):
    anchored = [r for r in detail if r.get("anchor_40")]
    filled_statuses = {"AMBIGUOUS_FILL", "FILLED_UNRESOLVED", "RESOLVED"}
    filled = [r for r in anchored if r["status"] in filled_statuses]
    eligible = [r for r in anchored if r["status"] in {"UNFILLED", *filled_statuses}]
    resolved = [r for r in detail if r.get("outcome") in {"EXPANSION", "FAIL", "AMBIGUOUS"}]
    values = [
        2.0 if r["outcome"] == "EXPANSION"
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
    improvements = [
        _f(r["entry_improvement_pct"]) for r in filled
        if _f(r["entry_improvement_pct"]) is not None
    ]
    summary = {
        "sample": len(detail),
        "anchored": len(anchored),
        "eligible": len(eligible),
        "filled": len(filled),
        "resolved": len(resolved),
        "wins": sum(r["outcome"] == "EXPANSION" for r in resolved),
        "losses": sum(r["outcome"] == "FAIL" for r in resolved),
        "ambiguous": sum(r["outcome"] == "AMBIGUOUS" for r in resolved),
        "unfilled": sum(r["status"] == "UNFILLED" for r in detail),
        "rejected_geometry": sum(r["status"] == "REJECTED_GEOMETRY" for r in detail),
        "skipped": sum(not r.get("anchor_40") for r in detail),
        "win_rate_pct": round(
            100.0 * sum(r["outcome"] == "EXPANSION" for r in resolved) / len(resolved), 4
        ) if resolved else 0.0,
        "fill_rate_pct": round(100.0 * len(filled) / len(eligible), 4) if eligible else 0.0,
        "net_r": round(sum(values), 4),
        "expectancy_r": round(sum(values) / len(resolved), 6) if resolved else 0.0,
        "max_drawdown_r": round(drawdown, 4),
        "avg_entry_improvement_pct": round(sum(improvements) / len(improvements), 6) if improvements else 0.0,
        "max_risk_pct": MAX_RISK_PCT,
        "min_reward_r": MIN_REWARD_R,
        "max_reward_r": MAX_REWARD_R,
        "min_sample_for_review": MIN_SAMPLE_FOR_REVIEW,
    }
    for level in REWARD_LEVELS:
        summary.update(_level_summary(detail, level))
    return summary


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
            "id": action.get("id", ""),
            "timestamp": action.get("timestamp", ""),
            "symbol": action.get("symbol", ""),
            "direction": direction,
            "baseline_entry": action.get("entry", ""),
            "baseline_stop": action.get("stop", ""),
            "baseline_target": action.get("target", ""),
            "status": "SKIPPED",
        })

        if None in (baseline_entry, baseline_stop, baseline_target) or baseline_entry <= 0:
            row["reason"] = "invalid baseline execution fields"
            detail.append(row)
            continue

        pre = _pre_signal_market(action, market)
        if len(pre) < LOOKBACK_CANDLES:
            row["reason"] = "fewer than 40 fully closed 5m candles before signal"
            detail.append(row)
            continue

        window = pre[-LOOKBACK_CANDLES:]
        atr_value = _atr(window)
        lows = [_f(r.get("low")) for r in window]
        highs = [_f(r.get("high")) for r in window]
        closes = [_f(r.get("close")) for r in window]
        if atr_value is None or any(v is None for v in lows + highs + closes):
            row["reason"] = "invalid 40-candle market window"
            detail.append(row)
            continue

        current_price = closes[-1]
        anchor = min(lows) if direction == "LONG" else max(highs)
        buffer = max(
            ENTRY_BUFFER_ATR * atr_value,
            current_price * ENTRY_BUFFER_FLOOR_PCT / 100.0,
        )
        planned_entry = anchor + buffer if direction == "LONG" else anchor - buffer

        row.update({
            "anchor_40": f"{anchor:.12g}",
            "buffer": f"{buffer:.12g}",
            "planned_entry": f"{planned_entry:.12g}",
            "entry_improvement_pct": f"{(
                (baseline_entry - planned_entry) / baseline_entry * 100.0
                if direction == "LONG"
                else (planned_entry - baseline_entry) / baseline_entry * 100.0
            ): .6f}".strip(),
        })

        if direction == "LONG" and planned_entry >= current_price:
            row["status"] = "REJECTED_GEOMETRY"
            row["reason"] = "40-candle long entry is not below current price"
            detail.append(row)
            continue
        if direction == "SHORT" and planned_entry <= current_price:
            row["status"] = "REJECTED_GEOMETRY"
            row["reason"] = "40-candle short entry is not above current price"
            detail.append(row)
            continue

        planned_stop = anchor - buffer if direction == "LONG" else anchor + buffer
        risk = planned_entry - planned_stop if direction == "LONG" else planned_stop - planned_entry
        risk_pct = risk / planned_entry * 100.0 if planned_entry else None

        if risk <= 0:
            row["status"] = "REJECTED_GEOMETRY"
            row["reason"] = "non-positive 40-candle execution risk"
            detail.append(row)
            continue
        if risk_pct is None or risk_pct > MAX_RISK_PCT:
            row["status"] = "REJECTED_GEOMETRY"
            row["reason"] = "40-candle stop exceeds 2% price-distance cap"
            detail.append(row)
            continue

        targets = {
            level: (
                planned_entry + level * risk
                if direction == "LONG"
                else planned_entry - level * risk
            )
            for level in REWARD_LEVELS
        }
        row.update({
            "planned_stop": f"{planned_stop:.12g}",
            "planned_target": f"{targets[int(MIN_REWARD_R)]:.12g}",
            "risk_pct": f"{risk_pct:.6f}",
            "reward_r": f"{MIN_REWARD_R:.6f}",
        })
        for level, target in targets.items():
            row[f"target_{level}r"] = f"{target:.12g}"

        row["status"] = "UNFILLED"
        future = _future_market(action, market)
        fill_index = None

        for index, candle in enumerate(future):
            if _entry_touched(direction, candle, planned_entry):
                row["fill_timestamp"] = _close_ts(candle).isoformat()
                fill_index = index
                row["status"] = "FILLED_UNRESOLVED"
                break

        if fill_index is not None:
            # The fill candle is not orderable from OHLC alone. If it also
            # reaches the stop or any TP level, mark the fill itself ambiguous
            # instead of inventing an intrabar sequence.
            fill_candle = future[fill_index]
            fill_touches_stop = (
                (_f(fill_candle.get("low")) is not None and _f(fill_candle.get("low")) <= planned_stop)
                if direction == "LONG"
                else (_f(fill_candle.get("high")) is not None and _f(fill_candle.get("high")) >= planned_stop)
            )
            fill_touches_target = any(
                (
                    _f(fill_candle.get("high")) is not None
                    and _f(fill_candle.get("high")) >= target
                )
                if direction == "LONG"
                else (
                    _f(fill_candle.get("low")) is not None
                    and _f(fill_candle.get("low")) <= target
                )
                for target in targets.values()
            )
            fill_ambiguous = fill_touches_stop or fill_touches_target
            row["status"] = "AMBIGUOUS_FILL" if fill_ambiguous else "RESOLVED"
            if fill_ambiguous:
                row["outcome"] = "AMBIGUOUS"
                row["outcome_timestamp"] = _close_ts(fill_candle).isoformat()
                row["reason"] = "fill candle also touched stop or target; intrabar order is unknowable"

            # Each TP level is an independent measurement using the same entry/SL.
            # This avoids coupling a 2R result to the 3R-8R ladder.
            unresolved = set(REWARD_LEVELS)
            for candle in future[fill_index + 1:]:
                if not unresolved:
                    break
                for level in tuple(unresolved):
                    outcome = _touch(direction, candle, planned_stop, targets[level])
                    if outcome:
                        row[f"outcome_{level}r"] = outcome
                        unresolved.remove(level)
                        if level == int(MIN_REWARD_R):
                            row["outcome"] = outcome
                            row["outcome_r"] = (
                                str(float(level)) if outcome == "EXPANSION"
                                else "-1.0" if outcome == "FAIL"
                                else ""
                            )
                            row["outcome_timestamp"] = _close_ts(candle).isoformat()

            if unresolved:
                row["reason"] = "horizon ended before all TP levels resolved"
            elif row["outcome"] == "AMBIGUOUS":
                row["status"] = "RESOLVED"
            else:
                row["status"] = "RESOLVED"

        detail.append(row)

    return detail


def write(detail=None):
    detail = calibrate() if detail is None else detail
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    summary = _summary(detail)
    report = {"model": "ENTRY_40C_5M_GEOMETRY_SHADOW", **summary}
    with REPORT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerow(report)
    with DETAIL_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(detail)
    return summary


if __name__ == "__main__":
    result = write()
    print(
        "40-candle entry shadow: "
        f"anchored={result['anchored']} eligible={result['eligible']} filled={result['filled']} "
        f"resolved={result['resolved']} wins={result['wins']} "
        f"losses={result['losses']} net_r={result['net_r']:.2f} "
        f"expectancy_r={result['expectancy_r']:.4f}"
    )
