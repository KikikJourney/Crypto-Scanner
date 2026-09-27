# Zorathvael Crypto Scanner

A research-grade crypto futures **multi-timeframe scalping scanner** that combines the existing V2.2 reversal engine with an independent MTF execution brain, dynamic futures-universe selection, forward testing, and Telegram signal delivery.

> **Current architecture: V2.2 reversal engine + MTF scalping intelligence + 15m/30m execution logic + forward testing + Telegram delivery**

The system is a **decision-support scanner, not an auto-trader**. It analyzes public market data, generates potential LONG/SHORT execution plans, records them for forward testing, and can send fresh actions to Telegram. Trades are still executed manually.

---

## 1. System architecture

```
PUBLIC FUTURES MARKET DATA
        |
        v
DYNAMIC FUTURES UNIVERSE
        |
        +--> liquidity bucket
        +--> mover bucket
        |
        v
DEEP SCAN
        |
        +--> V2.2 EXTREME REVERSAL ENGINE
        |       |
        |       +--> historical reversal accounting
        |       +--> extreme anchors
        |
        +--> MTF SCALPING BRAIN
                |
                +--> 4H trend context
                +--> 1H trend context
                +--> 30m structure
                +--> 15m structure / trigger
                +--> 5m entry precision
                +--> liquidity sweep
                +--> volume
                +--> RSI / momentum
                        |
                        v
                ACTION LONG / ACTION SHORT
                        |
              +---------+---------+
              |                   |
              v                   v
       Forward Testing        Telegram
       H15/H30/H60/H120       delivery
```

The MTF brain can operate independently of a V2.2 extreme reversal direction. When independent mode is used, V2.2 can provide a bonus to confidence rather than acting as the sole direction gate.

---

## 2. V2.2 reversal engine

The existing V2.2 scoring engine is preserved as the historical reversal-analysis layer.

It evaluates five components:

| Component | Weight | Purpose |
|---|---:|---|
| Location | 30% | Price position relative to recent extremes |
| Exhaustion | 20% | Evidence that the prior move is losing strength |
| Flow | 20% | Directional taker-flow pressure |
| Reclaim / Rejection | 15% | Structural reversal evidence |
| Expansion Potential | 15% | Activity and volatility-compression context |

### V2.2 PRE-EXPANSION gates

**LONG**
- Score >= 70
- Long location >= 0.60
- Long reclaim >= 0.25
- Buyer flow >= 0.55

**SHORT**
- Score >= 70
- Short location >= 0.60
- Short rejection >= 0.25
- Seller flow >= 0.55 equivalent

Expansion is a scoring component, not a mandatory hard gate.

The V2.2 engine is intentionally kept intact while the newer scalping layer consumes its outputs.

---

## 3. MTF scalping intelligence

File:

`scalping_intelligence.py`

The MTF brain is designed to answer a different question from the reversal engine:

> **Is there enough multi-timeframe directional and execution evidence to produce a current scalping action?**

### Timeframes

| Timeframe | Role |
|---|---|
| 4H | Higher-timeframe directional context |
| 1H | Trend confirmation |
| 30m | Market structure |
| 15m | Structure and execution trigger |
| 5m | Entry precision |

### Confidence model

The execution confidence is weighted as:

| Component | Weight |
|---|---:|
| 4H trend | 20% |
| 1H trend | 20% |
| 30m structure | 20% |
| 15m structure | 15% |
| 5m liquidity sweep | 10% |
| 5m volume | 10% |
| 5m momentum / RSI | 5% |

An action requires:

- valid LONG or SHORT direction
- sufficient MTF history
- directional alignment
- confidence >= 80
- execution risk between 0.10% and 8%

Independent MTF direction requires an alignment score of at least 3.0 across 4H/1H/30m/15m.

When a V2.2 score is >= 80 and aligned with the independent MTF direction, the MTF confidence receives a small bonus.

---

## 4. Execution model

The execution path now has an explicit separation between **entry calibration** and **entry geometry**.

Files:

- `entry_calibration.py`
- `entry_geometry.py`
- `scalping_intelligence.py`
- `execution_entry_location_100.py`
- `scalping_execution_layer.py`

### Entry calibration

**Entry calibration answers only: “Where/when should the execution attempt occur?”**

The current production calibration uses:

- 100 fully closed 5m candles
- LONG anchor = lowest low of the 100-candle window
- SHORT anchor = highest high of the 100-candle window
- ATR-aware entry buffer
- rebound validation
- maximum entry-distance validation

Calibration does **not** calculate the final SL/TP geometry.

### Historical calibration gate

The execution gate applies a direction-specific confidence floor derived from the latest resolved calibration evidence:

- LONG: **85.0**
- SHORT: **90.0**

This gate does not alter the calibrated entry or SL/TP geometry. It only suppresses execution when the historical direction-specific calibration evidence is below its configured floor. The values remain explicit constants so they can be revalidated as the forward-test sample grows.

### Entry geometry

**Entry geometry starts only after the calibrated entry is final.**

The global execution geometry is:

