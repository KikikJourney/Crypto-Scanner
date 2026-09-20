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
from scalping_forward_test import evaluate as evaluate_scalping, format_summary as scalping_summary, archive_actions as archive_scalping_actions, archive_market_candles as archive_scalping_market
from scalping_intelligence import _timestamp as mtf_timestamp
from early_reversal_engine import infer_direction as infer_early_reversal_direction
from signal_funnel_diagnostic import diagnose as diagnose_signal_funnel, write as write_signal_funnel

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
    "id", "timestamp", "scan_timestamp", "symbol", "provider", "direction", "score",
    "v2_score", "confidence", "location_15m", "reversal_5m", "entry", "entry_low", "entry_high", "trigger",
    "stop", "target", "risk_pct", "reward_r", "valid_until", "latest_closed_5m_timestamp", "latest_closed_15m_timestamp",
    "data_age_seconds", "timeframes", "rsi_5m", "trend_4h", "trend_1h", "structure_30m",
    "structure_15m", "liquidity_sweep_5m", "volume_5m",
    "exhaustion_15m", "base_15m", "structure_shift_5m",
    "reversal_trigger_5m", "early_reversal_score", "reason",
]


def _normalize_bitget_mtf_candles(raw, interval_minutes, limit=194):
    """Normalize Bitget MTF candles to ascending, closed-only chronological order.

    Bitget can return candle arrays in an order that must not be assumed by the
    strategy. The previous implementation blindly reversed raw[1:], which is
    only correct for a newest-first response. When the response is oldest-first,
    that transformation makes rows[-1] approximately one full requested page
    behind the live market (about 48h for 194 x 15m candles).
    """
    if not isinstance(raw, list):
        raise RuntimeError("Bitget candle response is not a list")

    def ts_ms(row):
        try:
            value = float(row[0])
            return int(value if value > 10_000_000_000 else value * 1000)
        except (TypeError, ValueError, IndexError):
            return None

    rows = [row for row in raw if isinstance(row, (list, tuple)) and len(row) >= 6]
    rows.sort(key=lambda row: ts_ms(row) if ts_ms(row) is not None else -1)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    interval_ms = interval_minutes * 60 * 1000
    closed = [
        row for row in rows
        if ts_ms(row) is not None and ts_ms(row) + interval_ms <= now_ms
    ]
    if len(closed) < limit:
        raise RuntimeError(
            f"Bitget {interval_minutes}m candle response has only "
            f"{len(closed)} closed candles; need {limit}"
        )
    return closed[-limit:]


def _rows(sym, provider):
    if provider == "Bitget":
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        raw = core.bitget(
            "/api/v2/mix/market/candles",
            {
                "symbol": sym,
                "productType": "USDT-FUTURES",
                "granularity": "15m",
                "limit": 200,
                "endTime": str(now_ms),
            },
        )["data"]
        return _normalize_bitget_mtf_candles(raw, 15)
    if provider == "Bybit":
        raw = core.bybit(
            "/v5/market/kline",
            {"category": "linear", "symbol": sym, "interval": "15", "limit": 195},
        )["result"]["list"]
        return core.normalize_bybit_candles(raw)
    return core.binance(
        "/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 195}
    )[:-1]


def _rows_5m(sym, provider):
    if provider == "Bitget":
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        raw = core.bitget(
            "/api/v2/mix/market/candles",
            {
                "symbol": sym,
                "productType": "USDT-FUTURES",
                "granularity": "5m",
                "limit": 200,
                "endTime": str(now_ms),
            },
        )["data"]
        return _normalize_bitget_mtf_candles(raw, 5)
    if provider == "Bybit":
        raw = core.bybit(
            "/v5/market/kline",
            {"category": "linear", "symbol": sym, "interval": "5", "limit": 195},
        )["result"]["list"]
        return core.normalize_bybit_candles(raw)
    return core.binance(
        "/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 195}
    )[:-1]


