import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import requests

BINANCE_BASES = ["https://fapi.binance.com", "https://fapi1.binance.com", "https://fapi2.binance.com", "https://fapi3.binance.com", "https://fapi4.binance.com"]
BYBIT_BASE = "https://api.bybit.com"
BITGET_BASE = "https://api.bitget.com"
CAPITAL_IDR = 900_000
RISK_PCT = 0.02
MAX_SYMBOLS = 15
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT", "IOTAUSDT", "TAOUSDT", "AXLUSDT", "BNBUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "APTUSDT", "SEIUSDT"]
TIMEOUT = 15
S = requests.Session()
S.headers.update({"User-Agent": "Zorathvael-Crypto-Scanner/1.6"})


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def http_json(base, path, params=None, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            r = S.get(base + path, params=params, timeout=TIMEOUT)
            if r.ok:
                try:
                    return r.json()
                except Exception as e:
                    raise RuntimeError(f"Invalid JSON: {e}")
            # Retry transient/rate-limit responses; do not waste time on permanent 4xx geo blocks.
            if r.status_code in (408, 425, 429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:220]}")
        except requests.RequestException as e:
            last = e
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise RuntimeError(f"Network error: {e}")
    raise RuntimeError(str(last) if last else "request failed")


def binance(path, params=None):
    errors = []
    for base in BINANCE_BASES:
        try:
            return http_json(base, path, params)
        except Exception as e:
            errors.append(f"{base}: {e}")
    raise RuntimeError("Binance unavailable: " + " | ".join(errors))


def bybit(path, params=None):
    d = http_json(BYBIT_BASE, path, params)
    if d.get("retCode") not in (None, 0):
        raise RuntimeError(f"retCode {d.get('retCode')}: {d.get('retMsg')}")
    return d


def bitget(path, params=None):
    d = http_json(BITGET_BASE, path, params)
    if d.get("code") not in (None, "00000", 0):
        raise RuntimeError(f"code {d.get('code')}: {d.get('msg')}")
    return d


def signal(score):
    return "STRONG SETUP" if score >= 80 else "BUY / WATCH" if score >= 70 else "WATCH" if score >= 60 else "AVOID"


def risk_plan(price):
    entry_low, entry_high = price * 0.985, price * 0.995
    sl = entry_low * 0.95
    position = (CAPITAL_IDR * RISK_PCT) / 0.05
    r = entry_low - sl
    return entry_low, entry_high, sl, position, r


def score_result(symbol, provider, price, change24, momentum, volume, oi, taker, book, funding, ls, btc):
    # Taker is a buy/sell notional ratio. A ratio near 1 is balanced; higher is buy-dominant.
    raw = {
        "momentum": (20, clamp((momentum + 2) / 8)) if momentum is not None else None,
        "volume": (15, clamp((volume - 0.8) / 1.7)) if volume is not None else None,
        "oi": (15, clamp((oi + 1) / 9)) if oi is not None else None,
        "taker": (15, clamp((taker - 0.90) / 0.50)) if taker is not None else None,
        "book": (10, clamp((book - 0.90) / 0.35)) if book is not None else None,
        "funding": (10, 1 - clamp(abs(funding) / 0.0015)) if funding is not None else None,
        "long_short": (10, 1 - clamp(abs(ls - 1.35) / 1.5)) if ls is not None else None,
        "btc": (5, clamp((btc + 3) / 9)) if btc is not None else None,
    }
    available = {k: v for k, v in raw.items() if v is not None}
    total = sum(v[0] for v in available.values())
    if total < 40:
        raise RuntimeError("Too little valid market data")
    parts = {k: round(v[0] * v[1] * 100 / total, 2) for k, v in available.items()}
    score = round(sum(parts.values()), 1)
    entry_low, entry_high, sl, position, r = risk_plan(price)
    return {
        "symbol": symbol, "provider": provider, "price": price, "score": score,
        "signal": signal(score), "change24": change24, "momentum6": momentum,
        "vol_ratio": volume, "oi_change": oi, "taker": taker, "funding": funding,
        "book": book, "ls_ratio": ls, "entry_low": entry_low, "entry_high": entry_high,
        "sl": sl, "position_idr": position, "tp1": entry_low + 1.5 * r,
        "tp2": entry_low + 3 * r, "tp3": entry_low + 5 * r,
        "parts": parts, "missing": [k for k, v in raw.items() if v is None],
    }


def common_features(kl):
    if len(kl) < 13:
        raise RuntimeError(f"Need 13+ candles, got {len(kl)}")
    closes = [float(x[4]) for x in kl]
    vols = [float(x[5]) for x in kl]
    momentum = (closes[-1] / closes[-7] - 1) * 100
    baseline = sum(vols[-13:-1]) / 12
    return momentum, vols[-1] / baseline if baseline else None


