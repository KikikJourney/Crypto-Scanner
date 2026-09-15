# Early Reversal Detection Specification

## Objective
Detect a reversal candidate **before expansion**, without treating a low/high price alone as a signal.

## Design principles
1. Preserve the existing V2.0 PRE-EXPANSION layer as the baseline.
2. Add EARLY REVERSAL as a separate earlier state rather than lowering the existing 70-point gate.
3. EARLY REVERSAL must not require the existing expansion component to be high.
4. Require evidence of both extreme location and a change in market control (exhaustion + directional flow).
5. A weak structural response remains MONITOR; the scanner does not predict reversals from location alone.
6. Forward testing must measure EARLY and PRE-EXPANSION separately.

## Proposed early evidence
### LONG
- location >= 0.65
- exhaustion >= 0.50
- buyer flow >= 0.55
- composite early score >= 65
- structure is supportive or at least non-invalidating

### SHORT
- location >= 0.65
- exhaustion >= 0.50
- seller flow >= 0.55 (equivalent to current short-flow <= 0.45)
- composite early score >= 65
- rejection/structure is supportive or at least non-invalidating

## Reference weighting
- Location: 30%
- Exhaustion: 25%
- Flow: 25%
- Early structure: 20%

Expansion is intentionally excluded from the early score. It remains an outcome/confirmation feature and is evaluated after the signal.

## State model
- `EARLY REVERSAL LONG/SHORT`: early evidence is sufficient, but expansion confirmation is not required.
- `PRE-EXPANSION LONG/SHORT`: existing stronger V2.0 condition remains unchanged.
- `MONITOR LONG/SHORT`: interesting but incomplete.
- `NO EDGE`: insufficient evidence.

## Validation requirement
Do not deploy the production scoring change until tests prove:
- early signals can fire with low expansion;
- mid-range conditions do not fire;
- weak flow/exhaustion does not fire;
- future-only H1/H4/H12/H24 evaluation distinguishes expansion, failure, ambiguity and unresolved states;
- no look-ahead data is used.
