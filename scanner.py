import csv
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

VERSION = "1.8"
BINANCE_BASES = ["https://fapi.binance.com", "https://fapi1.binance.com", "https://fapi2.binance.com", "https://fapi3.binance.com", "https://fapi4.binance.com"]
BYBIT_BASE = "https://api.bybit.com"
BITGET_BASE = "https://api.bitget.com"
CAPITAL_IDR = 900_000
RISK_PCT = 0.02
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT", "IOTAUSDT", "TAOUSDT", "AXLUSDT", "BNBUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "APTUSDT", "SEIUSDT"]
TIMEOUT = 12
DATA_DIR = Path("data")
SIGNAL_FILE = DATA_DIR / "forward_test.csv"
HORIZONS = (1, 4, 12, 24)
CSV_FIELDS = [
    "id", "timestamp", "symbol", "provider", "price", "score", "bias", "signal", "change24h", "m1", "m6", "m24", "volume_ratio", "atr_pct", "taker_ratio", "book_ratio", "funding", "entry_low", "entry_high", "sl", "position_idr", "tp1", "tp2", "tp3", "stop_pct", "btc24", "btc6", "h1", "h4", "h12", "h24"
]

S = requests.Session()
S.headers.update({"User-Agent": f"Zorathvael-Crypto-Scanner/{VERSION}"})


def clamp(x, a=-1, b=1):
    return max(a, min(b, x))


