# Zorathvael Crypto Scanner

A free public-data crypto futures scanner built for **pre-expansion reversal detection**.

The current engine is no longer the old V1.7 momentum scanner. It is designed to look for situations where price is genuinely stretched toward an extreme, exhaustion is developing, directional flow supports a reversal, structure begins to reclaim/reject, and expansion potential is present.

> **Current engine: V2.0 Pre-Expansion Reversal Scanner + V2.1 Diagnostic Layer**

## What the scanner is trying to detect

The scanner does **not** simply ask whether price is going up or down.

It asks whether a market is potentially transitioning from an extreme into a large move:

```text
LONG candidate
Price discounted / near range low
        +
Selling exhaustion
        +
Buyer flow
        +
Structure reclaim
        +
Expansion potential
        ↓
PRE-EXPANSION LONG
```

```text
SHORT candidate
Price premium / near range high
        +
Buying exhaustion
        +
Seller flow
        +
Structure rejection
        +
Expansion potential
        ↓
PRE-EXPANSION SHORT
```

The scanner only produces an actual directional signal when the required hard gates are satisfied.

## V2.0 scoring engine

Five components are scored from 0 to 1 and weighted into a 0-100 setup-quality score:

| Component | Weight | Purpose |
|---|---:|---|
| Location | 30% | Detects whether price is sufficiently discounted/premium within the recent range |
| Exhaustion | 20% | Measures evidence that the prior directional move may be losing strength |
| Flow | 20% | Uses public taker-flow data to measure directional pressure |
| Reclaim / Rejection | 15% | Looks for early structural confirmation of reversal |
| Expansion Potential | 15% | Combines activity/volume and volatility compression |

### Hard signal gates

A **PRE-EXPANSION LONG** requires all of the following:

- Score >= 70
- Long location >= 0.60
- Long reclaim >= 0.25
- Buyer flow >= 0.55

A **PRE-EXPANSION SHORT** requires all of the following:

- Score >= 70
- Short location >= 0.60
- Short rejection >= 0.25
- Seller flow >= 0.55 equivalent, represented internally as short flow <= 0.45

If the gates are not satisfied, the scanner does **not** manufacture a trade.

## V2.1 diagnostic layer

V2.1 does not change the V2.0 entry rules. It explains **how close a market is to becoming a valid setup**.

Possible diagnostic states include:

- `PRE-EXPANSION LONG`
- `PRE-EXPANSION SHORT`
- `NEAR LONG`
- `NEAR SHORT`
- `MONITOR LONG`
- `MONITOR SHORT`
- `NO EDGE`

For near candidates, the diagnostic layer identifies the main blockers, for example:

```text
reclaim 0.13<0.25
expansion 0.00<0.40
```

Side-specific LONG/SHORT component fields are preserved in the dynamic watchlist so the diagnostic layer can explain each side without duplicating the scanner's scoring math or making additional market-data requests.

Missing information is reported as `data-limited`; it is not replaced with invented values.

## Dynamic futures universe

The scanner now discovers the active futures universe from the selected provider instead of being restricted to the original 15 symbols.

Current provider selection:

```text
Binance Futures
      ↓ unavailable in current runner environment
Bybit Futures
      ↓ unavailable in current runner environment
Bitget USDT Futures
      ↓
Dynamic active perpetual universe
      ↓
Liquidity + mover candidate selection
      ↓
Deep scan
```

For Bitget, the runner discovers active USDT perpetual contracts and retains the full discovered universe as coverage while deep-scanning a focused candidate set.

Current selection configuration:

- Liquidity bucket: 220 symbols
- Mover bucket: 80 symbols
- Maximum deep-scan pool before deduplication: 300 symbols
- Scanner workers: 16

The liquidity and mover buckets are merged, so the actual deep-scan count can be lower than 300 because of overlap.

Example recent production run:

- 786 active Bitget USDT perpetual symbols discovered
- 261 symbols deep-scanned
- 261/261 deep-scan coverage
- 786/786 universe discovery coverage retained

These numbers are **run-specific**, not fixed guarantees; the live futures universe changes over time.

## Market data used

The V2.0 engine uses public market data including:

- Closed 1-hour candles
- ATR / volatility measurements
- Recent range location
- RSI
- Volume ratio
- Volatility compression
- Recent reclaim/rejection structure
- Taker-pressure windows of 100, 250 and 500 fills where available
- Taker-flow aggregate, stability and spread
- Order-book depth
- Funding data where available
- 24-hour price change

