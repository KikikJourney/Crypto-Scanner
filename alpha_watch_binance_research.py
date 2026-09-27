"""Historical Binance validation for Alpha Watch -> calibrated entry -> outcome.

Research-only: never creates Telegram actions and never changes production gates.
It reconstructs the Alpha Hunter discovery state on closed Binance 5m candles,
then measures whether the calibrated 100-candle entry is reached and what
happens afterward. Results are intentionally kept separate from Bitget legacy
execution evidence.
"""
import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import alpha_hunter

FUNNEL_FILE = Path("data/signal_funnel_symbols.csv")
DETAIL_FILE = Path("data/alpha_watch_binance_research.csv")
REPORT_FILE = Path("data/alpha_watch_binance_research_report.csv")
INTERVAL_MS = 5 * 60 * 1000
LOOKBACK_DAYS = int(os.getenv("ALPHA_RESEARCH_DAYS", "7"))
MAX_SYMBOLS = int(os.getenv("ALPHA_RESEARCH_MAX_SYMBOLS", "124"))
MAX_WORKERS = int(os.getenv("ALPHA_RESEARCH_WORKERS", "8"))
HORIZON_BARS = int(os.getenv("ALPHA_RESEARCH_HORIZON_BARS", "24"))

DETAIL_FIELDS = [
    "id","symbol","watch_timestamp","direction","confidence","watch_entry",
    "watch_stop","watch_target","entry_distance_atr","entry_anchor_100",
    "atr_pct","location_15m","participation","entry_touch","entry_touch_timestamp",
    "bars_to_entry","mfe_pct_after_entry","mae_pct_after_entry",
    "first_outcome","outcome_timestamp","outcome_r","reason",
]
REPORT_FIELDS = [
    "provider","status","reason","sample_watch_events","entry_touches","unfilled",
    "resolved_after_touch","wins","losses","ambiguous",
    "fill_rate_pct","win_rate_pct","avg_bars_to_entry",
    "avg_mfe_pct","avg_mae_pct","net_r","expectancy_r",
    "horizon_bars","lookback_days","symbols","fetch_errors",
]

S = requests.Session()
S.headers.update({"User-Agent": "Zorathvael-Alpha-Watch-Research/1.0"})
BASES = [
    "https://fapi.binance.com", "https://fapi1.binance.com",
    "https://fapi2.binance.com", "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]


def _request_klines(symbol, start_ms, end_ms):
    last = None
    for base in BASES:
        try:
            out = []
            cursor = start_ms
            while cursor < end_ms:
                r = S.get(
                    base + "/fapi/v1/klines",
                    params={"symbol": symbol, "interval": "5m",
                            "startTime": cursor, "endTime": end_ms, "limit": 1500},
                    timeout=20,
                )
                if r.status_code in (429, 418) or r.status_code >= 500:
                    raise RuntimeError(f"HTTP {r.status_code}")
                r.raise_for_status()
                batch = r.json()
                if not batch:
                    break
                out.extend(batch)
                last_open = int(batch[-1][0])
                next_cursor = last_open + INTERVAL_MS
                if next_cursor <= cursor:
                    break
                cursor = next_cursor
                if len(batch) < 1500:
                    break
                time.sleep(0.05)
            return out
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Binance kline fetch failed for {symbol}: {last}")


def _row(k):
    return [int(k[0]), k[1], float(k[2]), float(k[3]), float(k[4]), float(k[5])]


def _aggregate_15m(rows):
    out = []
    usable = len(rows) - len(rows) % 3
    for i in range(0, usable, 3):
        g = rows[i:i + 3]
        out.append([g[0][0], g[0][1], max(x[2] for x in g),
                    min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)])
    return out


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _watch_symbols():
    if not FUNNEL_FILE.exists():
        raise RuntimeError("signal_funnel_symbols.csv missing")
    with FUNNEL_FILE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    candidates = [
        r for r in rows
        if r.get("provider") == "Binance"
        and r.get("stage") == "ALPHA_WATCH"
        and r.get("direction") in {"LONG", "SHORT"}
    ]
    # Keep the latest/highest-confidence current watch universe. This is a
    # deliberate research cohort, not a production selection rule.
    candidates.sort(key=lambda r: float(r.get("confidence") or 0), reverse=True)
    return candidates[:MAX_SYMBOLS]