| Parameter | Standard |
|---|---:|
| Margin | 10 USDT |
| Leverage | 25x |
| Maximum SL loss | 5% of margin |
| TP1 | +30% margin ROI |
| TP2 | +60% margin ROI |
| TP3 | +120% margin ROI |

The geometry layer converts those margin limits into explicit price levels from the final calibrated entry. The complete TP1/TP2/TP3 ladder is always available in the action output.

A market-structure stop or target can be used as a **constraint**, but it cannot move or redefine the calibrated entry. If a structural stop exceeds the global 5% margin-loss budget, the geometry layer falls back to the canonical margin stop rather than expanding risk.

### Data flow

```
MARKET / MTF ANALYSIS
        |
        v
ENTRY CALIBRATION
100-candle location + timing
        |
        v
FINAL CALIBRATED ENTRY
        |
        v
ENTRY GEOMETRY
SL + TP1 + TP2 + TP3
        |
        v
EXECUTION GATE
        |
        +--> ACTION
        +--> WAIT
```

This separation is important for historical research: a change in entry timing can be evaluated independently from a change in SL/TP geometry.

### Signal validity

Each newly issued action receives a fresh **15-minute delivery window** from the scanner issuance timestamp.

This prevents a long-running deep scan from producing an action that is already expired before Telegram delivery.

---

## 5. Data freshness protection

The scanner explicitly rejects stale MTF market data.

Current maximum age:

- 15m candles: 30 minutes
- 5m candles: 10 minutes

If the feed is stale, invalid, or has an unavailable timestamp, the symbol is rejected rather than producing a potentially misleading action.

### Bitget candle normalization

Bitget MTF candles are:

1. timestamp-normalized
2. sorted chronologically
3. filtered to closed candles only
4. reduced to the latest required history

The scanner does **not** assume that the provider's returned candle order is newest-first.

This protects the execution layer from accidentally using an old candle page as if it were current market data.

---

## 6. Dynamic futures universe

The scanner does not depend on a permanent hard-coded symbol list.

Current provider chain:

```
Binance Futures
      |
      v
Bybit Futures
      |
      v
Bitget USDT Futures
      |
      v
Active perpetual universe
      |
      +--> liquidity candidates
      +--> mover candidates
      |
      v
deduplicated deep-scan pool
```

The current GitHub-hosted runner has experienced provider restrictions:

- Binance Futures: HTTP 451
- Bybit Futures: HTTP 403
- Bitget USDT Futures: working public-data provider

The system therefore falls through to the available provider. When this happens, Bitget is a fallback market-data source, not Binance-equivalent execution data; live cross-exchange validation should be performed before treating a setup as Binance Futures-executable.

Current Bitget selection configuration:

- Liquidity bucket: 220
- Mover bucket: 80
- Maximum pre-deduplication pool: 300
- Deep-scan workers: 8

The final deep-scan count can be lower because the liquidity and mover pools may overlap.

---

## 7. Market data

The scanner uses public market data including:

- closed candles
- price
- high / low range
- ATR
- EMA trend
- RSI
- volume
- liquidity-sweep structure
- market structure
- taker-flow information where available
- order-book information where available
- funding information where available
- 24-hour price movement

The MTF execution brain requires sufficient closed-candle history before producing an action.

No future candle is used to construct the current signal.

---

## 8. Signal lifecycle

A typical action moves through this lifecycle:

```
MARKET DATA
   |
   v
DIRECTION
   |
   v
MTF CONFIDENCE
   |
   +--> WAIT / DATA-LIMITED / NO-TRADE
   |
   v
ACTION LONG / ACTION SHORT
   |
   +--> entry zone
   +--> stop
   +--> target
   +--> risk
   +--> validity window
   |
   +--> forward test
   |
   +--> Telegram notification
```

Telegram delivery does not determine whether the underlying scanner generated an action. Delivery failures are isolated so one Telegram error does not abort the entire scanning workflow.

---

## 9. Telegram notifications

Files:

- `telegram_notifier.py`
- `send_telegram_actions.py`

The Telegram message contains:

- direction
- symbol
- confidence
- entry zone
- stop
- target
- RR
- risk percentage
- MTF context
- 5m RSI
- liquidity-sweep value
- 5m volume score
- validity window
- V2.2 score
- current execution status
- live price when available

GitHub Actions reads these secrets:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

A failed Telegram request is logged with the API error detail and does not stop the remaining signal-processing loop.

**Never commit or publish the bot token.**

---

## 10. Forward testing

The scanner records generated actions and evaluates future price behavior separately from signal generation.

### Scalping forward-test dataset

`data/scalping_forward_test.csv`

Horizons:

- H15
- H30
- H60
- H120

### Other research datasets

`data/extreme_reversal_forward_test.csv`

Historical V2.2 extreme-reversal outcomes at:

- H1
- H4
- H12
- H24

`data/actionable_forward_test.csv`

Historical actionable-reversal outcomes at:

- H1
- H4
- H12
- H24

`data/extreme_market_snapshots.csv`

Stores market snapshots used for research and forward evaluation.

The forward-test system uses future-only observations after the signal timestamp.

**No profitability claim is made until sufficient out-of-sample data exists.**

---

## 11. Generated output files

