# Autonomous Futures Agent — implementation status

## Status

Foundation only; not deployed and not authorized for live order execution.

## Verified design decisions

- Isolated module under autonomous_futures_agent/ so the existing scanner execution path is unchanged.
- Exchange-independent risk geometry for 5 USDT margin, 20x leverage, SL at -10% margin PnL, TP1/TP2/TP3 at +30%/+60%/+120% margin PnL.
- Live execution disabled by default and an unconfigured exchange adapter that fails closed.
- Unit tests for Long/Short geometry, invalid values, exchange identity, and explicit live acknowledgement.
- CI workflow runs the foundation tests on relevant pull requests.

## Blockers before live

The exchange has not been identified by its actual name. Therefore, no signed API adapter, credential wiring, testnet verification, production deployment, or live order placement is claimed. The next implementation step depends on the venue and contract type.

## Runtime note

Cue's documented server agent and cloud-computer runtimes may support supervision and tool execution, but the actual user's agent runtime, persistent process capability, and secret access must be checked in that account. GitHub Actions has job-duration and schedule reliability constraints and should not be represented as a permanent trading daemon.
