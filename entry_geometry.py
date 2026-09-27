"""Entry geometry layer.

This module answers only: given a FINAL calibrated entry, what risk/target
geometry is permitted by the global margin model?

Entry calibration and market-structure discovery happen elsewhere.
"""

from margin_risk_model import (
    DEFAULT_LEVERAGE,
    DEFAULT_MARGIN_USDT,
    MAX_MARGIN_LOSS_PCT,
    build_margin_plan,
    stop_margin_pct_from_price,
    target_margin_pct_from_price,
)


def build_anchor_stop(direction, anchor, current_price, micro_atr, stop_buffer_atr=0.45, stop_floor_pct=0.10):
    """Build a research structural stop from the calibrated 100-candle anchor.

    This is geometry only. It never changes the calibrated entry.
    """
    anchor = float(anchor)
    current_price = float(current_price)
    micro_atr = float(micro_atr)
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if anchor <= 0 or current_price <= 0 or micro_atr <= 0:
        raise ValueError("anchor/current_price/micro_atr must be positive")
    buffer = max(micro_atr * stop_buffer_atr, current_price * stop_floor_pct / 100.0)
    return anchor - buffer if direction == "LONG" else anchor + buffer


def build_entry_geometry(
    direction,
    entry,
    *,
    structural_stop=None,
    structural_target=None,
    selected_tp_margin_pct=None,
):
    """Build/validate SL and TP geometry from the final calibrated entry.

    The margin model is the hard risk boundary:
    - margin 10 USDT
    - leverage 25x
    - maximum SL loss 5% of margin
    - TP ladder 30/60/120% of margin

    A structural stop/target is treated as a market constraint, never as an
    alternative entry-calibration mechanism. Structural levels are accepted
    only when they remain inside the global risk/target envelope.
    """
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")

    if structural_stop is not None:
        stop_risk_pct = stop_margin_pct_from_price(
            entry, structural_stop, direction, DEFAULT_LEVERAGE
        )
        if 0 < stop_risk_pct <= MAX_MARGIN_LOSS_PCT:
            stop = float(structural_stop)
            stop_margin_pct = stop_risk_pct
        else:
            stop = None
            stop_margin_pct = MAX_MARGIN_LOSS_PCT
    else:
        stop = None
        stop_margin_pct = MAX_MARGIN_LOSS_PCT

    if stop is None:
        base = build_margin_plan(
            direction,
            entry,
            DEFAULT_MARGIN_USDT,
            DEFAULT_LEVERAGE,
            MAX_MARGIN_LOSS_PCT,
            30.0,
        )
        stop = base["stop"]
        stop_margin_pct = base["stop_margin_pct"]

    if selected_tp_margin_pct is None:
        selected_tp_margin_pct = 30.0

    plan = build_margin_plan(
        direction,
        entry,
        DEFAULT_MARGIN_USDT,
        DEFAULT_LEVERAGE,
        stop_margin_pct,
        selected_tp_margin_pct,
    )

    if structural_target is not None:
        structural_margin_pct = target_margin_pct_from_price(
            entry, structural_target, direction, DEFAULT_LEVERAGE
        )
        if structural_margin_pct > 0:
            plan["structural_target"] = float(structural_target)
            plan["structural_target_margin_pct"] = structural_margin_pct
        else:
            plan["structural_target"] = None
            plan["structural_target_margin_pct"] = None
    else:
        plan["structural_target"] = None
        plan["structural_target_margin_pct"] = None

    # The returned SL/TP values are always derived from the final entry and
    # the canonical margin model. The three TP ladder levels are never hidden.
    return plan