def scan_one(sym, provider, btc24):
    scan_started = datetime.now(timezone.utc)
    result = core.fetch_symbol(sym, provider, btc24)
    rows = _rows(sym, provider)
    features = build_features(rows, result["price"])
    result["extreme_features"] = features
    result["scan_timestamp"] = scan_started.isoformat()
    result["scalping_rows_15m"] = rows
    result["scalping_rows_5m"] = _rows_5m(sym, provider)
    # Execution signals must be built from genuinely recent closed candles.
    # A stale MTF feed can produce mathematically valid but operationally wrong prices.
    now = datetime.now(timezone.utc)
    for label, candle_rows, interval_minutes, max_age_minutes in (
        ("15m", rows, 15, 30),
        ("5m", result["scalping_rows_5m"], 5, 10),
    ):
        if not candle_rows:
            raise RuntimeError(f"{label} candle feed empty")
        last = mtf_timestamp(candle_rows[-1])
        if last is None:
            raise RuntimeError(f"{label} candle timestamp unavailable")
        age = (now - last).total_seconds() / 60.0
        if age > max_age_minutes or age < -interval_minutes:
            raise RuntimeError(
                f"{label} candle feed stale: latest={last.isoformat()} age={age:.1f}m"
            )
    result["extreme"] = classify(features)
    return result


def _mtf_action(x, timestamp):
    timestamp = x.get("scan_timestamp", timestamp)
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
    latest5 = plan.get("latest_closed_5m_timestamp", "")
    latest15 = plan.get("latest_closed_15m_timestamp", "")
    data_age = ""
    try:
        data_age = round((datetime.fromisoformat(timestamp.replace("Z", "+00:00")) - datetime.fromisoformat(latest5.replace("Z", "+00:00"))).total_seconds(), 3)
    except (TypeError, ValueError):
        pass
    return {
        "id": f'{x["provider"]}_{timestamp}_{x["symbol"]}_{plan["direction"]}_{plan["entry"]}',
        "timestamp": timestamp,
        "scan_timestamp": timestamp,
        "symbol": x["symbol"],
        "provider": x["provider"],
        "direction": plan["direction"],
        "score": plan["v2_score"],
        "v2_score": plan["v2_score"],
        "confidence": plan["confidence"],
        "location_15m": plan["location_15m"],
        "reversal_5m": plan["reversal_5m"],
        "entry": plan["entry"],
        "entry_low": plan["entry_low"],
        "entry_high": plan["entry_high"],
        "trigger": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"],
        "risk_pct": plan["risk_pct"],
        "reward_r": plan["reward_r"],
        "valid_until": _issue_valid_until(timestamp),
        "latest_closed_5m_timestamp": latest5,
        "latest_closed_15m_timestamp": latest15,
        "data_age_seconds": data_age,
        "timeframes": plan["timeframes"],
        "rsi_5m": plan["rsi_5m"],
        "trend_4h": plan["trend_4h"],
        "trend_1h": plan["trend_1h"],
        "structure_30m": plan["structure_30m"],
        "structure_15m": plan["structure_15m"],
        "liquidity_sweep_5m": plan["liquidity_sweep_5m"],
        "volume_5m": plan["volume_5m"],
        "exhaustion_15m": plan.get("exhaustion_15m", 0.0),
        "base_15m": plan.get("base_15m", 0.0),
        "structure_shift_5m": plan.get("structure_shift_5m", 0.0),
        "reversal_trigger_5m": plan.get("reversal_trigger_5m", plan.get("reversal_5m", 0.0)),
        "early_reversal_score": plan.get("early_reversal_score", 0.0),
        "reason": plan["reason"],
    }


