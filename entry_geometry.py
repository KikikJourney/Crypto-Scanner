"""Execution geometry after entry timing is final.

Entry calibration answers WHERE/WHEN. This module answers SL/TP price geometry.
TP may be a concrete structure/flow-calibrated price rather than a fixed rung.
"""
from margin_risk_model import (
    DEFAULT_LEVERAGE, DEFAULT_MARGIN_USDT, MAX_MARGIN_LOSS_PCT,
    MIN_MARGIN_TP_PCT, MAX_MARGIN_TP_PCT, TP1_MARGIN_PCT,
    build_margin_plan, target_margin_pct_from_price,
)


def build_anchor_stop(direction, anchor, current_price, micro_atr,
                      stop_buffer_atr=0.45, stop_floor_pct=0.10):
    anchor, current_price, micro_atr = float(anchor), float(current_price), float(micro_atr)
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if anchor <= 0 or current_price <= 0 or micro_atr <= 0:
        raise ValueError("anchor/current_price/micro_atr must be positive")
    buffer = max(micro_atr * stop_buffer_atr, current_price * stop_floor_pct / 100.0)
    return anchor - buffer if direction == "LONG" else anchor + buffer


def build_entry_geometry(direction, entry, *, structural_stop=None,
                         structural_target=None, selected_tp_margin_pct=None,
                         target_price=None):
    # target_price is authoritative when supplied and is validated against 2R..8R.
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")

    if target_price is not None:
        selected_tp_margin_pct = target_margin_pct_from_price(
            entry, float(target_price), direction, DEFAULT_LEVERAGE
        )
        if not 20.0 <= selected_tp_margin_pct <= 80.0:
            raise ValueError("target_price must produce 2R..8R under the canonical risk budget")
    else:
        if selected_tp_margin_pct is None:
            selected_tp_margin_pct = TP1_MARGIN_PCT
        selected_tp_margin_pct = float(selected_tp_margin_pct)
        if not MIN_MARGIN_TP_PCT <= selected_tp_margin_pct <= MAX_MARGIN_TP_PCT:
            raise ValueError("selected_tp_margin_pct must be between 20% and 80%")

    build_margin_pct = selected_tp_margin_pct if 30.0 <= selected_tp_margin_pct <= 120.0 else 30.0
    plan = build_margin_plan(
        direction, entry, DEFAULT_MARGIN_USDT, DEFAULT_LEVERAGE,
        MAX_MARGIN_LOSS_PCT, build_margin_pct
    )
    if target_price is not None:
        plan["target"] = float(target_price)
        plan["tp_margin_pct"] = selected_tp_margin_pct
        plan["target_price_move_pct"] = abs(float(target_price) - float(entry)) / float(entry) * 100.0
        plan["target_pnl_usdt"] = DEFAULT_MARGIN_USDT * selected_tp_margin_pct / 100.0
        plan["reward_to_r"] = selected_tp_margin_pct / MAX_MARGIN_LOSS_PCT
    plan["structural_stop"] = float(structural_stop) if structural_stop is not None else None
    plan["structural_target"] = float(structural_target) if structural_target is not None else None
    plan["structural_target_margin_pct"] = (
        target_margin_pct_from_price(entry, structural_target, direction, DEFAULT_LEVERAGE)
        if structural_target is not None else None
    )
    plan["target_source"] = "calibrated_price" if target_price is not None else "margin_rung"
    plan["geometry_contract"] = "10USDT/20x/SL-10%/TP-2R..8R"
    return plan
