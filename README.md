# Zorathvael Crypto Scanner

A free public-data crypto futures scanner built to detect **early reversal conditions before expansion**, while preserving a stricter PRE-EXPANSION confirmation layer.

> **Current engine: V2.0 Pre-Expansion Reversal + V2.1 Early Reversal + Diagnostic Layer**

## Signal architecture

The scanner now separates reversal evidence into layers instead of weakening the original V2.0 gate:

```text
EARLY REVERSAL
earliest actionable reversal evidence
        ↓
PRE-EXPANSION
stronger confirmed reversal setup
        ↓
FORWARD TEST
objective future-only validation
```

The V2.0 PRE-EXPANSION rules remain unchanged. The V2.1 Early Reversal layer is additive and does not require expansion confirmation.

## V2.0 PRE-EXPANSION scoring engine

Five components are scored from 0 to 1 and weighted into a 0-100 setup-quality score:

| Component | Weight | Purpose |
|---|---:|---|
| Location | 30% | Detects sufficiently discounted/premium price location |
| Exhaustion | 20% | Measures evidence that the prior directional move may be losing strength |
| Flow | 20% | Uses public taker-flow data to measure directional pressure |
| Reclaim / Rejection | 15% | Looks for structural reversal confirmation |
| Expansion Potential | 15% | Combines activity/volume and volatility compression |

### V2.0 hard signal gates

**PRE-EXPANSION LONG** requires:

- Score >= 70
- Long location >= 0.60
- Long reclaim >= 0.25
- Buyer flow >= 0.55

**PRE-EXPANSION SHORT** requires:

- Score >= 70
- Short location >= 0.60
- Short rejection >= 0.25
- Seller flow >= 0.55 equivalent, represented internally as short flow <= 0.45

Expansion is intentionally **not a hard gate**. It is a component used in the setup score and remains a forward-looking activity/volatility measure.

## V2.1 Early Reversal layer

Early Reversal is designed for the specific objective:

> Detect a reversal while price is still at an extreme and before expansion has already become obvious.

It uses four early components:

| Component | Weight |
|---|---:|
| Location | 30% |
| Exhaustion | 25% |
| Flow | 25% |
| Early Structure | 20% |

### Early gates

An **EARLY REVERSAL LONG** or **EARLY REVERSAL SHORT** requires:

- Early score >= 65
- Location >= 0.65
- Exhaustion >= 0.50
- Supporting flow >= 0.55
- Reclaim/rejection structure >= 0.15

Expansion is deliberately **not required** for Early Reversal.

The layer consumes components already calculated by the core scanner. It adds no market-data API calls and does not use future data.

### Interpretation

```text
EARLY REVERSAL
    = earliest qualified reversal condition

PRE-EXPANSION
    = stronger V2.0 confirmation

MONITOR / NEAR
    = candidate, not an entry

NO SETUP
    = no qualified condition
```

Early and PRE signals are recorded separately so their future performance can be measured independently.

## V2.1 diagnostic layer

The diagnostic layer explains why a market is close to or has reached a reversal state without changing the V2.0 entry gate.

Possible states include:

- `PRE-EXPANSION LONG`
- `PRE-EXPANSION SHORT`
- `NEAR LONG`
- `NEAR SHORT`
- `MONITOR LONG`
- `MONITOR SHORT`
- `NO EDGE`

For non-signal candidates, blockers may identify conditions such as:

```text
reclaim 0.13<0.25
exhaustion 0.45<0.50
```

For a valid PRE-EXPANSION signal, expansion is reported as a component to monitor rather than incorrectly reported as a hard blocker.

Missing information is reported as `data-limited`; values are never invented.

## Dynamic futures universe

The scanner discovers the active futures universe from the selected provider rather than relying on a fixed symbol list.

Current provider chain:

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

Current Bitget selection configuration:

- Liquidity bucket: 220
- Mover bucket: 80
- Maximum candidate pool before deduplication: 300
- Scanner workers: 16

The actual deep-scan count can be lower than 300 because liquidity and mover buckets overlap.

## Market data used

The V2.0/V2.1 engine uses public data including:

- Closed 1-hour candles
- ATR / volatility measurements
- Recent range location
- RSI
- Volume ratio
- Volatility compression
- Reclaim/rejection structure
- Taker-pressure windows of 100, 250 and 500 fills where available
- Taker-flow aggregate, stability and spread
- Order-book depth
- Funding data where available
- 24-hour price change

