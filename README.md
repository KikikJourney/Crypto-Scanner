# Zorathvael Crypto Scanner

Free public-data crypto futures swing scanner for Zorathvael.

## V1.3
- Runs every 15 minutes through GitHub Actions.
- Uses Binance Futures as the preferred data source.
- Automatically falls back to Bybit linear perpetual Futures when Binance is blocked or unreachable from the GitHub runner.
- Never converts a failed API request into fake neutral market data.
- Scores 15 selected USDT-margined futures pairs from 0-100.
- Uses 1h momentum, volume expansion, open-interest change, taker pressure, order-book imbalance, funding, long/short ratio and BTC regime.
- Produces a top-5 shortlist plus entry zone, 5% stop-loss model, 1.5R/3R/5R targets and conservative position sizing.
- Optional Telegram alerts through GitHub Actions Secrets.

## Provider architecture

```text
GitHub Actions
      |
      +--> Binance Futures (primary)
      |         |
      |         +--> if unavailable / HTTP 451
      |                    |
      +--------------------+
                           v
                    Bybit Futures fallback
                           |
                           v
                    Scoring engine 0-100
                           |
                           v
                         Top 5
                           |
                           v
                       Telegram
```

The Bybit fallback is a real derivatives-data source, not a price-only substitute. It supplies candles, open interest, funding, order book, recent public trades and long/short account ratio through its public V5 market API.

## Setup
1. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as repository Actions secrets if Telegram alerts are wanted.
2. Open **Actions** → **Zorathvael Crypto Scanner** → **Run workflow** for a manual test.
3. Otherwise the workflow runs every 15 minutes.

## Current limitations
- Binance may be inaccessible from GitHub-hosted runner IPs because Binance can restrict service by location/network policy.
- Bybit is therefore the operational fallback for the scanner.
- Entry zones are currently a conservative percentage-based model, not automatic support/resistance detection.
- The scanner is not an auto-trader and does not place orders.

## Risk
The scanner is a research tool, not financial advice. A high score does not guarantee profit. The 100% upside objective is treated as potential asymmetric upside, never as a guaranteed target or BUY condition. For the current Rp900,000 capital model, maximum account risk is 2% (Rp18,000) per trade.
