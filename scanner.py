import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import requests

# Binance publishes several equivalent Futures API base domains.
# GitHub-hosted runners can occasionally be unable to reach one of them.
BASES = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]

CAPITAL_IDR = 900_000
RISK_PCT = 0.02
MAX_SYMBOLS = 15
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "SUIUSDT", "IOTAUSDT", "TAOUSDT", "AXLUSDT", "BNBUSDT",
    "ADAUSDT", "LINKUSDT", "AVAXUSDT", "APTUSDT", "SEIUSDT"
]
TIMEOUT = 12

S = requests.Session()
S.headers.update({"User-Agent": "Zorathvael-Crypto-Scanner/1.2"})
ACTIVE_BASE = None


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def request(path, params=None):
    global ACTIVE_BASE
    bases = [ACTIVE_BASE] if ACTIVE_BASE else []
    bases += [b for b in BASES if b != ACTIVE_BASE]
    errors = []

    for base in bases:
        try:
            r = S.get(base + path, params=params, timeout=TIMEOUT)
            if r.ok:
                ACTIVE_BASE = base
                return r.json()
            errors.append(f"{base}: HTTP {r.status_code} {r.text[:120]}")
        except Exception as e:
            errors.append(f"{base}: {type(e).__name__}: {e}")

    raise RuntimeError(f"Binance API unavailable for {path}; " + " | ".join(errors))


def ticker(symbol):
    return request("/fapi/v1/ticker/24hr", {"symbol": symbol})


def optional(path, params=None, default=None):
    try:
        return request(path, params)
    except Exception as e:
        print(f"WARN {path}: {e}")
        return default


def score_symbol(symbol, btc_change):
    try:
        t = ticker(symbol)
        price = float(t["lastPrice"])
        change24 = float(t.get("priceChangePercent", 0))

        kl = optional("/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": 25}, []) or []
        oi = optional("/futures/data/openInterestHist", {"symbol": symbol, "period": "1h", "limit": 2}, []) or []
        taker = optional("/futures/data/takerlongshortRatio", {"symbol": symbol, "period": "1h", "limit": 1}, []) or []
        gls = optional("/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": "1h", "limit": 1}, []) or []
        top = optional("/futures/data/topLongShortAccountRatio", {"symbol": symbol, "period": "1h", "limit": 1}, []) or []
        funding = optional("/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1}, []) or []
        depth = optional("/fapi/v1/depth", {"symbol": symbol, "limit": 20}, {}) or {}

        if len(kl) < 7:
            raise RuntimeError(f"Insufficient 1h kline data: {len(kl)} candles")

        closes = [float(x[4]) for x in kl]
        vols = [float(x[5]) for x in kl]
        momentum6 = ((closes[-1] / closes[-7]) - 1) * 100
        baseline_vol = sum(vols[-13:-1]) / 12 if len(vols) >= 13 else 0
        vol_ratio = vols[-1] / baseline_vol if baseline_vol else 1

        oi_change = 0
        if len(oi) >= 2:
            a = float(oi[-2]["sumOpenInterest"])
            b = float(oi[-1]["sumOpenInterest"])
            oi_change = (b / a - 1) * 100 if a else 0

        taker_ratio = float(taker[-1].get("buySellRatio", 1)) if taker else 1
        gls_ratio = float(gls[-1].get("longShortRatio", 1)) if gls else 1
        top_ratio = float(top[-1].get("longShortRatio", 1)) if top else 1
        fr = float(funding[-1].get("fundingRate", 0)) if funding else 0

        bids = sum(float(x[1]) for x in depth.get("bids", [])[:20])
        asks = sum(float(x[1]) for x in depth.get("asks", [])[:20])
        book_ratio = bids / asks if asks else 1

        parts = {
            "momentum": 15 * clamp((momentum6 + 2) / 8),
            "volume": 15 * clamp((vol_ratio - 0.8) / 1.7),
            "oi": 15 * clamp((oi_change + 1) / 9),
            "taker": 15 * clamp((taker_ratio - 0.95) / 0.35),
            "book": 10 * clamp((book_ratio - 0.9) / 0.35),
            "funding": 10 * (1 - clamp(abs(fr) / 0.0015)),
            "global_ls": 10 * (1 - clamp(abs(gls_ratio - 1.35) / 1.5)),
            "top_ls": 5 * (1 - clamp(abs(top_ratio - 1.25) / 1.5)),
            "btc": 5 * clamp((btc_change + 3) / 9),
        }
        score = round(sum(parts.values()), 1)
        signal = "STRONG SETUP" if score >= 80 else "BUY / WATCH" if score >= 70 else "WATCH" if score >= 60 else "AVOID"

        entry_low, entry_high = price * 0.985, price * 0.995
        sl = entry_low * 0.95
        risk = CAPITAL_IDR * RISK_PCT
        position = risk / 0.05
        r = entry_low - sl

        return {
            "symbol": symbol,
            "price": price,
            "score": score,
            "signal": signal,
            "change24": change24,
            "momentum6": momentum6,
            "oi_change": oi_change,
            "taker": taker_ratio,
            "funding": fr,
            "book": book_ratio,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "sl": sl,
            "position_idr": position,
            "tp1": entry_low + 1.5 * r,
            "tp2": entry_low + 3 * r,
            "tp3": entry_low + 5 * r,
            "parts": parts,
        }
    except Exception as e:
        return {"symbol": symbol, "score": -1, "signal": "ERROR", "error": str(e)}


def send_telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        r = S.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text},
            timeout=TIMEOUT,
        )
        return r.ok
    except Exception:
        return False


def main():
    print("ZORATHVAEL CRYPTO SCANNER V1.2")
    print(f"Binance endpoint candidates: {len(BASES)}")

    try:
        btc = ticker("BTCUSDT")
        btc_change = float(btc.get("priceChangePercent", 0))
    except Exception as e:
        raise SystemExit(f"FATAL: Binance Futures API is unreachable. {e}")

    symbols = SYMBOLS[:MAX_SYMBOLS]
    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=5) as ex:
        jobs = [ex.submit(score_symbol, s, btc_change) for s in symbols]
        for j in as_completed(jobs):
            x = j.result()
            if x.get("score", -1) >= 0:
                results.append(x)
            else:
                errors.append(f"{x['symbol']}: {x.get('error', 'unknown error')}")

    if not results:
        raise SystemExit("FATAL: No symbols returned valid market data.")

    results.sort(key=lambda x: x["score"], reverse=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "ZORATHVAEL CRYPTO SCANNER V1.2",
        now,
        f"Binance endpoint: {ACTIVE_BASE}",
        f"BTC 24h: {btc_change:.2f}%",
        "",
    ]

    for i, x in enumerate(results[:5], 1):
        lines.append(f"{i}. {x['symbol']} | {x['score']:.1f} | {x['signal']}")
        lines.append(
            f"   Price {x['price']:.8g} | 24h {x['change24']:.2f}% | "
            f"OI {x['oi_change']:.2f}% | Taker {x['taker']:.2f}"
        )
        lines.append(f"   Entry {x['entry_low']:.8g}-{x['entry_high']:.8g} | SL {x['sl']:.8g}")
        lines.append(
            f"   Position max Rp{x['position_idr']:,.0f} | "
            f"TP1 {x['tp1']:.8g} | TP2 {x['tp2']:.8g} | TP3 {x['tp3']:.8g}"
        )

    if errors:
        lines += ["", f"Warnings: {len(errors)} symbol(s) had incomplete data."]
        lines.extend(f"- {e}" for e in errors[:5])

    text = "\n".join(lines)
    print(text)
    send_telegram(text)


if __name__ == "__main__":
    main()