The core candle calculation requires at least 80 closed candles.

## Forward testing

### PRE-EXPANSION dataset

`data/reversal_forward_test.csv`

Evaluation horizons:

- H1
- H4
- H12
- H24

An expansion is counted when price reaches **2 ATR favorable before 1 ATR adverse** after the signal snapshot. Adverse-first cases are failures; ambiguous cases are recorded separately.

Only future snapshots after the signal timestamp are eligible.

### EARLY REVERSAL dataset

`data/early_reversal_forward_test.csv`

The Early Reversal layer uses the same H1/H4/H12/H24 future-only methodology, but stores its signals separately from V2.0.

This separation is important: the system must prove whether the earlier signal provides useful lead time rather than mixing Early and PRE performance together.

**No profitability claim is made until a meaningful sample has accumulated.**

## GitHub Actions automation

Production workflow:

`.github/workflows/reversal-scanner.yml`

It supports:

- Scheduled execution every 15 minutes
- Manual `workflow_dispatch`
- Core-file push validation on `main`
- Python 3.12
- Syntax validation
- Diagnostic self-tests
- Early Reversal regression tests
- Watchlist schema validation
- Early forward-test schema validation
- Persistence of scanner and forward-test data
- Concurrency protection against overlapping scanner runs

GitHub scheduled workflows use POSIX cron and run on the default branch; GitHub documents a minimum schedule interval of five minutes. citeturn0search0turn0search1

The scanner is **not an auto-trader**. GitHub Actions only performs analysis and persists research data.

## Output files

### `data/universe_watchlist.csv`

Contains:

- Long/short scores
- Score gap to 70
- Directional bias
- V2.1 diagnostic status and blockers
- Early Reversal status and score
- Early component values
- Side-specific V2.0 components
- Price/range/ATR information
- Volume and taker information
- Funding and 24-hour change
- Selection state

Selection states:

- `TARGET` — valid V2.0 directional signal
- `EARLY` — valid Early Reversal condition without V2.0 confirmation
- `WATCH` — directional V2.0 candidate above 55 but below signal threshold
- `MONITOR` — score >= 50 without a valid directional signal
- `SKIP` — below monitoring threshold

### `data/reversal_forward_test.csv`

V2.0 PRE-EXPANSION snapshots and future outcomes.

### `data/early_reversal_forward_test.csv`

V2.1 Early Reversal snapshots and future outcomes.

## Risk model

Current capital parameters:

- Capital: **Rp900,000**
- Maximum account risk: **2% = Rp18,000 per trade**
- Stop distance: adaptive, bounded between **2% and 7%**
- Position size: capped at available capital
- Planned targets: **1.5R / 3R / 5R**

These are research risk parameters, not promises of return.

## Current provider limitations

The GitHub-hosted runner environment has recently returned:

- Binance Futures: HTTP 451
- Bybit Futures: HTTP 403
- Bitget Futures: working public-data provider

The provider chain falls through to the next provider when an earlier provider is unavailable.

## Interpretation rules

### Early does not mean guaranteed

`EARLY REVERSAL` means the configured early evidence is present. It is not a probability-of-profit guarantee.

### NEAR is not an entry

`NEAR LONG` and `NEAR SHORT` indicate proximity to the V2.0 threshold, not an approved trade.

### MONITOR is not an entry

Monitoring candidates still require the actual configured gates before becoming V2.0 directional signals.

### No signal is a valid result

If the market does not present the required evidence, the correct output is `NO SETUP`.

## Current status

**Implemented:**

- V2.0 reversal engine
- V2.1 diagnostics
- V2.1 Early Reversal layer
- Dynamic futures universe
- Separate Early Reversal forward testing
- Automated CI validation
- 15-minute production scheduling

**Not yet proven:**

- profitability
- win rate
- expectancy
- robustness across market regimes
- whether Early Reversal materially improves lead time versus PRE-EXPANSION

The next meaningful validation milestone is to accumulate enough Early and PRE signal samples to compare their H1/H4/H12/H24 outcomes.

## Disclaimer

This repository is a research and decision-support project. It is not financial advice and does not place trades. Crypto futures are highly risky and leverage can result in rapid losses. Never treat scanner output as a guarantee of profit.