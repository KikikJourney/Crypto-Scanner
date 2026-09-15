# Zorathvael Crypto Scanner

Free public-data crypto futures swing scanner for Zorathvael.

## V1.6
- Runs every 15 minutes through GitHub Actions.
- Uses Binance Futures as primary, Bybit as fallback, and Bitget as the operational fallback when the first two are geo-blocked.
- Never converts failed API requests into fake neutral market data.
- Attempts to score all 15 selected USDT-margined futures pairs instead of discarding a symbol because one optional metric fails.
- Uses 1h momentum, volume expansion, open-interest change when available, taker pressure, order-book imbalance, funding, long/short ratio when available, and BTC regime.
- Missing metrics are explicitly reported as `N/A` and their weights are removed from the score denominator rather than penalizing the asset with invented values.
- Bitget long/short data is treated as optional because its public endpoint has a strict 1 request/sec/IP limit.
- Retries transient HTTP/network failures and rate-limit responses without hiding permanent errors.
- Produces a top-10 ranked shortlist plus entry zone, 5% stop-loss model, 1.5R/3R/5R targets and conservative position sizing.
- Optional Telegram alerts through GitHub Actions Secrets.

## Provider architecture

```text
GitHub Actions
      |
      +--> Binance Futures (primary)
      |         |
      |         +--> unavailable / geo restriction
      |                    |
      +--------------------+
                           v
                    Bybit Futures
                           |
                           +--> unavailable / geo restriction
                                      |
                                      v
                               Bitget Futures
                                      |
                                      v
                               Scoring engine 0-100
                                      |
                                      v
                                  Top 10
                                      |
                                      v
                                   Telegram
```

The Bitget fallback uses public futures market endpoints for ticker, 1h candles, order book and recent public fills. Open-interest change is currently left `N/A` rather than fabricated when historical OI data is unavailable. Long/short ratio is also optional because the public endpoint is rate-limited to 1 request/sec/IP.

## Setup
1. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as repository Actions secrets if Telegram alerts are wanted.
2. Open **Actions** → **Zorathvael Crypto Scanner** → **Run workflow** for a manual test.
3. Otherwise the workflow runs every 15 minutes.

## Current limitations
- Binance may be inaccessible from GitHub-hosted runner IPs because Binance can restrict service by location/network policy.
- Bybit may also be inaccessible from the runner's network location.
- Bitget is currently the working public-data fallback in this environment.
- Entry zones are currently a conservative percentage-based model, not automatic support/resistance detection.
- The scanner is not an auto-trader and does not place orders.

## Risk
The scanner is a research tool, not financial advice. A high score does not guarantee profit. The 100% upside objective is treated as potential asymmetric upside, never as a guaranteed target or BUY condition. For the current Rp900,000 capital model, maximum account risk is 2% (Rp18,000) per trade.
