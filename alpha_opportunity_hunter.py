"""Independent futures opportunity hunter.

Purpose: detect actionable *potential* before reversal confirmation. This is
intentionally separate from scanner_v2.py and the existing reversal engine.

It scans Bitget USDT perpetuals, ranks volatility/volume expansion, directional
momentum, breakout/pullback structure and mean-reversion extremes. It never
modifies production scanner decisions.
"""
from __future__ import annotations
import csv, math, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE = "https://api.bitget.com"
PRODUCT = "USDT-FUTURES"
OUT = Path("data/alpha_opportunity_watch.csv")
TIMEOUT = 10
WORKERS = 8
MIN_QUOTE_VOLUME = 1_000_000.0
MAX_SYMBOLS = 250

S = requests.Session()
S.headers.update({"User-Agent": "Zorathvael-Alpha-Opportunity-Hunter/2.0"})

FIELDS = [
    "timestamp","symbol","price","direction","state","alpha_score",
    "return_15m","return_1h","atr_pct","range_pos","volume_ratio",
    "breakout","pullback","momentum","mean_reversion","reason"
]

def get(path, params=None, retries=3):
    last = None
    for attempt in range(retries + 1):
        try:
            r = S.get(BASE + path, params=params, timeout=TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}")
                if attempt < retries:
                    time.sleep(min(4.0, 0.5 * (2 ** attempt)))
                    continue
            r.raise_for_status()
            data = r.json()
            if str(data.get("code")) not in {"00000", "0", "None"} and data.get("code") is not None:
                raise RuntimeError(f"Bitget {data.get('code')}: {data.get('msg')}")
            return data
        except (requests.RequestException, RuntimeError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(min(4.0, 0.5 * (2 ** attempt)))
    raise last or RuntimeError("request failed")

def f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default

def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))

def candles(symbol, granularity, limit):
    raw = get("/api/v2/mix/market/candles", {
        "symbol": symbol, "productType": PRODUCT,
        "granularity": granularity, "limit": limit
    }).get("data", [])
    rows = list(reversed(raw))
    # Bitget may include the still-open candle; discard it.
    if len(rows) > 2:
        rows = rows[:-1]
    return rows

