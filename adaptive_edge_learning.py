"""Outcome-driven adaptive gating for Alpha Edge signals.

The learner evaluates paper-signal outcomes from closed 5m OHLC candles.
It only blocks a direction/regime cohort after a minimum resolved sample with
non-positive expectancy. It never changes SL/TP geometry, leverage, or live
exchange orders. Results are estimates before fees and slippage.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

STATE_VERSION = 1
HORIZON_MINUTES = 120
MIN_SAMPLE_FOR_POLICY = 30
MAX_OBSERVATIONS = 1000
MAX_PENDING = 500
BINANCE_KLINES_URL = os.getenv("BINANCE_KLINES_URL", "https://fapi.binance.com/fapi/v1/klines")


def _number(value):
    try:
        value = float(value)
        return value if value == value and abs(value) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _iso(value):
    return _timestamp(value).astimezone(timezone.utc).isoformat()


def cohort_key(signal):
    direction = str(signal.get("direction", "")).upper()
    regime = signal.get("regime") or {}
    regime_type = str(regime.get("type", "UNKNOWN") if isinstance(regime, dict) else regime).upper()
    return f"{direction}|{regime_type}"


def signal_key(signal, scan_timestamp=None):
    symbol = str(signal.get("symbol_full") or signal.get("symbol") or "").upper()
    direction = str(signal.get("direction") or "").upper()
    entry = _number(signal.get("entry"))
    timestamp = signal.get("timestamp") or scan_timestamp
    if not symbol or direction not in {"LONG", "SHORT"} or entry is None or not timestamp:
        return ""
    return f"{symbol}|{direction}|{entry:.10g}|{_iso(timestamp)}"


def initial_state():
    return {"version": STATE_VERSION, "pending": [], "observations": [], "seen": []}


def resolve_signal(signal, candles, now=None):
    """Resolve a hypothetical limit entry using chronological closed candles."""
    now = _timestamp(now or datetime.now(timezone.utc).isoformat())
    try:
        created = _timestamp(signal["timestamp"])
    except (KeyError, TypeError, ValueError):
        return {"outcome": "INVALID", "outcome_r": None, "reason": "invalid signal timestamp"}

    direction = str(signal.get("direction", "")).upper()
    entry = _number(signal.get("entry"))
    stop = _number(signal.get("stop"))
    target = _number(signal.get("tp1"))
    if target is None:
        target = _number(signal.get("target"))
    if direction not in {"LONG", "SHORT"} or None in (entry, stop, target) or entry <= 0:
        return {"outcome": "INVALID", "outcome_r": None, "reason": "invalid signal geometry"}
    risk = entry - stop if direction == "LONG" else stop - entry
    reward = target - entry if direction == "LONG" else entry - target
    if risk <= 0 or reward <= 0:
        return {"outcome": "INVALID", "outcome_r": None, "reason": "invalid directional risk/reward"}

    ordered = []
    for candle in candles or []:
        try:
            ts = _timestamp(candle.get("timestamp"))
            high, low = _number(candle.get("high")), _number(candle.get("low"))
        except (TypeError, ValueError):
            continue
        if ts <= created or ts + timedelta(minutes=5) > now or high is None or low is None:
            continue
        ordered.append((ts, high, low))
    ordered.sort(key=lambda item: item[0])

    filled = False
    fill_timestamp = ""
    for ts, high, low in ordered:
        if not filled:
            # Do not assume a limit filled unless the candle traded through it.
            if not (low <= entry <= high):
                continue
            filled = True
            fill_timestamp = ts.isoformat()
        favorable = high >= target if direction == "LONG" else low <= target
        adverse = low <= stop if direction == "LONG" else high >= stop
        if favorable and adverse:
            return {"outcome": "AMBIGUOUS", "outcome_r": 0.0, "filled": True,
                    "fill_timestamp": fill_timestamp, "outcome_timestamp": ts.isoformat(),
                    "reason": "stop and target touched in the same 5m candle"}
        if adverse:
            return {"outcome": "LOSS", "outcome_r": -1.0, "filled": True,
                    "fill_timestamp": fill_timestamp, "outcome_timestamp": ts.isoformat(),
                    "reason": "structural stop touched"}
        if favorable:
            return {"outcome": "WIN", "outcome_r": round(reward / risk, 6), "filled": True,
                    "fill_timestamp": fill_timestamp, "outcome_timestamp": ts.isoformat(),
                    "reason": "TP1 touched"}

    deadline = created + timedelta(minutes=HORIZON_MINUTES)
    if now < deadline:
        return {"outcome": "PENDING", "outcome_r": None, "filled": filled,
                "fill_timestamp": fill_timestamp, "reason": "waiting for fill or resolution"}
    if not filled:
        return {"outcome": "NO_FILL", "outcome_r": None, "filled": False,
                "reason": "entry was not traded within the observation horizon"}
    return {"outcome": "EXPIRED", "outcome_r": None, "filled": True,
            "fill_timestamp": fill_timestamp, "reason": "filled but neither SL nor TP1 touched within horizon"}


def derive_policy(observations, min_sample=MIN_SAMPLE_FOR_POLICY):
    """Create a conservative cohort policy from resolved, filled paper outcomes."""
    cohorts = {}
    for row in observations or []:
        cohort = str(row.get("cohort") or "")
        outcome = str(row.get("outcome") or "").upper()
        value = _number(row.get("outcome_r"))
        if not cohort or outcome not in {"WIN", "LOSS"} or value is None:
            continue
        cohorts.setdefault(cohort, []).append(value)

    policy = {"version": STATE_VERSION, "min_sample": int(min_sample), "cohorts": {}}
    for cohort, values in cohorts.items():
        values = values[-60:]
        if len(values) < min_sample:
            continue
        expectancy = sum(values) / len(values)
        policy["cohorts"][cohort] = {
            "sample": len(values),
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "win_rate_pct": round(100 * sum(value > 0 for value in values) / len(values), 2),
            "expectancy_r": round(expectancy, 6),
            "decision": "BLOCK" if expectancy <= 0 else "ALLOW",
            "basis": "last up to 60 resolved filled paper outcomes; before fees/slippage",
        }
    return policy


def apply_policy(results, policy):
    """Filter only cohorts with enough observed evidence of non-positive expectancy."""
    kept, blocked = [], []
    cohorts = (policy or {}).get("cohorts", {})
    for signal in results or []:
        key = cohort_key(signal)
        rule = cohorts.get(key, {})
        if rule.get("decision") == "BLOCK":
            row = dict(signal)
            row["adaptive_learning"] = {
                "decision": "BLOCK",
                "cohort": key,
                "sample": rule.get("sample", 0),
                "expectancy_r": rule.get("expectancy_r"),
                "reason": "sufficient resolved history shows non-positive expectancy",
            }
            blocked.append(row)
        else:
            kept.append(signal)
    return kept, blocked


def _fetch_candles(symbol, start_time):
    """Fetch public Binance Futures 5m candles; unavailable data leaves the signal pending."""
    start_ms = int(_timestamp(start_time).timestamp() * 1000)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    response = requests.get(
        BINANCE_KLINES_URL,
        params={"symbol": symbol, "interval": "5m", "startTime": start_ms, "endTime": end_ms, "limit": 1000},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("unexpected Binance kline response")
    return [
        {"timestamp": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).isoformat(),
         "high": _number(row[2]), "low": _number(row[3]), "close": _number(row[4])}
        for row in payload if isinstance(row, list) and len(row) >= 5
    ]


def process(result, state=None, candle_fetcher=None, now=None):
    """Resolve previous signals, update bounded learning state, and filter current results."""
    now = _timestamp(now or datetime.now(timezone.utc).isoformat())
    state = dict(initial_state() if not state else state)
    pending = list(state.get("pending") or [])
    observations = list(state.get("observations") or [])
    seen_order = list(state.get("seen") or [])
    seen = set(seen_order)
    candle_fetcher = candle_fetcher or _fetch_candles

    symbols = {}
    for item in pending:
        symbol = str(item.get("symbol_full") or item.get("symbol") or "").upper()
        if symbol:
            try:
                started = _timestamp(item["timestamp"])
                if symbol not in symbols or started < _timestamp(symbols[symbol]):
                    symbols[symbol] = started.isoformat()
            except (KeyError, TypeError, ValueError):
                continue

    candles_by_symbol = {}
    for symbol, started in symbols.items():
        try:
            candles_by_symbol[symbol] = candle_fetcher(symbol, started)
        except Exception as exc:
            print(f"ADAPTIVE_EDGE_DATA_UNAVAILABLE symbol={symbol} reason={type(exc).__name__}")

    still_pending = []
    resolved_now = 0
    for item in pending:
        symbol = str(item.get("symbol_full") or item.get("symbol") or "").upper()
        if symbol not in candles_by_symbol:
            try:
                expired = now >= _timestamp(item["timestamp"]) + timedelta(minutes=HORIZON_MINUTES)
            except (KeyError, TypeError, ValueError):
                expired = True
            if not expired:
                still_pending.append(item)
            else:
                print(f"ADAPTIVE_EDGE_EXPIRED_DATA_UNAVAILABLE symbol={symbol}")
            continue
        outcome = resolve_signal(item, candles_by_symbol[symbol], now=now)
        if outcome["outcome"] == "PENDING":
            still_pending.append(item)
        elif outcome["outcome"] in {"WIN", "LOSS", "AMBIGUOUS", "NO_FILL", "EXPIRED"}:
            row = dict(item)
            row.update(outcome)
            row["cohort"] = cohort_key(item)
            row["resolved_at"] = now.isoformat()
            if outcome["outcome"] in {"WIN", "LOSS"}:
                observations.append(row)
            resolved_now += 1
            print(f"ADAPTIVE_EDGE_OUTCOME symbol={symbol} cohort={row['cohort']} outcome={outcome['outcome']} r={outcome.get('outcome_r')}")
        else:
            still_pending.append(item)

    raw_results = list(result.get("results") or [])
    scan_timestamp = result.get("timestamp") or now.isoformat()
    added = 0
    for signal in raw_results:
        key = signal_key(signal, scan_timestamp)
        if not key or key in seen:
            continue
        row = dict(signal)
        row["timestamp"] = _iso(signal.get("timestamp") or scan_timestamp)
        row["id"] = key
        row["cohort"] = cohort_key(row)
        still_pending.append(row)
        seen.add(key)
        seen_order.append(key)
        added += 1

    observations = observations[-MAX_OBSERVATIONS:]
    still_pending = still_pending[-MAX_PENDING:]
    seen_order = list(dict.fromkeys(seen_order))[-MAX_PENDING * 4:]
    seen = set(seen_order)
    policy = derive_policy(observations)
    kept, blocked = apply_policy(raw_results, policy)
    updated_result = dict(result)
    updated_result["results"] = kept
    updated_result["adaptive_learning"] = {
        "mode": "bounded_outcome_learning",
        "observations": len(observations),
        "pending_signals": len(still_pending),
        "resolved_this_run": resolved_now,
        "new_signals_tracked": added,
        "cohorts_with_sufficient_sample": len(policy["cohorts"]),
        "blocked_this_run": len(blocked),
        "blocked_cohorts": [key for key, value in policy["cohorts"].items() if value["decision"] == "BLOCK"],
        "policy": policy,
        "limitations": "Paper-signal OHLC estimates; no fee/slippage modeling; ambiguous same-candle touches excluded; policy changes only after minimum sample.",
    }
    next_state = {
        "version": STATE_VERSION,
        "pending": still_pending,
        "observations": observations,
        "seen": seen_order,
        "updated_at": now.isoformat(),
        "policy": policy,
    }
    return updated_result, next_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".adaptive-edge/state.json")
    parser.add_argument("--result", default="scanner_result.json")
    args = parser.parse_args()
    state_path, result_path = Path(args.state), Path(args.result)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else initial_state()
    except (OSError, json.JSONDecodeError):
        state = initial_state()
    updated, next_state = process(result, state=state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(next_state, indent=2, ensure_ascii=False), encoding="utf-8")
    result_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    info = updated["adaptive_learning"]
    print("ADAPTIVE_EDGE_SUMMARY " + json.dumps({
        "observations": info["observations"], "pending": info["pending_signals"],
        "resolved_this_run": info["resolved_this_run"], "new_tracked": info["new_signals_tracked"],
        "cohorts_ready": info["cohorts_with_sufficient_sample"], "blocked": info["blocked_this_run"],
        "blocked_cohorts": info["blocked_cohorts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