### `data/actionable_signals.csv`

Current scalping action queue.

Contains fields such as:

- timestamp
- symbol
- provider
- direction
- V2.2 score
- confidence
- entry
- entry_low
- entry_high
- trigger
- stop
- target
- risk percentage
- reward-to-risk
- validity window
- timeframe context
- RSI
- liquidity sweep
- volume
- reason

### `data/scalping_forward_test.csv`

Stores scalping actions and their future H15/H30/H60/H120 outcomes.

### `data/universe_watchlist.csv`

Stores the broader market universe and scanner-selection information.

### `data/telegram_sent_actions.csv`

Tracks action IDs that were successfully delivered to Telegram.

This prevents the same action from being repeatedly sent after successful delivery.

---

## 12. GitHub Actions automation

Production workflow:

`.github/workflows/reversal-scanner.yml`

The workflow:

1. checks out the repository
2. installs Python 3.12 dependencies
3. validates Python syntax
4. runs diagnostic tests
5. runs reversal tests
6. runs actionable-reversal tests
7. runs scalping execution tests
8. runs scalping intelligence tests
9. validates Telegram formatting
10. runs the V2.2/MTF scanner
11. evaluates scalping forward tests
12. sends pending actions to Telegram
13. validates generated datasets
14. persists research data back to the repository

### Schedule

```text
*/15 * * * *
```

The production workflow therefore executes every 15 minutes.

It also supports:

- manual `workflow_dispatch`
- push-triggered validation for relevant scanner files
- concurrency protection
- automatic persistence of generated datasets

---

## 13. Tests and validation

The workflow currently validates:

- Python syntax
- Early Reversal logic
- Extreme Reversal logic
- Actionable Reversal logic
- Actionable forward-test logic
- Actionable confirmation window
- Scalping execution
- Scalping intelligence
- Telegram message formatting
- generated dataset schemas
- action direction and numeric constraints
- forward-test event integrity

The goal is to catch logic or data-integrity regressions before treating a scanner run as operationally valid.

---

## 14. Risk parameters

Current execution parameters include:

- margin: 10 USDT
- leverage: 25x
- maximum SL loss: 5% of margin
- TP1: +30% margin ROI
- TP2: +60% margin ROI
- TP3: +120% margin ROI
- 100-candle entry calibration with ATR-aware buffer
- action validity: 15 minutes
- trigger gap limit in the dedicated execution layer: 1.25 ATR
- confirmation window in the dedicated execution layer: 30 minutes

These are **research and execution-control parameters**, not guarantees of return.

Position sizing and actual trade execution remain the user's responsibility.

---

## 15. Operational rules

### ACTION is not a guaranteed trade

An ACTION means the configured scanner conditions are currently satisfied. It is not a prediction of guaranteed profit.

### WAIT is intentional

WAIT means the scanner sees incomplete confirmation or insufficient execution quality.

### DATA-LIMITED means no reliable decision

If required data is missing or insufficient, the scanner should not invent values.

### STALE data means no action

A mathematically valid setup is not operationally valid if the underlying MTF data is too old.

### Price-zone validation matters

The Telegram execution status reports whether the current live price is:

- inside the entry zone
- outside the entry zone
- expired
- unavailable

The notification itself does not place an order.

### No signal is a valid result

The scanner is allowed to produce zero actions when market conditions do not meet its configured requirements.

---

## 16. Current implementation status

### Implemented

- explicit entry-calibration layer
- explicit entry-geometry layer
- 100-candle execution anchor
- canonical 10 USDT / 25x / 5% SL / 30%-60%-120% TP ladder
- V2.2 reversal-analysis engine
- dynamic futures universe
- Bitget MTF candle normalization
- stale-data protection
- independent MTF directional brain
- 4H / 1H / 30m / 15m / 5m analysis
- execution entry zone
- canonical margin-based SL/TP geometry from the final calibrated entry
- 15-minute action validity
- scalping forward testing
- Telegram notification pipeline
- Telegram error isolation
- automated GitHub Actions execution
- automated dataset validation
- automated persistence
- regression tests

### Not yet proven

- profitability
- win rate
- expectancy after fees and slippage
- robustness across market regimes
- live execution quality
- whether the independent MTF brain has a durable edge
- whether the V2.2 bonus improves outcomes
- whether 15-minute scheduled execution is sufficient for every intended scalping condition

These require continued forward testing with realistic execution assumptions.

---

## 17. Project philosophy

The scanner is built around a simple rule:

> **Do not manufacture a trade when the data does not justify one.**

The system therefore prioritizes:

1. data freshness
2. reproducibility
3. explicit signal rules
4. separation of analysis and execution logic
5. future-only validation
6. failure isolation
7. empirical testing over assumptions

---

## Disclaimer

This repository is a research and decision-support project. It is **not financial advice** and does not automatically place trades.

Crypto futures are highly risky. Leverage can produce rapid losses, including losses exceeding the amount expected to be risked depending on the trading venue and position management.

Scanner output is not a guarantee of profit, accuracy, or future performance. Always account for fees, slippage, liquidity, latency, funding, and execution risk when evaluating results.