def metrics(symbol):
    t = get("/api/v2/mix/market/ticker", {
        "symbol": symbol, "productType": PRODUCT
    }).get("data", [])
    if not t:
        raise RuntimeError("ticker unavailable")
    ticker = t[0]
    price = f(ticker.get("lastPr"))
    quote_volume = f(ticker.get("quoteVolume"))
    if price <= 0:
        raise RuntimeError("invalid price")
    if quote_volume < MIN_QUOTE_VOLUME:
        return None

    rows = candles(symbol, "15m", 80)
    if len(rows) < 40:
        return None

    closes = [f(r[4]) for r in rows]
    highs = [f(r[2]) for r in rows]
    lows = [f(r[3]) for r in rows]
    vols = [f(r[5]) for r in rows]

    atrs = []
    prev = None
    for h, l, c in zip(highs, lows, closes):
        atrs.append(h - l if prev is None else max(h-l, abs(h-prev), abs(l-prev)))
        prev = c
    atr = sum(atrs[-14:]) / 14
    if atr <= 0:
        return None

    ret15 = (closes[-1] / closes[-2] - 1) * 100
    ret1h = (closes[-1] / closes[-5] - 1) * 100
    range_high = max(highs[-32:])
    range_low = min(lows[-32:])
    span = range_high - range_low
    range_pos = (price - range_low) / span if span > 0 else 0.5

    baseline = sum(vols[-21:-1]) / 20 if sum(vols[-21:-1]) else 1.0
    volume_ratio = vols[-1] / baseline if baseline else 1.0

    move_atr = abs(closes[-1] - closes[-5]) / atr
    breakout_long = price > range_high * 0.9995
    breakout_short = price < range_low * 1.0005
    pullback_long = ret1h > 0.6 and 0.35 <= range_pos <= 0.70 and ret15 < 0.2
    pullback_short = ret1h < -0.6 and 0.30 <= range_pos <= 0.65 and ret15 > -0.2

    momentum_long = ret1h > 0.8 and ret15 > 0.10 and move_atr >= 0.35
    momentum_short = ret1h < -0.8 and ret15 < -0.10 and move_atr >= 0.35

    mean_long = range_pos <= 0.20 and ret15 > -1.0
    mean_short = range_pos >= 0.80 and ret15 < 1.0

    def score(direction):
        expansion = clamp((volume_ratio - 1.0) * 30.0)
        vol = clamp((atr / price) * 10000.0)
        vol_score = clamp(vol * 1.5)
        if direction == "LONG":
            structure = (25 if breakout_long else 12 if pullback_long else 0)
            momentum = clamp(ret1h * 10 + ret15 * 12) if momentum_long else 0
            mean = 15 if mean_long else 0
            directional = clamp(50 + ret1h * 12 + ret15 * 15)
        else:
            structure = (25 if breakout_short else 12 if pullback_short else 0)
            momentum = clamp(-ret1h * 10 - ret15 * 12) if momentum_short else 0
            mean = 15 if mean_short else 0
            directional = clamp(50 - ret1h * 12 - ret15 * 15)
        return clamp(0.25*directional + 0.20*expansion +
                     0.15*vol_score + 0.25*structure +
                     0.15*momentum + 0.05*mean)

    long_score, short_score = score("LONG"), score("SHORT")
    direction = "LONG" if long_score >= short_score else "SHORT"
    alpha = max(long_score, short_score)

    reasons = []
    if volume_ratio >= 1.5: reasons.append(f"volume {volume_ratio:.2f}x")
    if atr / price * 100 >= 0.5: reasons.append(f"ATR {atr/price*100:.2f}%")
    if direction == "LONG":
        if breakout_long: reasons.append("range breakout")
        if pullback_long: reasons.append("bullish pullback")
        if momentum_long: reasons.append("momentum")
        if mean_long: reasons.append("lower-range reversion")
    else:
        if breakout_short: reasons.append("range breakdown")
        if pullback_short: reasons.append("bearish pullback")
        if momentum_short: reasons.append("momentum")
        if mean_short: reasons.append("upper-range reversion")

    if alpha >= 72 and len(reasons) >= 2:
        state = "ALPHA_READY_SHADOW"
    elif alpha >= 58 and reasons:
        state = "DEVELOPING"
    elif alpha >= 48:
        state = "WATCH"
    else:
        return None

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "price": round(price, 10), "direction": direction,
        "state": state, "alpha_score": round(alpha, 2),
        "return_15m": round(ret15, 3), "return_1h": round(ret1h, 3),
        "atr_pct": round(atr / price * 100, 4), "range_pos": round(range_pos, 4),
        "volume_ratio": round(volume_ratio, 3),
        "breakout": int(breakout_long or breakout_short),
        "pullback": int(pullback_long or pullback_short),
        "momentum": int(momentum_long or momentum_short),
        "mean_reversion": int(mean_long or mean_short),
        "reason": "; ".join(reasons) or "volatility/price opportunity"
    }

def discover_symbols():
    rows = get("/api/v2/mix/market/tickers", {"productType": PRODUCT}).get("data", [])
    symbols = []
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        if not symbol.endswith("USDT"):
            continue
        if f(row.get("lastPr")) <= 0 or f(row.get("quoteVolume")) < MIN_QUOTE_VOLUME:
            continue
        symbols.append(symbol)
    symbols.sort(key=lambda s: s)
    return symbols[:MAX_SYMBOLS]

def run():
    symbols = discover_symbols()
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(metrics, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as exc:
                print(f"WARN {futures[future]}: {exc}")
    results.sort(key=lambda r: (-float(r["alpha_score"]), r["symbol"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print(f"Universe: {len(symbols)} | Opportunities: {len(results)}")
    for row in results[:20]:
        print(row["state"], row["direction"], row["symbol"], row["alpha_score"], row["reason"])
    return results

if __name__ == "__main__":
    run()