def _outcome(direction, entry, stop, target, future):
    touch_i = None
    for i, c in enumerate(future):
        high, low = c[2], c[3]
        touched = low <= entry <= high
        if touched:
            touch_i = i
            break
    if touch_i is None:
        return None, None, None, None, None, "UNFILLED"

    post = future[touch_i:touch_i + HORIZON_BARS]
    if not post:
        return touch_i, future[touch_i][0], None, None, None, "UNRESOLVED"

    mfe = 0.0
    mae = 0.0
    outcome = None
    outcome_i = None
    for i, c in enumerate(post):
        high, low = c[2], c[3]
        if direction == "LONG":
            mfe = max(mfe, (high - entry) / entry * 100.0)
            mae = min(mae, (low - entry) / entry * 100.0)
            tp = high >= target
            sl = low <= stop
        else:
            mfe = max(mfe, (entry - low) / entry * 100.0)
            mae = min(mae, (entry - high) / entry * 100.0)
            tp = low <= target
            sl = high >= stop
        if tp and sl:
            outcome, outcome_i = "AMBIGUOUS", i
            break
        if tp:
            outcome, outcome_i = "WIN", i
            break
        if sl:
            outcome, outcome_i = "LOSS", i
            break
    return (
        touch_i, post[0][0], mfe, mae,
        post[outcome_i][0] if outcome_i is not None else None,
        outcome or "OPEN",
    )


def _evaluate_symbol(symbol, watch_rows, candles):
    rows5 = [_row(k) for k in candles]
    rows15 = _aggregate_15m(rows5)
    by_time = {r[0]: i for i, r in enumerate(rows5)}
    results = []

    for watch in watch_rows:
        try:
            ts = datetime.fromisoformat(watch["timestamp"].replace("Z", "+00:00"))
            ts_ms = int(ts.timestamp() * 1000)
            idx5 = max((i for i, r in enumerate(rows5) if r[0] <= ts_ms), default=-1)
            idx15 = max((i for i, r in enumerate(rows15) if r[0] <= ts_ms), default=-1)
            if idx5 < 99 or idx15 < 159:
                continue
            # Alpha Hunter requires the fully closed 5m/15m context at the
            # observation time. Rebuild that exact historical state.
            h5 = rows5[:idx5 + 1]
            h15 = rows15[:idx15 + 1]
            plan = alpha_hunter.build_discovery_plan(h15, h5)
            if plan.get("direction") != watch["direction"]:
                continue
            if not str(plan.get("status", "")).startswith("ALPHA WATCH"):
                continue
            future = rows5[idx5 + 1:]
            entry = float(plan["entry"])
            stop = float(plan["stop"])
            target = float(plan["target"])
            touch_i, touch_ts, mfe, mae, outcome_ts, outcome = _outcome(
                plan["direction"], entry, stop, target, future
            )
            bars = touch_i + 1 if touch_i is not None else ""
            outcome_r = ""
            if outcome == "WIN":
                risk = abs(entry - stop)
                reward = abs(target - entry)
                outcome_r = reward / risk if risk > 0 else ""
            elif outcome == "LOSS":
                outcome_r = -1.0
            elif outcome == "AMBIGUOUS":
                outcome_r = 0.0
            results.append({
                "id": f"BINANCE_WATCH_{symbol}_{watch['timestamp']}_{plan['direction']}",
                "symbol": symbol, "watch_timestamp": watch["timestamp"],
                "direction": plan["direction"], "confidence": plan.get("confidence", ""),
                "watch_entry": entry, "watch_stop": stop, "watch_target": target,
                "entry_distance_atr": plan.get("entry_distance_atr", ""),
                "entry_anchor_100": plan.get("entry_anchor_100", ""),
                "atr_pct": plan.get("atr_pct", ""),
                "location_15m": plan.get("location_15m", ""),
                "participation": plan.get("participation", ""),
                "entry_touch": "TOUCHED" if touch_i is not None else "UNFILLED",
                "entry_touch_timestamp": _iso(touch_ts) if touch_ts else "",
                "bars_to_entry": bars,
                "mfe_pct_after_entry": mfe if mfe is not None else "",
                "mae_pct_after_entry": mae if mae is not None else "",
                "first_outcome": outcome or "",
                "outcome_timestamp": _iso(outcome_ts) if outcome_ts else "",
                "outcome_r": outcome_r,
                "reason": "historical Binance reconstruction",
            })
        except Exception as exc:
            results.append({
                "id": f"ERROR_{symbol}_{watch.get('timestamp','')}",
                "symbol": symbol, "watch_timestamp": watch.get("timestamp",""),
                "direction": watch.get("direction",""), "confidence": watch.get("confidence",""),
                "watch_entry":"","watch_stop":"","watch_target":"",
                "entry_distance_atr":"","entry_anchor_100":"","atr_pct":"",
                "location_15m":"","participation":"","entry_touch":"",
                "entry_touch_timestamp":"","bars_to_entry":"",
                "mfe_pct_after_entry":"","mae_pct_after_entry":"",
                "first_outcome":"","outcome_timestamp":"","outcome_r":"",
                "reason": f"reconstruction error: {exc}",
            })
    return results


