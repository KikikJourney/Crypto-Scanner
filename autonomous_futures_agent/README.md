# Autonomous Futures Agent — Foundation

This folder is an isolated, exchange-independent foundation. It does not submit orders, contain API credentials, or enable live trading.

## Current defaults

- Margin allocation: 5 USDT per position
- Leverage planning: 20x
- Margin mode: isolated
- Stop-loss geometry: 10% of allocated margin
- Take-profit geometry: 30%, 60%, and 120% of allocated margin
- Live trading: disabled by default

At 5 USDT margin and 20x leverage, planned notional is 100 USDT. The pure risk calculator translates margin-PnL percentages into approximate price levels. Fees, funding, slippage, exchange filters, partial fills, and liquidation mechanics are not included in these illustrative levels; the venue adapter must account for them before any live use.

## Why live trading is blocked

The requested exchange was supplied as “Lainnya” without an actual venue name. Exchange-specific signing, endpoints, symbol rules, leverage setup, position mode, and protective-order semantics cannot safely be guessed. UnconfiguredExchange refuses account queries and order actions. assert_live_ready is a guard only, not an order executor or proof of profitability.

## Tests

Run from the repository root:

    python -m unittest discover -s autonomous_futures_agent/tests -v

## Required before live execution

1. Name the exact exchange and contract type (USDT-margined perpetual or coin-margined).
2. Implement its official API adapter with signed requests, clock-skew handling, rate limits, and exchange error mapping.
3. Read account mode and open positions; verify symbol filters, minimum quantity/notional, and isolated margin.
4. Reconcile orders after timeouts so retries cannot create duplicate positions.
5. Place and verify exchange-side stop-loss protection; handle partial fills and reduce-only exits.
6. Run deterministic unit tests, exchange sandbox/testnet integration tests, and a read-only account preflight.
7. Deploy a persistent worker with a watchdog and alerting. GitHub Actions scheduled workflows are useful for CI and periodic checks but are not a guaranteed continuous low-latency trading process.
8. Enable live execution only after explicit review; use an API key with withdrawals disabled and the narrowest available permissions/IP allowlist.

Cue.im can supervise the agent and routines if the account/runtime supports the required shell, secrets, and persistent process. This repository change does not configure Cue, store credentials, or deploy a worker.
