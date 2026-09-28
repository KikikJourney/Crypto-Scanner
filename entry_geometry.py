"""Entry geometry layer.

This module answers only: given a FINAL calibrated entry, what risk/target
geometry is permitted by the global margin model?

Entry calibration and market-structure discovery happen elsewhere.
"""

from margin_risk_model import (
    DEFAULT_LEVERAGE,
    DEFAULT_MARGIN_USDT,
    MAX_MARGIN_LOSS_PCT,
    TP1_MARGIN_PCT,
    TP2_MARGIN_PCT,
    TP3_MARGIN_PCT,
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
    """Build canonical SL/TP geometry from the FINAL calibrated entry.

    Geometry is independent from entry timing/calibration:
    10 USDT margin, 20x leverage, SL -10% margin, TP1/TP2/TP3
    +30/+60/+120% margin.
    """
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")

    if selected_tp_margin_pct is None:
        selected_tp_margin_pct = TP1_MARGIN_PCT
    selected_tp_margin_pct = float(selected_tp_margin_pct)

    ladder = (TP1_MARGIN_PCT, TP2_MARGIN_PCT, TP3_MARGIN_PCT)
    selected_tp_margin_pct = min(ladder, key=lambda x: abs(x - selected_tp_margin_pct))

    plan = build_margin_plan(
        direction,
        entry,
        DEFAULT_MARGIN_USDT,
        DEFAULT_LEVERAGE,
        MAX_MARGIN_LOSS_PCT,
        selected_tp_margin_pct,
    )

    # Structural levels are diagnostics only. They cannot move canonical SL/TP.
    plan["structural_stop"] = float(structural_stop) if structural_stop is not None else None
    plan["structural_target"] = float(structural_target) if structural_target is not None else None
    if structural_target is not None:
        structural_margin_pct = target_margin_pct_from_price(
            entry, structural_target, direction, DEFAULT_LEVERAGE
        )
        plan["structural_target_margin_pct"] = (
            structural_margin_pct if structural_margin_pct > 0 else None
        )
    else:
        plan["structural_target_margin_pct"] = None

    plan["geometry_contract"] = "10USDT/20x/SL-10%/TP+30+60+120"
    return plan
