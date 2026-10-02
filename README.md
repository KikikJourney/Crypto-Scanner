# Zorathvael Crypto Scanner — Alpha Edge Council

The production scanner is a decision-support engine for crypto perpetual futures. It does not auto-trade.

## Production architecture

Market regime -> liquidity event -> order-flow / displacement -> structure response -> pullback calibration -> entry timing -> empirical edge evidence -> execution geometry -> Telegram.

The scanner is no longer based on the old 40-candle entry rule or a stack of independent signal engines.

## Calibration vs geometry

They are separate layers.

Pullback calibration determines WHERE and WHEN an entry is reachable. It uses the displacement leg and a directional 50%-78.6% pullback zone, plus timing confirmation.

Execution geometry is fixed and independent of calibration:

- Margin: 10 USDT
- Leverage: 20x
- SL: -10% of margin
- TP1: +30% of margin
- TP2: +60% of margin
- TP3: +120% of margin

At 20x this corresponds to approximately -0.50%, +1.50%, +3.00%, and +6.00% price movement from the calibrated entry.

## Evidence layer

Historical research measures:

- sample size
- win rate
- expectancy in R
- profit factor
- maximum drawdown
- MFE
- MAE
- train/test separation

A positive historical result is never assumed merely because a setup looks good. The research workflow produces edge_evidence.json as evidence for review.

## Market inputs

The production engine incorporates, when available:

- 5m / 15m / 1h / 4h structure
- volatility and ATR
- volume regime
- liquidity sweeps
- order-flow proxy / signed volume delta
- displacement and exhaustion
- open interest
- funding
- crowding / long-short positioning
- multi-timeframe alignment
- pullback timing
- calibration quality

Missing external data is recorded as unavailable; it is never fabricated.

## Data transport

Binance USDⓈ-M Futures is the primary transport. Bitget is the fallback transport when Binance is unavailable.

## Workflows

- .github/workflows/reversal-scanner.yml — production scan every 5 minutes and manual dispatch.
- .github/workflows/edge-research.yml — scheduled historical edge study.
- .github/workflows/validation-ci.yml — production engine validation.

Legacy scanner workflows are removed from the production path.

## Telegram

Every actionable message exposes absolute prices for calibrated entry / entry zone, SL, TP1, TP2, TP3, margin, and leverage.

Calibration and geometry are explicitly labeled separately.

## Important validation principle

The scanner is designed to measure whether an edge exists; the code must not claim that an edge is proven before out-of-sample evidence supports it.
