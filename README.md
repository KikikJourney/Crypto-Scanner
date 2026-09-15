# Zorathvael Crypto Scanner

Free public-data crypto futures swing scanner for Zorathvael.

## V1.7 — Signal Quality Engine
- Runs every 15 minutes through GitHub Actions.
- Provider chain: Binance -> Bybit -> Bitget.
- Processes all 15 selected USDT futures pairs and reports coverage.
- Uses multi-horizon 1h/6h/24h momentum instead of relying on one momentum value.
- Uses volume as confirmation rather than allowing volume alone to create a bullish signal.
- Uses bounded taker-pressure and order-book transforms so extreme values cannot dominate the score.
- Uses funding as a crowding/context factor.
- Adds ATR-style volatility measurement and adaptive 2%-7% stop sizing instead of a fixed 5% stop.
- Produces LONG, SHORT or NEUTRAL bias and separates setup quality from data quality.
- Long/Short and historical OI are not fabricated when the public provider does not supply reliable data for the required calculation.
- Retries transient HTTP/network/rate-limit failures.
- Produces a top-10 ranked shortlist with entry, stop, position size and 1.5R/3R/5R targets.
- Optional Telegram alerts through GitHub Actions Secrets.

## Scoring philosophy
The 0-100 score is a **setup-quality score**, not a probability of profit. Direction is determined from momentum, taker pressure and order-book imbalance. Volume confirms activity but does not independently create a bullish score. Missing data is not replaced with invented values.

## Provider architecture
```text
GitHub Actions
      |
      +--> Binance Futures
      |         |
      +--> Bybit Futures
      |         |
      +--> Bitget Futures (working fallback in current runner)
                |
                v
        Signal Quality Engine
                |
                v
             Top 10
                |
                v
             Telegram
```

Bitget public futures endpoints provide ticker, candles, depth and recent public fills. Its public long/short endpoint is rate-limited to 1 request/sec/IP, so V1.7 does not make that slow endpoint a requirement for every symbol. OI change is not fabricated when a defensible historical public series is unavailable. Bitget documents its futures depth and fills endpoints as high-frequency public market-data endpoints, while the long/short endpoint is much more restrictive. citeturn0search0turn0search5turn0search14

## Setup
1. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as repository Actions secrets if Telegram alerts are wanted.
2. Open **Actions** -> **Zorathvael Crypto Scanner** -> **Run workflow** for a manual test.
3. Otherwise the workflow runs every 15 minutes.

## Current limitations
- Binance may be inaccessible from GitHub-hosted runner IPs because Binance can restrict service by location/network policy.
- Bybit may also be inaccessible from the runner's network location.
- Bitget is currently the working public-data fallback in this environment.
- Entry zones are percentage-based rather than automatic support/resistance detection.
- The scanner is not an auto-trader and does not place orders.

## Risk
The scanner is a research/decision-support tool, not financial advice. A high score does not guarantee profit. The 100% upside objective is treated as potential asymmetric upside, never as a guaranteed target or BUY condition. Current capital model: Rp900,000 with maximum account risk of 2% (Rp18,000) per trade.