def _write_actionable(rows):
    ACTIONABLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ACTIONABLE_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ACTIONABLE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _brain_action(x, timestamp):
    timestamp = x.get("scan_timestamp", timestamp)
    rows_5m = x["scalping_rows_5m"]
    # Primary execution path: detect the reversal while price is still near
    # the extreme/base. Do not require the preceding trend to have already
    # flipped; that would systematically make the scanner late.
    direction = infer_early_reversal_direction(x["scalping_rows_15m"], rows_5m)
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
        early_reversal=True,
    )
    if plan["status"] not in {"ACTION LONG", "ACTION SHORT"}:
        return None
    latest5 = plan.get("latest_closed_5m_timestamp", "")
    latest15 = plan.get("latest_closed_15m_timestamp", "")
    data_age = ""
    try:
        data_age = round((datetime.fromisoformat(timestamp.replace("Z", "+00:00")) - datetime.fromisoformat(latest5.replace("Z", "+00:00"))).total_seconds(), 3)
    except (TypeError, ValueError):
        pass
    return {
        "id": f'{x["provider"]}_{timestamp}_{x["symbol"]}_{plan["direction"]}_{plan["entry"]}',
        "timestamp": timestamp,
        "scan_timestamp": timestamp,
        "symbol": x["symbol"],
        "provider": x["provider"],
        "direction": plan["direction"],
        "score": plan["v2_score"],
        "v2_score": plan["v2_score"],
        "confidence": plan["confidence"],
        "location_15m": plan["location_15m"],
        "reversal_5m": plan["reversal_5m"],
        "entry": plan["entry"],
        "entry_low": plan["entry_low"],
        "entry_high": plan["entry_high"],
        "trigger": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"],
        "risk_pct": plan["risk_pct"],
        "reward_r": plan["reward_r"],
        "valid_until": _issue_valid_until(timestamp),
        "latest_closed_5m_timestamp": latest5,
        "latest_closed_15m_timestamp": latest15,
        "data_age_seconds": data_age,
        "timeframes": plan["timeframes"],
        "rsi_5m": plan["rsi_5m"],
        "trend_4h": plan["trend_4h"],
        "trend_1h": plan["trend_1h"],
        "structure_30m": plan["structure_30m"],
        "structure_15m": plan["structure_15m"],
        "liquidity_sweep_5m": plan["liquidity_sweep_5m"],
        "volume_5m": plan["volume_5m"],
        "exhaustion_15m": plan.get("exhaustion_15m", 0.0),
        "base_15m": plan.get("base_15m", 0.0),
        "structure_shift_5m": plan.get("structure_shift_5m", 0.0),
        "reversal_trigger_5m": plan.get("reversal_trigger_5m", plan.get("reversal_5m", 0.0)),
        "early_reversal_score": plan.get("early_reversal_score", 0.0),
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
    return actions

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

    scalping_actions = _print_action_candidates(results, timestamp)
    archived_actions = archive_scalping_actions(scalping_actions)
    archived_candles = archive_scalping_market(results)
    print(f"Scalping action history added: {archived_actions}")
    print(f"Scalping 5m candles archived: {archived_candles}")

    # Diagnostic-only funnel: explains exactly where scanned symbols are filtered out.
    funnel_summary, funnel_rows = diagnose_signal_funnel(
        results, errors, len(symbols), len(scan_symbols), provider, timestamp
    )
    write_signal_funnel(funnel_summary, funnel_rows)
    print(
        "SIGNAL FUNNEL: "
        f"universe={funnel_summary['universe']} | "
        f"deep_scan={funnel_summary['deep_scan']} | "
        f"data_valid={funnel_summary['data_valid']} | "
        f"errors={funnel_summary['data_errors']} | "
        f"LONG={funnel_summary['direction_long']} | "
        f"SHORT={funnel_summary['direction_short']} | "
        f"no_direction={funnel_summary['no_direction']} | "
        f"alignment_failed={funnel_summary['alignment_failed']} | "
        f"confidence_failed={funnel_summary['confidence_failed']} | "
        f"risk_failed={funnel_summary['risk_failed']} | "
        f"actions={funnel_summary['actions']}"
    )

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
