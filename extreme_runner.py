"""V2.2 scanner runner with a dedicated multi-timeframe scalping execution engine."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import csv
from pathlib import Path

import scanner_v2 as core
from universe_runner import active_symbols, select_scan_symbols
from extreme_market_data import build_features
from extreme_reversal_layer import (
    classify, append_rows, append_snapshots, evaluate_forward,
    signal_row, snapshot_row,
)
from extreme_event_stats import format_summary
from scalping_execution_layer import build_plan as legacy_scalping_plan
from scalping_intelligence import build_plan as mtf_scalping_plan
from scalping_forward_test import evaluate as evaluate_scalping, format_summary as scalping_summary

WORKERS = 8
ACTIONABLE_FILE = Path("data/actionable_signals.csv")
def _issue_valid_until(timestamp):
    """Give each newly issued action a fresh 15-minute delivery window."""
    try:
        issued = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return (issued + timedelta(minutes=15)).isoformat()
    except ValueError:
        return timestamp


ACTIONABLE_FIELDS = [
    "id", "timestamp", "symbol", "provider", "direction", "score",
    "confidence", "entry", "entry_low", "entry_high", "trigger",
    "stop", "target", "risk_pct", "reward_r", "valid_until",
    "timeframes", "rsi_5m", "trend_4h", "trend_1h", "structure_30m",
    "structure_15m", "liquidity_sweep_5m", "volume_5m", "reason",
]


def _rows(sym, provider):
    if provider == "Bitget":
        raw = core.bitget(
            "/api/v2/mix/market/candles",
            {"symbol": sym, "productType": "USDT-FUTURES", "granularity": "15m", "limit": 194},
        )["data"]
        return core.normalize_bitget_candles(raw)
    if provider == "Bybit":
        raw = core.bybit(
            "/v5/market/kline",
            {"category": "linear", "symbol": sym, "interval": "15", "limit": 194},
        )["result"]["list"]
        return core.normalize_bybit_candles(raw)
    return core.binance(
        "/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 194}
    )[:-1]


def _rows_5m(sym, provider):
    if provider == "Bitget":
        raw = core.bitget(
            "/api/v2/mix/market/candles",
            {"symbol": sym, "productType": "USDT-FUTURES", "granularity": "5m", "limit": 194},
        )["data"]
        return core.normalize_bitget_candles(raw)
    if provider == "Bybit":
        raw = core.bybit(
            "/v5/market/kline",
            {"category": "linear", "symbol": sym, "interval": "5", "limit": 194},
        )["result"]["list"]
        return core.normalize_bybit_candles(raw)
    return core.binance(
        "/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 194}
    )[:-1]


def scan_one(sym, provider, btc24):
    result = core.fetch_symbol(sym, provider, btc24)
    rows = _rows(sym, provider)
    features = build_features(rows, result["price"])
    result["extreme_features"] = features
    result["scalping_rows_15m"] = rows
    result["scalping_rows_5m"] = _rows_5m(sym, provider)
    result["extreme"] = classify(features)
    return result


def _mtf_action(x, timestamp):
    extreme = x["extreme"]
    if not extreme["status"].startswith("EXTREME REVERSAL"):
        return None
    rows_5m = x["scalping_rows_5m"]
    plan = mtf_scalping_plan(
        extreme["direction"],
        x["scalping_rows_15m"],
        rows_5m,
        extreme["score"],
        x["extreme_features"],
        require_v2_direction=True,
    )
    if plan["status"] not in {"ACTION LONG", "ACTION SHORT"}:
        return None
    p = plan
    return {
        "id": f'{x["provider"]}_{timestamp}_{x["symbol"]}_{plan["direction"]}_{plan["entry"]}',
        "timestamp": timestamp,
        "symbol": x["symbol"],
        "provider": x["provider"],
        "direction": plan["direction"],
        "score": plan["v2_score"],
        "confidence": plan["confidence"],
        "entry": plan["entry"],
        "entry_low": plan["entry_low"],
        "entry_high": plan["entry_high"],
        "trigger": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"],
        "risk_pct": plan["risk_pct"],
        "reward_r": plan["reward_r"],
        "valid_until": _issue_valid_until(timestamp),
        "timeframes": plan["timeframes"],
        "rsi_5m": plan["rsi_5m"],
        "trend_4h": plan["trend_4h"],
        "trend_1h": plan["trend_1h"],
        "structure_30m": plan["structure_30m"],
        "structure_15m": plan["structure_15m"],
        "liquidity_sweep_5m": plan["liquidity_sweep_5m"],
        "volume_5m": plan["volume_5m"],
        "reason": plan["reason"],
    }


def _write_actionable(rows):
    ACTIONABLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ACTIONABLE_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ACTIONABLE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _brain_action(x, timestamp):
    rows_5m = x["scalping_rows_5m"]
    direction = __import__("scalping_intelligence", fromlist=["infer_direction"]).infer_direction(
        x["scalping_rows_15m"], rows_5m
    )
    if not direction:
        return None
    extreme = x["extreme"]
    v2_bonus_score = (
        extreme["score"]
        if extreme["status"].startswith("EXTREME REVERSAL")
        and extreme["direction"] == direction
        else 0.0
    )
    plan = mtf_scalping_plan(
        direction,
        x["scalping_rows_15m"],
        rows_5m,
        v2_bonus_score,
        x["extreme_features"],
        require_v2_direction=False,
    )
    if plan["status"] not in {"ACTION LONG", "ACTION SHORT"}:
        return None
    return {
        "id": f'{x["provider"]}_{timestamp}_{x["symbol"]}_{plan["direction"]}_{plan["entry"]}',
        "timestamp": timestamp,
        "symbol": x["symbol"],
        "provider": x["provider"],
        "direction": plan["direction"],
        "score": plan["v2_score"],
        "confidence": plan["confidence"],
        "entry": plan["entry"],
        "entry_low": plan["entry_low"],
        "entry_high": plan["entry_high"],
        "trigger": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"],
        "risk_pct": plan["risk_pct"],
        "reward_r": plan["reward_r"],
        "valid_until": plan["valid_until"],
        "timeframes": plan["timeframes"],
        "rsi_5m": plan["rsi_5m"],
        "trend_4h": plan["trend_4h"],
        "trend_1h": plan["trend_1h"],
        "structure_30m": plan["structure_30m"],
        "structure_15m": plan["structure_15m"],
        "liquidity_sweep_5m": plan["liquidity_sweep_5m"],
        "volume_5m": plan["volume_5m"],
        "reason": plan["reason"],
    }


def _print_action_candidates(results, timestamp):
    print("SCALPING BRAIN OUTPUT:")
    actions = []
    for x in results:
        try:
            action = _brain_action(x, timestamp)
        except Exception as exc:
            action = None
            print(f'{x["symbol"]} | DATA-LIMITED | brain error: {exc}')
        if action:
            actions.append(action)
            print(
                f'{x["symbol"]} | ACTION {action["direction"]} | '
                f'confidence {action["confidence"]} | entry {action["entry_low"]}-{action["entry_high"]} | '
                f'SL {action["stop"]} | TP {action["target"]} | RR {action["reward_r"]}'
            )
    actions.sort(key=lambda r: float(r["confidence"]), reverse=True)
    actions = actions[:20]
    _write_actionable(actions)
    print(f"Confirmed MTF scalping brain actions: {len(actions)}")

def _load_forward_rows():
    from extreme_reversal_layer import EXTREME_FORWARD_FILE
    with EXTREME_FORWARD_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    provider, btc24 = core.discover()
    symbols = active_symbols(provider)
    scan_symbols, liquid_n, mover_n = select_scan_symbols(provider, symbols)
    print(
        f"Extreme scan universe: {len(symbols)} active {provider} USDT perpetual symbols"
    )
    print(
        f"Extreme deep scan: {len(scan_symbols)} symbols | "
        f"liquidity bucket={liquid_n} | mover bucket={mover_n} | workers={WORKERS}"
    )

    results, errors = [], []
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(scan_symbols))) as executor:
        futures = {
            executor.submit(scan_one, symbol, provider, btc24): symbol
            for symbol in scan_symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append((symbol, str(exc)))

    results.sort(
        key=lambda x: x["extreme"]["score"] if x["extreme"]["score"] is not None else -1,
        reverse=True,
    )
    timestamp = datetime.now(timezone.utc).isoformat()

    # Historical V2.2 accounting remains intact.
    added = append_rows([
        signal_row(
            x,
            x["extreme_features"],
            timestamp,
            legacy_scalping_plan(
                x["extreme_features"],
                x["scalping_rows_15m"],
                x["extreme"]["direction"],
            ),
        )
        for x in results
    ])
    snapshot_added = append_snapshots([
        snapshot_row(x, x["extreme_features"], timestamp) for x in results
    ])

    extreme = [
        x for x in results
        if x["extreme"]["status"].startswith("EXTREME REVERSAL")
    ]
    print("TOP EXTREME CANDIDATES:")
    if not extreme:
        print("NONE — no true-extreme reversal passed the V2.2 gate")
    for rank, x in enumerate(extreme[:20], 1):
        e, f = x["extreme"], x["extreme_features"]
        print(
            f'{rank}. {x["symbol"]} | {e["status"]} | score {e["score"]:.1f} | '
            f'24hPos {f["h1_pos_24"]:.2f} | 48hPos {f["h1_pos_48"]:.2f} | '
            f'lowDist {f["dist_low_atr"]:.2f}ATR | highDist {f["dist_high_atr"]:.2f}ATR'
        )

    _print_action_candidates(results, timestamp)

    print(f"Extreme scan coverage: {len(results)}/{len(scan_symbols)}")
    if errors:
        print(f"Extreme symbol errors: {len(errors)}")
        for symbol, error in errors[:10]:
            print(f" - {symbol}: {error}")

    print(f"Extreme market snapshots added: {snapshot_added}")
    print(f"Extreme forward-test outcomes updated: {evaluate_forward()}")
    print(f"Extreme forward-test rows added: {added}")
    print(format_summary(_load_forward_rows()))

    scalping = evaluate_scalping()
    print(scalping_summary(scalping))


if __name__ == "__main__":
    main()