def sf(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def get(base, path, params=None, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            r = S.get(base + path, params=params, timeout=TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
                if i < retries:
                    time.sleep(0.8 * (i + 1))
                    continue
            if not r.ok:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            try:
                return r.json()
            except Exception as e:
                raise RuntimeError(f"Invalid JSON: {e}") from e
        except requests.RequestException as e:
            last = RuntimeError(f"Network error: {e}")
            if i < retries:
                time.sleep(0.8 * (i + 1))
                continue
    raise last or RuntimeError("request failed")


def binance(path, params=None):
    errors = []
    for base in BINANCE_BASES:
        try:
            return get(base, path, params)
        except Exception as e:
            errors.append(f"{base}: {e}")
    raise RuntimeError("Binance unavailable: " + " | ".join(errors))


def bybit(path, params=None):
    d = get(BYBIT_BASE, path, params)
    if d.get("retCode") not in (None, 0):
        raise RuntimeError(f"retCode {d.get('retCode')}: {d.get('retMsg')}")
    return d


def bitget(path, params=None):
    d = get(BITGET_BASE, path, params)
    if d.get("code") not in (None, "00000", 0):
        raise RuntimeError(f"code {d.get('code')}: {d.get('msg')}")
    return d


def candle_features(rows):
    """Rows must be chronological: oldest -> newest, and contain closed candles only."""
    if len(rows) < 25:
        raise RuntimeError(f"Need 25+ closed candles, got {len(rows)}")
    c = [float(x[4]) for x in rows]
    v = [float(x[5]) for x in rows]
    m1 = (c[-1] / c[-2] - 1) * 100
    m6 = (c[-1] / c[-7] - 1) * 100
    m24 = (c[-1] / c[-25] - 1) * 100
    base = sum(v[-13:-1]) / 12
    vr = v[-1] / base if base else None
    trs = []
    prev = None
    for x in rows[-15:]:
        h, l, cl = map(float, x[2:5])
        trs.append(h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev)))
        prev = cl
    atr = (sum(trs) / len(trs)) / c[-1] * 100 if trs else None
    return m1, m6, m24, vr, atr


def bitget_features(sym):
    raw = bitget("/api/v2/mix/market/candles", {"symbol": sym, "productType": "USDT-FUTURES", "granularity": "1H", "limit": 26})["data"]
    return candle_features(list(reversed(raw[1:])))


def bybit_features(sym):
    raw = bybit("/v5/market/kline", {"category": "linear", "symbol": sym, "interval": "60", "limit": 26})["result"]["list"]
    return candle_features(list(reversed(raw[1:])))


def binance_features(sym):
    raw = binance("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 26})
    return candle_features(raw[:-1])


def bounded_ratio_score(ratio, scale):
    if ratio is None or ratio <= 0:
        return None
    return 50 + 25 * clamp(math.log(ratio) / math.log(scale))


def score(f, taker, book, funding, btc):
    m1, m6, m24, vr, atr = f
    mom = 50 + 18 * clamp(m6 / 4) + 12 * clamp(m24 / 12)
    tak = bounded_ratio_score(taker, 1.5)
    bk = bounded_ratio_score(book, 1.35)
    vol = None if vr is None else 50 + 20 * clamp((vr - 1) / 2)
    fund = None if funding is None else 50 - 25 * min(abs(funding) / 0.001, 1)
    br = 50 + 25 * clamp(btc / 4)
    vals = {"momentum": (30, mom), "taker": (20, tak), "orderbook": (15, bk), "volume": (10, vol), "funding": (10, fund), "btc_regime": (15, br)}
    available = {k: v for k, v in vals.items() if v[1] is not None}
    total = sum(v[0] for v in available.values())
    if total <= 0:
        raise RuntimeError("No scoring metrics available")
    s = sum(w * x for w, x in available.values()) / total
    direction_keys = [k for k in ("momentum", "taker", "orderbook") if k in available]
    direction_weight = sum(available[k][0] for k in direction_keys)
    ds = sum(available[k][0] * (available[k][1] - 50) for k in direction_keys) / direction_weight
    bias = "LONG" if ds > 5 else "SHORT" if ds < -5 else "NEUTRAL"
    return round(s, 1), bias, total / 100


def risk_plan(price, atr, bias):
    if bias not in ("LONG", "SHORT"):
        return (None,) * 8
    stop_pct = max(0.02, min(0.07, (atr or 3) * 1.5 / 100))
    risk_cash = CAPITAL_IDR * RISK_PCT
    position = min(CAPITAL_IDR, risk_cash / stop_pct)
    if bias == "SHORT":
        lo, hi = price * 1.005, price * 1.015
        sl = hi * (1 + stop_pct)
        r = sl - hi
        tp = [hi - 1.5 * r, hi - 3 * r, hi - 5 * r]
    else:
        lo, hi = price * 0.985, price * 0.995
        sl = lo * (1 - stop_pct)
        r = lo - sl
        tp = [lo + 1.5 * r, lo + 3 * r, lo + 5 * r]
    return lo, hi, sl, position, *tp, stop_pct * 100


def result(sym, provider, price, change24h, f, taker, book, funding, btc):
    s, bias, coverage = score(f, taker, book, funding, btc)
    m1, m6, m24, vr, atr = f
    plan = risk_plan(price, atr, bias)
    if s >= 75 and bias != "NEUTRAL" and coverage >= 0.65:
        signal = "STRONG " + bias
    elif s >= 68 and bias != "NEUTRAL" and coverage >= 0.65:
        signal = bias + " WATCH"
    else:
        signal = "NO SETUP"
    return dict(symbol=sym, provider=provider, price=price, score=s, bias=bias, signal=signal, coverage=coverage, change=change24h, m1=m1, m6=m6, m24=m24, vol=vr, atr=atr, taker=taker, book=book, funding=funding, plan=plan)


def bitget_symbol(sym, btc):
    pt = "USDT-FUTURES"
    t = bitget("/api/v2/mix/market/ticker", {"symbol": sym, "productType": pt})["data"][0]
    price = float(t["lastPr"])
    change = float(t.get("change24h", 0)) * 100
    funding = sf(t.get("fundingRate"))
    f = bitget_features(sym)
    d = bitget("/api/v2/mix/market/merge-depth", {"symbol": sym, "productType": pt, "limit": 20})["data"]
    bids = sum(float(x[1]) for x in d.get("bids", []))
    asks = sum(float(x[1]) for x in d.get("asks", []))
    book = bids / asks if bids and asks else None
    trades = bitget("/api/v2/mix/market/fills", {"symbol": sym, "productType": pt, "limit": 500})["data"]
    buy = sum(float(x["price"]) * float(x["size"]) for x in trades if x.get("side", "").lower() == "buy")
    sell = sum(float(x["price"]) * float(x["size"]) for x in trades if x.get("side", "").lower() == "sell")
    taker = buy / sell if buy and sell else None
    return result(sym, "Bitget", price, change, f, taker, book, funding, btc)


def bybit_symbol(sym, btc):
    t = bybit("/v5/market/tickers", {"category": "linear", "symbol": sym})["result"]["list"][0]
    price = float(t["lastPrice"])
    change = float(t.get("price24hPcnt", 0)) * 100
    f = bybit_features(sym)
    trades = bybit("/v5/market/recent-trade", {"category": "linear", "symbol": sym, "limit": 500})["result"]["list"]
    buy = sum(float(x[1]) * float(x[2]) for x in trades if x.get("side") == "Buy")
    sell = sum(float(x[1]) * float(x[2]) for x in trades if x.get("side") == "Sell")
    taker = buy / sell if buy and sell else None
    d = bybit("/v5/market/orderbook", {"category": "linear", "symbol": sym, "limit": 25})["result"]
    bids = sum(float(x[1]) for x in d.get("b", []))
    asks = sum(float(x[1]) for x in d.get("a", []))
    book = bids / asks if bids and asks else None
    fr = bybit("/v5/market/funding/history", {"category": "linear", "symbol": sym, "limit": 1})["result"]["list"]
    funding = float(fr[0]["fundingRate"]) if fr else None
    return result(sym, "Bybit", price, change, f, taker, book, funding, btc)


def binance_symbol(sym, btc):
    t = binance("/fapi/v1/ticker/24hr", {"symbol": sym})
    price = float(t["lastPrice"])
    change = float(t.get("priceChangePercent", 0))
    f = binance_features(sym)
    tr = binance("/futures/data/takerlongshortRatio", {"symbol": sym, "period": "1h", "limit": 1})
    taker = float(tr[-1]["buySellRatio"]) if tr else None
    fr = binance("/fapi/v1/fundingRate", {"symbol": sym, "limit": 1})
    funding = float(fr[-1]["fundingRate"]) if fr else None
    d = binance("/fapi/v1/depth", {"symbol": sym, "limit": 20})
    bids = sum(float(x[1]) for x in d.get("bids", []))
    asks = sum(float(x[1]) for x in d.get("asks", []))
    book = bids / asks if bids and asks else None
    return result(sym, "Binance", price, change, f, taker, book, funding, btc)


def discover():
    try:
        t = binance("/fapi/v1/ticker/24hr", {"symbol": "BTCUSDT"})
        return "Binance", float(t.get("priceChangePercent", 0))
    except Exception as e:
        print("WARN: Binance unavailable:", e)
    try:
        t = bybit("/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"})["result"]["list"][0]
        return "Bybit", float(t.get("price24hPcnt", 0)) * 100
    except Exception as e:
        print("WARN: Bybit unavailable:", e)
    try:
        t = bitget("/api/v2/mix/market/ticker", {"symbol": "BTCUSDT", "productType": "USDT-FUTURES"})["data"][0]
        return "Bitget", float(t.get("change24h", 0)) * 100
    except Exception as e:
        raise SystemExit("FATAL: all Futures providers unavailable: " + str(e))


def btc6(provider):
    if provider == "Binance":
        return binance_features("BTCUSDT")[1]
    if provider == "Bybit":
        return bybit_features("BTCUSDT")[1]
    return bitget_features("BTCUSDT")[1]


def ensure_signal_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SIGNAL_FILE.exists():
        with SIGNAL_FILE.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()


def signal_row(x, timestamp, btc24, btc6):
    p = x["plan"]
    return {
        "id": f"{timestamp}_{x['symbol']}", "timestamp": timestamp, "symbol": x["symbol"], "provider": x["provider"], "price": x["price"], "score": x["score"], "bias": x["bias"], "signal": x["signal"], "change24h": x["change"], "m1": x["m1"], "m6": x["m6"], "m24": x["m24"], "volume_ratio": x["vol"], "atr_pct": x["atr"], "taker_ratio": x["taker"], "book_ratio": x["book"], "funding": x["funding"], "entry_low": p[0] if p[0] is not None else "", "entry_high": p[1] if p[1] is not None else "", "sl": p[2] if p[2] is not None else "", "position_idr": p[3] if p[3] is not None else "", "tp1": p[4] if p[4] is not None else "", "tp2": p[5] if p[5] is not None else "", "tp3": p[6] if p[6] is not None else "", "stop_pct": p[7] if p[7] is not None else "", "btc24": btc24, "btc6": btc6, "h1": "", "h4": "", "h12": "", "h24": ""
    }


def append_signals(rows):
    ensure_signal_file()
    with SIGNAL_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        for row in rows:
            w.writerow(row)


def forward_candles(provider, sym):
    if provider == "Bitget":
        raw = bitget("/api/v2/mix/market/candles", {"symbol": sym, "productType": "USDT-FUTURES", "granularity": "15m", "limit": 110})["data"]
        return list(reversed(raw))
    if provider == "Bybit":
        raw = bybit("/v5/market/kline", {"category": "linear", "symbol": sym, "interval": "15", "limit": 110})["result"]["list"]
        return list(reversed(raw))
    return binance("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 110})


def evaluate_forward_test():
    if not SIGNAL_FILE.exists():
        return 0, 0
    with SIGNAL_FILE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    now = datetime.now(timezone.utc)
    changed = 0
    pending = 0
    cache = {}
    for row in rows:
        if row["bias"] not in ("LONG", "SHORT") or not row["entry_low"]:
            continue
        try:
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            age_h = (now - ts).total_seconds() / 3600
        except Exception:
            continue
        if age_h < 1:
            pending += 1
            continue
        try:
            cache_key = (row["provider"], row["symbol"])
            if cache_key not in cache:
                cache[cache_key] = forward_candles(row["provider"], row["symbol"])
            candles = cache[cache_key]
            base_ms = int(ts.timestamp() * 1000)
            future = [c for c in candles if int(c[0]) >= base_ms]
            if not future:
                continue
            direction = row["bias"]
            entry_low, entry_high = float(row["entry_low"]), float(row["entry_high"])
            sl, tp1 = float(row["sl"]), float(row["tp1"])
            for h in HORIZONS:
                key = f"h{h}"
                if row[key] or age_h < h:
                    continue
                subset = future[: h * 4]
                entered = False
                outcome = "NO_ENTRY"
                for c in subset:
                    high, low = float(c[2]), float(c[3])
                    if not entered:
                        if direction == "LONG" and low <= entry_high and high >= entry_low:
                            entered = True
                        elif direction == "SHORT" and high >= entry_low and low <= entry_high:
                            entered = True
                    if not entered:
                        continue
                    if direction == "LONG":
                        sl_hit, tp_hit = low <= sl, high >= tp1
                    else:
                        sl_hit, tp_hit = high >= sl, low <= tp1
                    if sl_hit and tp_hit:
                        outcome = "SL_AND_TP_SAME_CANDLE"
                        break
                    if sl_hit:
                        outcome = "SL"
                        break
                    if tp_hit:
                        outcome = "TP1"
                        break
                if entered and outcome == "NO_ENTRY":
                    outcome = "OPEN"
                row[key] = outcome
                changed += 1
        except Exception:
            continue
    if changed:
        with SIGNAL_FILE.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            w.writerows(rows)
    return changed, pending


def summarize_validation():
    if not SIGNAL_FILE.exists():
        return []
    with SIGNAL_FILE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for label, lo, hi in (("50-59", 50, 60), ("60-67", 60, 68), ("68-74", 68, 75), ("75+", 75, 101)):
        group = [r for r in rows if lo <= float(r["score"]) < hi and r["bias"] in ("LONG", "SHORT")]
        h1 = [r["h1"] for r in group if r["h1"] in ("TP1", "SL", "SL_AND_TP_SAME_CANDLE")]
        tp = sum(v == "TP1" for v in h1)
        sl = sum(v != "TP1" for v in h1)
        if h1:
            out.append(f"Score {label}: {len(group)} tracked | 1h TP1 {tp}/{len(h1)} ({tp/len(h1):.0%}) | non-TP {sl}/{len(h1)} ({sl/len(h1):.0%})")
    return out


def send(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("INFO: Telegram secrets not configured; console output only.")
        return
    try:
        r = S.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text}, timeout=TIMEOUT)
        if not r.ok:
            print("WARN: Telegram:", r.status_code, r.text[:160])
    except Exception as e:
        print("WARN: Telegram unavailable:", e)


def main():
    print(f"ZORATHVAEL CRYPTO SCANNER V{VERSION}\nProvider strategy: Binance -> Bybit -> Bitget")
    provider, btc24 = discover()
    print("Active provider:", provider)
    btc = btc6(provider)
    results, errors = [], []
    fn = binance_symbol if provider == "Binance" else bybit_symbol if provider == "Bybit" else bitget_symbol
    with ThreadPoolExecutor(max_workers=5) as ex:
        jobs = [ex.submit(fn, s, btc) for s in SYMBOLS]
        for j in as_completed(jobs):
            try:
                results.append(j.result())
            except Exception as e:
                errors.append(str(e))
    results.sort(key=lambda x: (x["score"], x["coverage"]), reverse=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    append_signals([signal_row(x, timestamp, btc24, btc) for x in results])
    evaluated, pending = evaluate_forward_test()
    lines = [f"ZORATHVAEL CRYPTO SCANNER V{VERSION}", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), f"Provider: {provider}", f"BTC 24h: {btc24:.2f}% | BTC 6h: {btc:.2f}%", f"Coverage: {len(results)}/{len(SYMBOLS)}", ""]
    for i, x in enumerate(results[:10], 1):
        p = x["plan"]
        lines += [f"{i}. {x['symbol']} | {x['score']:.1f} | {x['signal']} | Core data {x['coverage']:.0%}", f"   Bias {x['bias']} | Price {x['price']:.8g} | 24h {x['change']:.2f}% | 1h {x['m1']:.2f}% | 6h {x['m6']:.2f}% | 24h-trend {x['m24']:.2f}%", f"   Vol {x['vol']:.2f}x | ATR {x['atr']:.2f}% | Taker {x['taker']:.2f}x | Book {x['book']:.2f}x | Funding {x['funding']:.6g}"]
        if x["bias"] in ("LONG", "SHORT"):
            lines += [f"   Entry {p[0]:.8g}-{p[1]:.8g} | SL {p[2]:.8g} ({p[7]:.2f}%) | Pos Rp{p[3]:,.0f}", f"   TP1 {p[4]:.8g} | TP2 {p[5]:.8g} | TP3 {p[6]:.8g}"]
        else:
            lines.append("   Trade plan: N/A (NEUTRAL bias)")
    if errors:
        lines += [f"\nFailed symbols: {len(errors)}"] + [" - " + e for e in errors[:15]]
    lines += ["", f"Forward-test store: {SIGNAL_FILE.as_posix()} | outcomes updated: {evaluated}"]
    for s in summarize_validation():
        lines.append(s)
    lines += ["", "Score is setup quality, NOT probability of profit.", "Forward-test results are observational and must not be treated as guaranteed performance.", "OI and Long/Short are intentionally not fabricated when reliable public historical data is unavailable."]
    text = "\n".join(lines)
    print(text)
    send(text)


if __name__ == "__main__":
    main()