def _write_status_report(status, reason, *, symbols=0, fetch_errors=0):
    """Persist a machine-readable non-fatal research status."""
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Keep the detail artifact present even when Binance is unavailable so
    # workflow persistence can distinguish "no evidence" from a missing file.
    with DETAIL_FILE.open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=DETAIL_FIELDS).writeheader()
    report = {
        "provider": "Binance", "status": status, "reason": reason,
        "sample_watch_events": 0, "entry_touches": 0, "unfilled": 0,
        "resolved_after_touch": 0, "wins": 0, "losses": 0, "ambiguous": 0,
        "fill_rate_pct": 0, "win_rate_pct": 0, "avg_bars_to_entry": 0,
        "avg_mfe_pct": 0, "avg_mae_pct": 0, "net_r": 0, "expectancy_r": 0,
        "horizon_bars": HORIZON_BARS, "lookback_days": LOOKBACK_DAYS,
        "symbols": symbols, "fetch_errors": fetch_errors,
    }
    with REPORT_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        w.writeheader()
        w.writerow(report)
    print("Alpha Watch Binance research status:", report)
    return report


def run():
    try:
        watches = _watch_symbols()
    except Exception as exc:
        return _write_status_report("NO_COHORT", str(exc))
    if not watches:
        return _write_status_report(
            "NO_COHORT",
            "No current Binance ALPHA_WATCH cohort was emitted by the scanner.",
        )
    grouped = {}
    for row in watches:
        grouped.setdefault(row["symbol"], []).append(row)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    fetched = {}
    errors = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_request_klines, symbol,
                        int(start.timestamp() * 1000), int(end.timestamp() * 1000)): symbol
            for symbol in grouped
        }
        for fut in as_completed(futures):
            symbol = futures[fut]
            try:
                fetched[symbol] = fut.result()
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")

    details = []
    for symbol, watch_rows in grouped.items():
        if symbol in fetched:
            details.extend(_evaluate_symbol(symbol, watch_rows, fetched[symbol]))

    if not details:
        reason = (
            "Binance historical data unavailable for the current cohort."
            if errors
            else "Binance research produced no reconstructable watch events."
        )
        return _write_status_report(
            "DATA_UNAVAILABLE" if errors else "NO_RECONSTRUCTABLE_EVENTS",
            reason, symbols=len(grouped), fetch_errors=len(errors),
        )

    DETAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DETAIL_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        w.writeheader()
        w.writerows(details)

    touched = [r for r in details if r["entry_touch"] == "TOUCHED"]
    resolved = [r for r in touched if r["first_outcome"] in {"WIN","LOSS","AMBIGUOUS"}]
    wins = [r for r in resolved if r["first_outcome"] == "WIN"]
    losses = [r for r in resolved if r["first_outcome"] == "LOSS"]
    ambiguous = [r for r in resolved if r["first_outcome"] == "AMBIGUOUS"]
    bars = [float(r["bars_to_entry"]) for r in touched if str(r["bars_to_entry"]).strip()]
    mfe = [float(r["mfe_pct_after_entry"]) for r in touched if str(r["mfe_pct_after_entry"]).strip()]
    mae = [float(r["mae_pct_after_entry"]) for r in touched if str(r["mae_pct_after_entry"]).strip()]
    values = [float(r["outcome_r"]) for r in resolved if str(r["outcome_r"]).strip()]
    report = {
        "provider":"Binance", "status":"OK", "reason":"historical Binance reconstruction",
        "sample_watch_events":len(details),
        "entry_touches":len(touched), "unfilled":sum(r["entry_touch"]=="UNFILLED" for r in details),
        "resolved_after_touch":len(resolved), "wins":len(wins), "losses":len(losses),
        "ambiguous":len(ambiguous),
        "fill_rate_pct":round(100*len(touched)/len(details),4) if details else 0,
        "win_rate_pct":round(100*len(wins)/len(resolved),4) if resolved else 0,
        "avg_bars_to_entry":round(sum(bars)/len(bars),3) if bars else 0,
        "avg_mfe_pct":round(sum(mfe)/len(mfe),5) if mfe else 0,
        "avg_mae_pct":round(sum(mae)/len(mae),5) if mae else 0,
        "net_r":round(sum(values),5), "expectancy_r":round(sum(values)/len(values),6) if values else 0,
        "horizon_bars":HORIZON_BARS, "lookback_days":LOOKBACK_DAYS,
        "symbols":len(grouped), "fetch_errors":len(errors),
    }
    with REPORT_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        w.writeheader()
        w.writerow(report)
    print("Alpha Watch Binance research:", report)
    if errors:
        print("Fetch errors:", len(errors), errors[:10])
    return report


if __name__ == "__main__":
    run()
