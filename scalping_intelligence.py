"""Multi-timeframe scalping intelligence layer.

This module does NOT modify the existing V2.2 scoring engine. It consumes
MTF direction/context and adds execution-quality filters for 4H/1H/30m/15m
context plus 5m entry precision, location, and reversal confirmation.
"""
from datetime import datetime, timezone, timedelta
from math import isfinite

from early_reversal_engine import evaluate_setup as evaluate_early_reversal
from margin_risk_model import (DEFAULT_LEVERAGE, DEFAULT_MARGIN_USDT, MAX_MARGIN_LOSS_PCT, MIN_MARGIN_TP_PCT, MAX_MARGIN_TP_PCT, TP1_MARGIN_PCT, TP2_MARGIN_PCT, TP3_MARGIN_PCT, target_margin_pct_from_price, stop_margin_pct_from_price, build_margin_plan)
from entry_calibration import calibrate_entry
from entry_geometry import build_entry_geometry
from tp_geometry import calibrate_tp


# Version boundary for forward-test evidence. Historical rows without this
# version are legacy evidence and must not be mixed with the current rules.
SCALPING_STRATEGY_VERSION = "scalp-structure-v1"

# Direction-specific historical calibration floors. These values are
# deliberately explicit so production logic, tests, and documentation share
# one source of truth. Revalidate as the forward-test sample grows.
CALIBRATION_CONFIDENCE_LONG = 85.0
CALIBRATION_CONFIDENCE_SHORT = 90.0


def _f(v, default=None):
    try:
        x = float(v)
        return x if isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _close(r): return _f(r[4], 0.0)
def _high(r): return _f(r[2], 0.0)
def _low(r): return _f(r[3], 0.0)
def _volume(r): return _f(r[5], 0.0)


def aggregate(rows, bars):
    if bars <= 0:
        raise ValueError("bars must be positive")
    usable = len(rows) - len(rows) % bars
    out = []
    for i in range(0, usable, bars):
        g = rows[i:i + bars]
        out.append([g[0][0], g[0][1], max(_high(x) for x in g),
                    min(_low(x) for x in g), _close(g[-1]),
                    sum(_volume(x) for x in g)])
    return out


def ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    for item in values[period:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        delta = b - a
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def atr(rows, period=14):
    if len(rows) < 2:
        return None
    trs, previous = [], None
    for row in rows:
        high, low, close = _high(row), _low(row), _close(row)
        tr = high - low if previous is None else max(
            high - low, abs(high - previous), abs(low - previous))
        trs.append(tr)
        previous = close
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _countertrend_early_reversal_allowed(
    direction, score_4h, score_1h, early_score, v2_score,
    opposing_score_4h=0.0, opposing_score_1h=0.0,
):
    """Allow early reversals against MTF trend only with stronger confirmation.

    A candidate is countertrend when neither its 4H nor 1H trend score supports
    the trade direction. If the opposite direction is actually confirmed on
    either higher timeframe, early reversal must wait for V2.2 confirmation.
    This prevents a perfect local reversal score from overriding a live 1H/4H
    trend without independent confirmation.
    """
    countertrend = score_4h == 0.0 and score_1h == 0.0
    if not countertrend:
        return True
    opposing_trend = opposing_score_4h >= 1.0 or opposing_score_1h >= 1.0
    if opposing_trend:
        return v2_score >= 80.0
    return early_score >= 0.90 or v2_score >= 80.0

def _trend_score(rows, direction):
    closes = [_close(x) for x in rows]
    n = len(closes)
    if n >= 50:
        fast_period, slow_period = 20, 50
    elif n >= 20:
        fast_period, slow_period = 8, 20
    elif n >= 10:
        fast_period, slow_period = 3, 8
    else:
        return 0.0
    fast, slow = ema(closes, fast_period), ema(closes, slow_period)
    if fast is None or slow is None:
        return 0.0
    if direction == "LONG":
        return 1.0 if fast >= slow and closes[-1] >= fast else 0.0
    return 1.0 if fast <= slow and closes[-1] <= fast else 0.0


def _structure_score(rows, direction):
    if len(rows) < 6:
        return 0.0
    recent = rows[-6:-1]
    close = _close(rows[-1])
    high = max(_high(x) for x in recent)
    low = min(_low(x) for x in recent)
    if direction == "LONG":
        return 1.0 if close > high else 0.5 if close >= low else 0.0
    return 1.0 if close < low else 0.5 if close <= high else 0.0


def _liquidity_sweep(rows, direction):
    if len(rows) < 8:
        return 0.0
    previous, last = rows[-7:-1], rows[-1]
    prior_high = max(_high(x) for x in previous)
    prior_low = min(_low(x) for x in previous)
    if direction == "LONG":
        return 1.0 if _low(last) < prior_low and _close(last) > prior_low else 0.0
    return 1.0 if _high(last) > prior_high and _close(last) < prior_high else 0.0


def _volume_score(rows):
    if len(rows) < 21:
        return 0.0
    base = sum(_volume(x) for x in rows[-21:-1]) / 20.0
    return min(1.0, max(0.0, (_volume(rows[-1]) / base - 1.0))) if base else 0.0


def _location_score(rows, direction, lookback=32):
    """Prefer lower-half LONG entries and upper-half SHORT entries."""
    if len(rows) < max(8, lookback):
        return 0.0
    window = rows[-lookback:]
    high = max(_high(x) for x in window)
    low = min(_low(x) for x in window)
    span = high - low
    if span <= 0:
        return 0.0
    position = (_close(rows[-1]) - low) / span
    if direction == "LONG":
        return 1.0 if position <= 0.35 else 0.5 if position <= 0.50 else 0.0
    return 1.0 if position >= 0.65 else 0.5 if position >= 0.50 else 0.0


def _reversal_score(rows, direction):
    """Require a 5m rejection/sweep or a fresh directional recovery."""
    if len(rows) < 8:
        return 0.0
    previous, last = rows[-7:-1], rows[-1]
    prior_high = max(_high(x) for x in previous)
    prior_low = min(_low(x) for x in previous)
    last_open, last_close = _f(last[1], _close(last)), _close(last)
    last_high, last_low = _high(last), _low(last)
    candle_range = last_high - last_low
    if candle_range <= 0:
        return 0.0
    bullish = last_close > last_open
    bearish = last_close < last_open
    upper = (last_close - last_low) / candle_range >= 0.60
    lower = (last_high - last_close) / candle_range >= 0.60
    if direction == "LONG":
        sweep = last_low < prior_low and last_close > prior_low
        recovery = bullish and upper and last_close > _close(previous[-1])
        return 1.0 if sweep else 0.5 if recovery else 0.0
    sweep = last_high > prior_high and last_close < prior_high
    recovery = bearish and lower and last_close < _close(previous[-1])
    return 1.0 if sweep else 0.5 if recovery else 0.0



def _entry_location_100(rows_5m, direction, micro_atr):
    """Backward-compatible composite helper.

    Production build_plan calls calibration and geometry separately. This helper
    remains for research/tests that need the combined diagnostic view.
    """
    calibrated = calibrate_entry(rows_5m, direction, micro_atr)
    if calibrated is None:
        return None
    geometry = build_entry_geometry(direction, calibrated["entry"])
    return {**calibrated, "stop": geometry["stop"], "stop_buffer": abs(calibrated["entry"] - geometry["stop"])}

def _opposing_structure_target(rows, direction, entry, risk, min_reward_r=1.40, max_reward_r=3.50):
    """Return the strongest opposing closing-price swing within a sane R range."""
    if len(rows) < 7 or entry <= 0 or risk <= 0:
        return None

    window = rows[-32:]
    min_target = (
        entry + min_reward_r * risk
        if direction == "LONG"
        else entry - min_reward_r * risk
    )
    max_target = (
        entry + max_reward_r * risk
        if direction == "LONG"
        else entry - max_reward_r * risk
    )

    candidates = []
    for i in range(2, len(window) - 2):
        level = _close(window[i])
        left = _close(window[i - 1])
        right = _close(window[i + 1])

        if direction == "LONG":
            if level >= min_target and level >= left and level >= right:
                candidates.append(level)
        else:
            if level <= min_target and level <= left and level <= right:
                candidates.append(level)

    if direction == "LONG":
        # Use the strongest valid opposing swing inside the reward envelope.
        # This keeps TP structure-driven while avoiding stale/outlier extremes.
        valid = [level for level in candidates if min_target <= level <= max_target]
        return max(valid) if valid else None

    # Mirror LONG for SHORT: strongest valid opposing swing inside the envelope.
    valid = [level for level in candidates if max_target <= level <= min_target]
    return min(valid) if valid else None

def _select_tp_margin_pct(direction, entry, structural_target, features, confidence):
    """Select a feasible target margin; does not calculate entry geometry."""
    features = features or {}
    whale = max(0.0, min(1.0, _f(features.get("whale_score"), 0.0)))
    order_flow = max(0.0, min(1.0, _f(features.get("order_flow_score"), 0.0)))
    liquidation = max(0.0, min(1.0, _f(features.get("liquidation_score"), 0.0)))
    sweep = max(0.0, min(1.0, _f(features.get("liquidity_sweep_score"), 0.0)))
    volume = max(0.0, min(1.0, _f(features.get("volume_score"), 0.0)))
    conviction = (
        0.20 * whale + 0.20 * order_flow + 0.15 * liquidation +
        0.15 * sweep + 0.10 * volume +
        0.20 * max(0.0, min(1.0, confidence / 100.0))
    )
    desired_margin_pct = MIN_MARGIN_TP_PCT + conviction * (MAX_MARGIN_TP_PCT - MIN_MARGIN_TP_PCT)
    if structural_target is None:
        # No opposing structure is available, but canonical geometry still
        # provides a valid TP1. Do not suppress discovery solely for that.
        return MIN_MARGIN_TP_PCT, conviction, None
    structural_margin_pct = target_margin_pct_from_price(
        entry, structural_target, direction, DEFAULT_LEVERAGE
    )
    if structural_margin_pct <= 0:
        return MIN_MARGIN_TP_PCT, conviction, structural_margin_pct

    # Geometry owns the actual TP price. Structure only influences which
    # canonical rung is selected; it cannot create a custom TP.
    candidates = [MIN_MARGIN_TP_PCT, TP2_MARGIN_PCT, TP3_MARGIN_PCT]
    feasible = [x for x in candidates if x <= structural_margin_pct]
    selected = min(feasible, key=lambda x: abs(x - desired_margin_pct)) if feasible else MIN_MARGIN_TP_PCT
    return selected, conviction, structural_margin_pct

def _timestamp(row):
    try:
        value = float(row[0])
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def infer_direction(rows_15m, rows_5m):
    """Infer trade side from MTF trend/structure without requiring V2.2."""
    if len(rows_15m) < 160 or len(rows_5m) < 60:
        return None
    tf1h, tf4h, tf30 = aggregate(rows_15m, 4), aggregate(rows_15m, 16), aggregate(rows_15m, 2)
    if len(tf1h) < 40 or len(tf4h) < 8 or len(tf30) < 20:
        return None
    long_sum = sum((_trend_score(tf4h, "LONG"), _trend_score(tf1h, "LONG"),
                    _structure_score(tf30, "LONG"), _structure_score(rows_15m, "LONG")))
    short_sum = sum((_trend_score(tf4h, "SHORT"), _trend_score(tf1h, "SHORT"),
                     _structure_score(tf30, "SHORT"), _structure_score(rows_15m, "SHORT")))
    if long_sum >= 3.0 and long_sum > short_sum:
        return "LONG"
    if short_sum >= 3.0 and short_sum > long_sum:
        return "SHORT"
    return None


def build_plan(direction, rows_15m, rows_5m, v2_score, v2_features, require_v2_direction=True,
               early_reversal=False):
    """Build a plan with either the established MTF gate or early-reversal gate."""
    if direction not in {"LONG", "SHORT"}:
        return {"status": "NO-TRADE", "reason": "no trade direction"}
    if len(rows_15m) < 160 or len(rows_5m) < 60:
        return {"status": "DATA-LIMITED", "reason": "insufficient MTF candles"}

    tf30, tf1h, tf4h = aggregate(rows_15m, 2), aggregate(rows_15m, 4), aggregate(rows_15m, 16)
    if len(tf30) < 20 or len(tf1h) < 40 or len(tf4h) < 8:
        return {"status": "DATA-LIMITED", "reason": "insufficient aggregated timeframe history"}

    score_4h = _trend_score(tf4h, direction)
    score_1h = _trend_score(tf1h, direction)
    score_30 = _structure_score(tf30, direction)
    score_15 = _structure_score(rows_15m, direction)
    location_15 = _location_score(rows_15m, direction)
    reversal_5 = _reversal_score(rows_5m, direction)
    sweep_5 = _liquidity_sweep(rows_5m, direction)
    volume_5 = _volume_score(rows_5m)
    closes5 = [_close(x) for x in rows_5m]
    rsi5 = rsi(closes5, 14)
    momentum_5 = 1.0 if (
        (direction == "LONG" and rsi5 is not None and 45 <= rsi5 <= 68) or
        (direction == "SHORT" and rsi5 is not None and 32 <= rsi5 <= 55)
    ) else 0.0

    early = evaluate_early_reversal(rows_15m, rows_5m, direction) if early_reversal else None

    if early_reversal:
        if not early["eligible"]:
            return {
                "status": "WAIT", "direction": direction, "confidence": round(100.0 * early["score"], 1),
                "location_15m": early["location_15m"], "reversal_5m": early["reversal_trigger_5m"],
                "exhaustion_15m": early["exhaustion_15m"], "base_15m": early["base_15m"],
                "structure_shift_5m": early["structure_shift_5m"],
                "reversal_trigger_5m": early["reversal_trigger_5m"],
                "reason": early["reason"],
            }
        # Early-reversal mode deliberately does not require trend alignment:
        # the setup is expected to form while the preceding move is still
        # directional. V2.2 remains an optional confirmation input.
        confidence = 100.0 * early["score"]
        v2_confirmation = _f(v2_score, 0.0)
        if v2_confirmation >= 80.0:
            confidence = min(100.0, confidence + 3.0)
        opposite_direction = "SHORT" if direction == "LONG" else "LONG"
        opposing_score_4h = _trend_score(tf4h, opposite_direction)
        opposing_score_1h = _trend_score(tf1h, opposite_direction)
        if not _countertrend_early_reversal_allowed(
            direction, score_4h, score_1h, early["score"], v2_confirmation,
            opposing_score_4h, opposing_score_1h,
        ):
            return {
                "status": "WAIT",
                "direction": direction,
                "confidence": round(confidence, 1),
                "location_15m": early["location_15m"],
                "reversal_5m": early["reversal_trigger_5m"],
                "reason": "countertrend early reversal requires stronger confirmation",
            }
    else:
        if location_15 == 0.0:
            return {"status": "WAIT", "direction": direction, "confidence": 0.0,
                    "location_15m": location_15, "reversal_5m": reversal_5,
                    "reason": "entry location is unfavorable for direction"}
        # ACTIONs must come from the preferred third of the 15m range.
        if location_15 < 1.0:
            return {"status": "WAIT", "direction": direction, "confidence": 0.0,
                    "location_15m": location_15, "reversal_5m": reversal_5,
                    "reason": "entry location is only mid-range; ACTION requires preferred range location"}
        if reversal_5 == 0.0:
            return {"status": "WAIT", "direction": direction, "confidence": 0.0,
                    "location_15m": location_15, "reversal_5m": reversal_5,
                    "reason": "no 5m pullback/reversal confirmation"}
        if reversal_5 < 1.0:
            return {"status": "WAIT", "direction": direction, "confidence": 0.0,
                    "location_15m": location_15, "reversal_5m": reversal_5,
                    "rsi_5m": round(rsi5, 2) if rsi5 is not None else None,
                    "reason": "reversal confirmation is not a true sweep/rejection"}

        confidence = 100.0 * (
            0.15 * score_4h + 0.15 * score_1h + 0.10 * score_30 + 0.10 * score_15 +
            0.20 * location_15 + 0.20 * reversal_5 + 0.05 * sweep_5 +
            0.03 * volume_5 + 0.02 * momentum_5
        )

    calibration_confidence_floor = (
        CALIBRATION_CONFIDENCE_LONG if direction == "LONG"
        else CALIBRATION_CONFIDENCE_SHORT
    )

    # Historical calibration evidence is direction-asymmetric. Keep the gate
    # after entry calibration so it filters execution quality without changing
    # the calibrated price or geometry responsibilities.
    if confidence < calibration_confidence_floor:
        return {
            "status": "WAIT", "direction": direction,
            "confidence": round(confidence, 1),
            "location_15m": location_15, "reversal_5m": reversal_5,
            "calibration_confidence_floor": calibration_confidence_floor,
            "reason": "historical calibration confidence floor not met",
        }

    if not early_reversal and not require_v2_direction:
        alignment = score_4h + score_1h + score_30 + score_15
        if alignment < 3.0:
            return {"status": "WAIT", "direction": direction,
                    "confidence": round(confidence, 1),
                    "location_15m": location_15, "reversal_5m": reversal_5,
                    "reason": "MTF directional alignment below threshold"}
        if _f(v2_score, 0.0) >= 80.0:
            confidence = min(100.0, confidence + 3.0)

    price = _close(rows_5m[-1])
    atr15 = _f(v2_features.get("atr"))
    if not price or not atr15:
        return {"status": "DATA-LIMITED", "reason": "price/ATR unavailable"}

    micro_atr = atr(rows_5m, 14) or atr15 / 3.0

    # LAYER 1 — ENTRY CALIBRATION.
    # This layer may move/qualify the entry, but cannot define SL/TP.
    entry_calibration = calibrate_entry(rows_5m, direction, micro_atr, rows_15m=rows_15m, context=v2_features)
    if entry_calibration is None:
        return {"status": "DATA-LIMITED", "reason": "100-candle entry calibration unavailable"}

    entry = entry_calibration["entry"]
    entry_low = entry
    entry_high = entry

    if direction == "LONG" and entry >= price:
        return {"status": "WAIT", "reason": "calibrated long entry is not below current price"}
    if direction == "SHORT" and entry <= price:
        return {"status": "WAIT", "reason": "calibrated short entry is not above current price"}

    rebound_atr = (
        (price - entry_calibration["anchor"]) / micro_atr
        if direction == "LONG"
        else (entry_calibration["anchor"] - price) / micro_atr
    )
    min_rebound_atr = 0.20
    if rebound_atr < min_rebound_atr:
        return {
            "status": "WAIT",
            "reason": "100-candle entry calibration has not rebounded enough",
            "rebound_atr": round(rebound_atr, 3),
            "min_rebound_atr": min_rebound_atr,
            "timing_score": entry_calibration.get("timing_score"),
        }

    entry_distance_atr = entry_calibration["distance_atr"]
    max_entry_distance_atr = 0.90
    if entry_distance_atr > max_entry_distance_atr:
        return {
            "status": "WAIT",
            "reason": "calibrated entry is too far from current price",
            "entry_distance_atr": round(entry_distance_atr, 3),
            "max_entry_distance_atr": max_entry_distance_atr,
            "timing_score": entry_calibration.get("timing_score"),
        }

    # LAYER 2 — ENTRY GEOMETRY.
    # Geometry starts only after the calibrated entry is final.
    base_geometry = build_entry_geometry(direction, entry)
    stop = base_geometry["stop"]
    risk = entry - stop if direction == "LONG" else stop - entry
    if risk <= 0:
        return {"status": "INVALID", "reason": "non-positive execution geometry risk"}

    stop_margin_pct = stop_margin_pct_from_price(entry, stop, direction, DEFAULT_LEVERAGE)
    if stop_margin_pct > MAX_MARGIN_LOSS_PCT:
        return {
            "status": "WAIT", "direction": direction, "confidence": round(confidence, 1),
            "location_15m": location_15, "reversal_5m": reversal_5,
            "risk_pct": round(risk / price * 100.0, 4),
            "stop_margin_pct": round(stop_margin_pct, 3),
            "max_margin_loss_pct": MAX_MARGIN_LOSS_PCT,
            "reason": "entry geometry exceeds 10% margin-loss budget",
        }

    risk_pct = risk / price * 100.0
    structural_target = _opposing_structure_target(
        rows_15m, direction, entry, risk, min_reward_r=1.0, max_reward_r=20.0
    )
    tp_calibration = calibrate_tp(
        rows_15m, rows_5m, direction, entry, stop, context=v2_features
    )
    if tp_calibration is None:
        return {
            "status": "WAIT", "direction": direction,
            "confidence": round(confidence, 1),
            "location_15m": location_15, "reversal_5m": reversal_5,
            "risk_pct": round(risk_pct, 4),
            "reason": "TP geometry has no supported 2R..8R price target",
        }
    margin_plan = build_entry_geometry(
        direction,
        entry,
        structural_target=structural_target,
        target_price=tp_calibration["target"],
    )
    target = margin_plan["target"]
    reward_r = tp_calibration["reward_r"]
    flow_conviction = tp_calibration["flow_conviction"]
    structural_margin_pct = margin_plan.get("structural_target_margin_pct")
    if confidence < 80.0:
        return {
            "status": "WAIT", "direction": direction,
            "confidence": round(confidence, 1),
            "v2_score": round(_f(v2_score, 0.0), 1),
            "location_15m": location_15, "reversal_5m": reversal_5,
            "risk_pct": round(risk_pct, 4),
            "reason": "confidence below action threshold",
        }
    status = "ACTION LONG" if direction == "LONG" else "ACTION SHORT"
    ts = _timestamp(rows_5m[-1])
    latest_5m_ts = _timestamp(rows_5m[-1])
    latest_5m_close_ts = latest_5m_ts + timedelta(minutes=5) if latest_5m_ts else None
    latest_15m_ts = _timestamp(rows_15m[-1])
    # Execution signals expire after one closed 5m candle. The next scan
    # must re-evaluate price and structure instead of carrying stale entries.
    valid_until = latest_5m_close_ts + timedelta(minutes=5) if latest_5m_close_ts else None
    return {
        "status": status, "direction": direction, "strategy_version": SCALPING_STRATEGY_VERSION,
        "confidence": round(confidence, 1),
        "v2_score": round(_f(v2_score, 0.0), 1), "entry": round(entry, 12),
        "entry_low": round(entry_low, 12), "entry_high": round(entry_high, 12),
        "stop": round(stop, 12), "target": round(target, 12),
        "risk_pct": round(risk_pct, 4), "reward_r": round(reward_r, 2),
        "margin_usdt": margin_plan["margin_usdt"], "leverage": margin_plan["leverage"],
        "notional_usdt": margin_plan["notional_usdt"], "stop_margin_pct": round(margin_plan["stop_margin_pct"], 3),
        "tp_margin_pct": round(margin_plan["tp_margin_pct"], 3), "max_loss_usdt": round(margin_plan["max_loss_usdt"], 6),
        "target_pnl_usdt": round(margin_plan["target_pnl_usdt"], 6), "target_price_move_pct": round(margin_plan["target_price_move_pct"], 4),
        "tp1": round(margin_plan["tp1"], 12), "tp2": round(margin_plan["tp2"], 12), "tp3": round(margin_plan["tp3"], 12),
        "tp1_margin_pct": margin_plan["tp1_margin_pct"], "tp2_margin_pct": margin_plan["tp2_margin_pct"], "tp3_margin_pct": margin_plan["tp3_margin_pct"],
        "tp1_pnl_usdt": margin_plan["tp1_pnl_usdt"], "tp2_pnl_usdt": margin_plan["tp2_pnl_usdt"], "tp3_pnl_usdt": margin_plan["tp3_pnl_usdt"],
        "flow_conviction": round(flow_conviction, 3), "structural_target_margin_pct": round(structural_margin_pct, 3) if structural_margin_pct is not None else None,
        "tp_target_source": tp_calibration["target_source"], "tp_trend_strength": tp_calibration["trend_strength"],
        "tp_desired_reward_r": tp_calibration["desired_reward_r"],
        "entry_calibration": "100-candle + volume/flow/regime",
        "calibration_inputs": entry_calibration.get("calibration_inputs", ""),
        "timing_score": entry_calibration.get("timing_score"),
        "volume_ratio_5m": entry_calibration.get("volume_ratio_5m"),
        "volume_regime": entry_calibration.get("volume_regime", ""),
        "flow_score": entry_calibration.get("flow_score"),
        "sweep_score": entry_calibration.get("sweep_score"),
        "regime_score_15m": entry_calibration.get("regime_score_15m"),
        "entry_anchor_100": round(entry_calibration["anchor"], 12),
        "entry_buffer": round(entry_calibration["buffer"], 12),
        "entry_buffer_atr": entry_calibration.get("buffer_atr"),
        "entry_distance_atr": round(entry_distance_atr, 3),
        "entry_rebound_atr": round(rebound_atr, 3),
        "target_structure": round(structural_target, 12) if structural_target is not None else None,
        "rsi_5m": round(rsi5, 2) if rsi5 is not None else None,
        "trend_4h": score_4h, "trend_1h": score_1h, "structure_30m": score_30,
        "structure_15m": score_15, "location_15m": location_15,
        "reversal_5m": reversal_5, "liquidity_sweep_5m": sweep_5,
        "volume_5m": round(volume_5, 3),
        "exhaustion_15m": early["exhaustion_15m"] if early_reversal else 0.0,
        "base_15m": early["base_15m"] if early_reversal else 0.0,
        "structure_shift_5m": early["structure_shift_5m"] if early_reversal else 0.0,
        "reversal_trigger_5m": early["reversal_trigger_5m"] if early_reversal else reversal_5,
        "early_reversal_score": early["score"] if early_reversal else 0.0,
        "valid_until": valid_until.isoformat() if valid_until else "",
        "latest_closed_5m_timestamp": latest_5m_ts.isoformat() if latest_5m_ts else "",
        "latest_closed_5m_close_timestamp": latest_5m_close_ts.isoformat() if latest_5m_close_ts else "",
        "latest_closed_15m_timestamp": latest_15m_ts.isoformat() if latest_15m_ts else "",
        "timeframes": "4H/1H/30m/15m/5m",
        "reason": (
            "EARLY REVERSAL: extreme location + exhaustion + base + trigger"
            if early_reversal else
            ("MTF brain + V2.2 confirmation" if require_v2_direction
             else "MTF brain: direction + location + reversal + execution")
        ),
    }
