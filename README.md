# Zorathvael Crypto Scanner

Free Binance Futures public-data swing scanner for Zorathvael.

## V1.1
- Scans 15 selected USDT-margined futures pairs on a 15-minute GitHub Actions schedule.
- Uses 1h market structure plus momentum, volume, open interest, taker flow, order-book imbalance, funding, long/short ratios, top-trader ratio and BTC regime.
- Produces a 0-100 score and top-5 shortlist.
- Includes a conservative risk plan for Rp900,000 capital and 2% maximum account risk per trade.
- Optional Telegram alerts through GitHub Actions Secrets.

## Setup
1. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as repository Actions secrets if Telegram alerts are wanted.
2. Open **Actions** → **Zorathvael Crypto Scanner** → **Run workflow** for a manual test.
3. Otherwise the workflow runs every 15 minutes.

## Risk
The scanner is a research tool, not financial advice. A high score does not guarantee profit. The 100% upside objective is treated as potential asymmetric upside, never as a guaranteed target or BUY condition.