def score_binance(symbol, btc):
    t = binance("/fapi/v1/ticker/24hr", {"symbol": symbol})
    price = float(t["lastPrice"]); change = float(t.get("priceChangePercent", 0))
    momentum, volume = common_features(binance("/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": 25}))
    oi_raw = binance("/futures/data/openInterestHist", {"symbol": symbol, "period": "1h", "limit": 2}); oi = None
    if len(oi_raw) >= 2:
        a, b = float(oi_raw[-2]["sumOpenInterest"]), float(oi_raw[-1]["sumOpenInterest"]); oi = (b / a - 1) * 100 if a else None
    tak_raw = binance("/futures/data/takerlongshortRatio", {"symbol": symbol, "period": "1h", "limit": 1}); taker = float(tak_raw[-1]["buySellRatio"]) if tak_raw else None
    ls_raw = binance("/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": "1h", "limit": 1}); ls = float(ls_raw[-1]["longShortRatio"]) if ls_raw else None
    fr = binance("/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1}); funding = float(fr[-1]["fundingRate"]) if fr else None
    d = binance("/fapi/v1/depth", {"symbol": symbol, "limit": 20}); bids = sum(float(x[1]) for x in d.get("bids", [])[:20]); asks = sum(float(x[1]) for x in d.get("asks", [])[:20]); book = bids / asks if bids > 0 and asks > 0 else None
    return score_result(symbol, "Binance", price, change, momentum, volume, oi, taker, book, funding, ls, btc)


def score_bybit(symbol, btc):
    t = bybit("/v5/market/tickers", {"category": "linear", "symbol": symbol})["result"]["list"]
    if not t: raise RuntimeError("symbol unavailable")
    t = t[0]; price = float(t["lastPrice"]); change = float(t.get("price24hPcnt", 0)) * 100
    kl = list(reversed(bybit("/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": "60", "limit": 25})["result"]["list"]))
    momentum, volume = common_features(kl)
    oi_raw = bybit("/v5/market/open-interest", {"category": "linear", "symbol": symbol, "intervalTime": "1h", "limit": 2})["result"]["list"]; oi = None
    if len(oi_raw) >= 2:
        q = list(reversed(oi_raw)); a, b = float(q[-2]["openInterest"]), float(q[-1]["openInterest"]); oi = (b / a - 1) * 100 if a else None
    fr = bybit("/v5/market/funding/history", {"category": "linear", "symbol": symbol, "limit": 1})["result"]["list"]; funding = float(fr[0]["fundingRate"]) if fr else None
    lsraw = bybit("/v5/market/account-ratio", {"category": "linear", "symbol": symbol, "period": "1h", "limit": 1})["result"]["list"]; ls = float(lsraw[0]["buyRatio"]) / max(float(lsraw[0]["sellRatio"]), 1e-9) if lsraw else None
    d = bybit("/v5/market/orderbook", {"category": "linear", "symbol": symbol, "limit": 25})["result"]; bids = sum(float(x[1]) for x in d.get("b", [])); asks = sum(float(x[1]) for x in d.get("a", [])); book = bids / asks if bids > 0 and asks > 0 else None
    tr = bybit("/v5/market/recent-trade", {"category": "linear", "symbol": symbol, "limit": 500})["result"]["list"]; buy = sum(float(x[1]) * float(x[2]) for x in tr if x.get("side") == "Buy"); sell = sum(float(x[1]) * float(x[2]) for x in tr if x.get("side") == "Sell"); taker = buy / sell if buy > 0 and sell > 0 else None
    return score_result(symbol, "Bybit", price, change, momentum, volume, oi, taker, book, funding, ls, btc)


def score_bitget(symbol, btc):
    pt = "USDT-FUTURES"
    t = bitget("/api/v2/mix/market/ticker", {"symbol": symbol, "productType": pt})["data"]
    if not t: raise RuntimeError("symbol unavailable")
    t = t[0]; price = float(t["lastPr"]); change = float(t.get("change24h", 0)) * 100; funding = float(t.get("fundingRate", 0))

    raw = bitget("/api/v2/mix/market/candles", {"symbol": symbol, "productType": pt, "granularity": "1H", "limit": 25})["data"]
    momentum, volume = common_features(list(reversed(raw)))

    d = bitget("/api/v2/mix/market/merge-depth", {"symbol": symbol, "productType": pt, "limit": 20})["data"]
    bids = sum(float(x[1]) for x in d.get("bids", [])); asks = sum(float(x[1]) for x in d.get("asks", [])); book = bids / asks if bids > 0 and asks > 0 else None

    # Public fills are available at high rate. Compute buy/sell notional ratio.
    tr = bitget("/api/v2/mix/market/fills", {"symbol": symbol, "productType": pt, "limit": 100})["data"]
    buy = sum(float(x["price"]) * float(x["size"]) for x in tr if x.get("side") == "buy")
    sell = sum(float(x["price"]) * float(x["size"]) for x in tr if x.get("side") == "sell")
    taker = buy / sell if buy > 0 and sell > 0 else None

    # Long/short has a strict 1 request/sec/IP limit. It is intentionally optional:
    # one throttled auxiliary endpoint must never discard an otherwise valid symbol.
    ls = None
    ls_error = None
    try:
        lsraw = bitget("/api/v2/mix/market/long-short", {"symbol": symbol, "period": "1h"})["data"]
        if lsraw:
            ls = float(lsraw[0]["longShortRatio"])
    except Exception as e:
        ls_error = str(e)

    result = score_result(symbol, "Bitget", price, change, momentum, volume, None, taker, book, funding, ls, btc)
    if ls_error:
        result["aux_errors"] = ["long_short: " + ls_error]
    return result