The scanner requires at least 80 closed candles for the core candle-feature calculation.

## Taker-pressure handling

Taker pressure is evaluated across multiple windows rather than relying on one observation:

```text
100 fills
250 fills
500 fills
   ↓
Geometric aggregation
   ↓
Stability + spread diagnostics
```

If sufficient public fills are unavailable, the scanner records that limitation rather than fabricating pressure data.

## Forward testing

The scanner maintains a forward-test dataset in:

`data/reversal_forward_test.csv`

The current evaluation horizons are:

- H1
- H4
- H12
- H24

An expansion is counted when price reaches **2 ATR favorable before 1 ATR adverse** after the signal snapshot. If the adverse threshold is reached first, the outcome is treated as a failure. Ambiguous cases are recorded separately.

Only candles occurring **after the signal timestamp** are eligible for forward-test evaluation.

The current dataset is still being accumulated. A recent run had:

```text
0 pre-expansion snapshots
3136 total snapshots
```

Therefore there is currently **not enough forward-test evidence to claim that the strategy is profitable or statistically validated**.

## GitHub Actions automation

The production workflow is:

`.github/workflows/reversal-scanner.yml`

It supports:

- Scheduled execution every 15 minutes
- Manual `workflow_dispatch` execution
- Automatic execution when core scanner/diagnostic workflow files change
- Python 3.12
- Syntax validation before scanning
- V2.1 diagnostic self-tests before scanning
- Watchlist CSV schema validation after scanning
- Automatic persistence of scanner and forward-test data

The workflow uses a concurrency group so overlapping scanner runs do not execute simultaneously.

The scanner itself is **not an auto-trader**. GitHub Actions only runs the analysis and persists the resulting research data.

## Output files

### `data/universe_watchlist.csv`

Current dynamic watchlist containing:

- Long and short scores
- Score gap to the 70 signal threshold
- Directional bias
- Diagnostic status
- Blockers
- Side-specific component scores
- Price/range/ATR information
- Volume and taker information
- Funding and 24-hour change
- Selection state

Selection states are:

- `TARGET` — valid directional signal at the configured threshold
- `WATCH` — directional candidate above 55 but below the signal threshold
- `MONITOR` — score >= 50 without a valid directional signal
- `SKIP` — below monitoring threshold

### `data/reversal_forward_test.csv`

Historical signal snapshots and subsequent forward-test outcomes.

## Risk model

The current capital model is:

- Capital: **Rp900,000**
- Maximum account risk: **2% = Rp18,000 per trade**
- Stop distance: adaptive, bounded between **2% and 7%**
- Position size: capped at available capital
- Planned targets: **1.5R / 3R / 5R**

These values are risk-management parameters, not promises of return.

## Current provider limitations

The current GitHub-hosted runner environment has recently returned:

- Binance Futures: HTTP 451
- Bybit Futures: HTTP 403
- Bitget Futures: working public-data provider

The provider chain is designed to fall through to the next provider when the earlier provider is unavailable.

## Important interpretation rules

### A high score is not a guaranteed trade

The score represents **setup quality**, not probability of profit.

### `NEAR` is not an entry

For example:

```text
NEAR LONG
```

means the market is approaching the configured conditions. It does not mean the scanner has approved a LONG entry.

### `MONITOR` is not an entry

Monitoring candidates still require the actual V2.0 hard gates before becoming directional signals.

### No signal is a valid result

If the market does not present the required combination of location, exhaustion, flow, structure and expansion potential, the correct scanner output is:

```text
NO SETUP
```

The system is deliberately designed to prefer **no trade over a fabricated signal**.

## Project status

**Current:** V2.0 reversal engine + V2.1 diagnostics + dynamic futures universe + automated forward-test collection.

**Not yet proven:** profitability, win rate, expectancy, or robustness across market regimes.

The next meaningful validation milestone is to accumulate a sufficient number of genuine `PRE-EXPANSION LONG/SHORT` snapshots and evaluate their subsequent H1/H4/H12/H24 outcomes.

## Disclaimer

This repository is a research and decision-support project. It is not financial advice and does not place trades. Crypto futures are highly risky and leverage can result in rapid losses. Never treat scanner output as a guarantee of profit.