def score_symbol(symbol, provider, btc):
    try:
        if provider == "Binance": return score_binance(symbol, btc)
        if provider == "Bybit": return score_bybit(symbol, btc)
        return score_bitget(symbol, btc)
    except Exception as e:
        return {"symbol": symbol, "score": -1, "signal": "ERROR", "error": str(e)}


def discover_provider():
    errors = []
    try:
        t = binance("/fapi/v1/ticker/24hr", {"symbol": "BTCUSDT"}); return "Binance", float(t.get("priceChangePercent", 0))
    except Exception as e:
        errors.append(f"Binance={e}"); print(f"WARN: Binance unavailable: {e}")
    try:
        t = bybit("/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"})["result"]["list"]
        if not t: raise RuntimeError("BTCUSDT unavailable")
        return "Bybit", float(t[0].get("price24hPcnt", 0)) * 100
    except Exception as e:
        errors.append(f"Bybit={e}"); print(f"WARN: Bybit unavailable: {e}")
    try:
        t = bitget("/api/v2/mix/market/ticker", {"symbol": "BTCUSDT", "productType": "USDT-FUTURES"})["data"]
        if not t: raise RuntimeError("BTCUSDT unavailable")
        return "Bitget", float(t[0].get("change24h", 0)) * 100
    except Exception as e:
        errors.append(f"Bitget={e}"); raise SystemExit("FATAL: all public Futures providers unavailable. " + " | ".join(errors))


def send_telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("INFO: Telegram secrets not configured; console output only."); return False
    try:
        r = S.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=TIMEOUT)
        return r.ok
    except Exception as e:
        print(f"WARN: Telegram unavailable: {e}"); return False


def fmt(v, digits=2):
    return "N/A" if v is None else f"{v:.{digits}f}"


def main():
    print("ZORATHVAEL CRYPTO SCANNER V1.6")
    print("Provider strategy: Binance -> Bybit -> Bitget")
    provider, btc = discover_provider(); print(f"Active provider: {provider}")
    results = []; errors = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        jobs = [ex.submit(score_symbol, s, provider, btc) for s in SYMBOLS[:MAX_SYMBOLS]]
        for j in as_completed(jobs):
            x = j.result()
            if x.get("score", -1) >= 0: results.append(x)
            else: errors.append(f"{x['symbol']}: {x.get('error', 'unknown error')}")
    if not results:
        print("SYMBOL ERRORS:"); [print(" -", e) for e in errors[:15]]
        raise SystemExit(f"FATAL: No symbols returned valid {provider} Futures data.")

    results.sort(key=lambda x: x["score"], reverse=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["ZORATHVAEL CRYPTO SCANNER V1.6", now, f"Provider: {provider}", f"BTC 24h: {btc:.2f}%", f"Coverage: {len(results)}/{len(SYMBOLS[:MAX_SYMBOLS])} symbols", ""]
    for i, x in enumerate(results[:10], 1):
        miss = ",".join(x["missing"]) if x["missing"] else "none"
        lines.append(f"{i}. {x['symbol']} | {x['score']:.1f} | {x['signal']}")
        lines.append(f"   Price {x['price']:.8g} | 24h {x['change24']:.2f}% | Mom {fmt(x['momentum6'])}% | Vol {fmt(x['vol_ratio'])}x")
        lines.append(f"   OI {fmt(x['oi_change'])}% | Taker {fmt(x['taker'])}x | Book {fmt(x['book'])}x | Funding {fmt(x['funding'], 6)} | L/S {fmt(x['ls_ratio'])}")
        lines.append(f"   Entry {x['entry_low']:.8g}-{x['entry_high']:.8g} | SL {x['sl']:.8g} | Pos Rp{x['position_idr']:,.0f}")
        lines.append(f"   TP1 {x['tp1']:.8g} | TP2 {x['tp2']:.8g} | TP3 {x['tp3']:.8g} | Missing: {miss}")
    if errors:
        lines.append(f"\nHard-failed symbols: {len(errors)}")
        for e in errors[:10]: lines.append(" - " + e)
    text = "\n".join(lines); print(text); send_telegram(text)


if __name__ == "__main__":
    main()
