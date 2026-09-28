"""Alpha Hunter opportunity-discovery lane.

This lane is intentionally broader than the reversal/action engines. It detects
15m opportunity regimes (volatility + location + 5m participation) and builds
a reachable 100-candle execution plan. It does not modify scanner_v2.py.
"""
from math import isfinite

from scalping_intelligence import _close, _high, _low, _volume, atr, _opposing_structure_target, _select_tp_margin_pct
from entry_calibration import calibrate_entry
from entry_geometry import build_entry_geometry
from margin_risk_model import DEFAULT_LEVERAGE, DEFAULT_MARGIN_USDT, MAX_MARGIN_LOSS_PCT, target_margin_pct_from_price
from tp_geometry import calibrate_tp


ALPHA_HUNTER_VERSION = "alpha-hunter-v2"
MAX_ALPHA_REWARD_R = 8.0


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _range_position(rows, direction, lookback=32):
    if len(rows) < lookback:
        return 0.5
    window = rows[-lookback:]
    high = max(_high(r) for r in window)
    low = min(_low(r) for r in window)
    span = high - low
    if span <= 0:
        return 0.5
    pos = (_close(rows[-1]) - low) / span
    return pos if direction == "LONG" else 1.0 - pos


def _volume_ratio(rows, period=20):
    if len(rows) < period + 1:
        return 0.0
    base = sum(_volume(r) for r in rows[-period-1:-1]) / period
    return _volume(rows[-1]) / base if base > 0 else 0.0


def _impulse(rows, direction, bars=3):
    if len(rows) < bars + 1:
        return 0.0
    start = _close(rows[-bars-1])
    end = _close(rows[-1])
    if start <= 0:
        return 0.0
    move = (end - start) / start
    return move if direction == "LONG" else -move


def _sweep(rows, direction):
    if len(rows) < 8:
        return 0.0
    previous = rows[-7:-1]
    last = rows[-1]
    prior_low = min(_low(r) for r in previous)
    prior_high = max(_high(r) for r in previous)
    if direction == "LONG":
        return 1.0 if _low(last) < prior_low and _close(last) > prior_low else 0.0
    return 1.0 if _high(last) > prior_high and _close(last) < prior_high else 0.0



def _entry_timing_state(current_price, calibrated_entry, micro_atr, direction=None):
    """Evaluate timing only; the entry zone is directional and geometry-independent."""
    current_price = _f(current_price)
    calibrated_entry = _f(calibrated_entry)
    micro_atr = _f(micro_atr)
    if current_price is None or calibrated_entry is None or micro_atr is None or micro_atr <= 0:
        return {"execution_ready": False, "distance_atr": float("inf"), "reason": "timing inputs unavailable"}
    distance_atr = abs(current_price - calibrated_entry) / micro_atr

    # The scanner's execution zone is the same directional zone exposed to
    # Telegram: LONG enters from entry upward; SHORT enters from entry downward.
    # The old symmetric ATR gate could mark a signal READY while price was on
    # the wrong side of the calibrated entry.
    # Match the calibrated entry buffer (0.25 ATR) with a small execution cushion.
    zone_atr = 0.30
    if direction == "LONG":
        zone_low = calibrated_entry
        zone_high = calibrated_entry + micro_atr * zone_atr
        execution_ready = zone_low <= current_price <= zone_high
    elif direction == "SHORT":
        zone_low = calibrated_entry - micro_atr * zone_atr
        zone_high = calibrated_entry
        execution_ready = zone_low <= current_price <= zone_high
    else:
        # Backward-compatible diagnostic mode for direct callers/tests that do
        # not provide a trade direction. Production Alpha always supplies it.
        zone_low = calibrated_entry - micro_atr * 1.25
        zone_high = calibrated_entry + micro_atr * 1.25
        execution_ready = distance_atr <= 1.25
    return {
        "execution_ready": execution_ready,
        "distance_atr": distance_atr,
        "entry_zone_low": zone_low,
        "entry_zone_high": zone_high,
        "reason": (
            "inside directional entry zone" if direction in {"LONG", "SHORT"} and execution_ready
            else "within calibrated execution zone" if direction is None and execution_ready
            else "outside directional entry zone" if direction in {"LONG", "SHORT"}
            else "outside calibrated execution zone"
        ),
    }

def _direction_candidates(rows_15m, rows_5m):
    out = []
    for direction in ("LONG", "SHORT"):
        location = _range_position(rows_15m, direction)
        impulse = _impulse(rows_5m, direction)
        volume = _volume_ratio(rows_5m)
        sweep = _sweep(rows_5m, direction)
        # Broad discovery: location is primary, then require actual participation
        # (volume, impulse, or liquidity sweep). This is deliberately less strict
        # than the reversal lane.
        participation = max(
            sweep,
            min(1.0, volume / 1.5),
            min(1.0, max(0.0, impulse) / 0.006),
        )
        if location >= 0.55 and participation >= 0.45:
            out.append((direction, location, impulse, volume, sweep, participation))
    return out


def _build_plan(rows_15m, rows_5m, allow_watch=False, context=None):
    if len(rows_15m) < 160 or len(rows_5m) < 60:
        return {"status": "DATA-LIMITED", "reason": "insufficient MTF candles"}

    micro_atr = atr(rows_5m, 14)
    price = _close(rows_5m[-1])
    if not micro_atr or price <= 0:
        return {"status": "DATA-LIMITED", "reason": "price/5m ATR unavailable"}

    atr_pct = micro_atr / price * 100.0
    # Exclude dead/choked markets and pathological spikes. This is a regime gate,
    # not a directional score.
    if atr_pct < 0.12 or atr_pct > 4.0:
        return {"status": "WAIT", "reason": "5m volatility regime outside alpha envelope", "atr_pct": atr_pct}

    candidates = _direction_candidates(rows_15m, rows_5m)
    context = context or {}
    if not candidates:
        return {"status": "WAIT", "reason": "no alpha opportunity regime", "atr_pct": atr_pct}

    best = None
    for direction, location, impulse, volume, sweep, participation in candidates:
        calibration = calibrate_entry(
            rows_5m, direction, micro_atr,
            rows_15m=rows_15m,
            context=context,
        )
        if not calibration:
            continue
        entry = calibration["entry"]

        # TIMING GATE — intentionally independent of SL/TP geometry.
        # The 100-candle calibration decides whether price is close enough to
        # the calibrated execution zone. No stop/target calculation is allowed
        # to influence this decision.
        timing = _entry_timing_state(price, entry, micro_atr, direction)
        distance_atr = timing["distance_atr"]
        execution_ready = timing["execution_ready"]
        if not execution_ready and not allow_watch:
            continue

        # GEOMETRY begins only after timing has produced the final entry state.
        # SL/TP cannot tighten, loosen, or otherwise alter entry timing.
        base_geometry = build_entry_geometry(direction, entry)
        stop = base_geometry["stop"]
        risk = entry - stop if direction == "LONG" else stop - entry
        if risk <= 0:
            continue
        risk_pct = risk / price * 100.0
        if risk_pct < 0.10:
            continue

        structural = _opposing_structure_target(rows_15m, direction, entry, risk, 1.0, 20.0)
        flow_features = {
            "liquidity_sweep_score": sweep,
            "volume_score": min(1.0, max(0.0, volume / 1.5)),
        }
        tp_calibration = calibrate_tp(
            rows_15m, rows_5m, direction, entry, stop, context={**context, **flow_features}
        )
        if tp_calibration is None:
            continue
        margin_plan = build_entry_geometry(
            direction,
            entry,
            structural_target=structural,
            target_price=tp_calibration["target"],
        )
        target = margin_plan["target"]
        reward = tp_calibration["reward_r"]
        flow_conviction = tp_calibration["flow_conviction"]
        structural_margin_pct = margin_plan.get("structural_target_margin_pct")
        geometry_reason = f"tp:{tp_calibration['target_source']}:{reward:.2f}R"
        if margin_plan["stop_margin_pct"] > MAX_MARGIN_LOSS_PCT:
            continue

        score = 45.0 + 20.0 * location + 15.0 * participation
        if sweep:
            score += 10.0
        if volume >= 1.5:
            score += 5.0
        if impulse >= 0.003:
            score += 5.0
        score = min(100.0, score)

        candidate = {
            "status": (
                ("ALPHA LONG" if direction == "LONG" else "ALPHA SHORT")
                if execution_ready
                else ("ALPHA WATCH LONG" if direction == "LONG" else "ALPHA WATCH SHORT")
            ),
            "direction": direction,
            "confidence": round(score, 1),
            "entry": entry,
            "entry_low": entry - micro_atr * 0.15 if direction == "SHORT" else entry,
            "entry_high": entry + micro_atr * 0.15 if direction == "LONG" else entry,
            "stop": stop,
            "target": target,
            "margin_usdt": margin_plan["margin_usdt"],
            "leverage": margin_plan["leverage"],
            "notional_usdt": margin_plan["notional_usdt"],
            "stop_margin_pct": margin_plan["stop_margin_pct"],
            "tp_margin_pct": margin_plan["tp_margin_pct"],
            "max_loss_usdt": margin_plan["max_loss_usdt"],
            "target_pnl_usdt": margin_plan["target_pnl_usdt"],
        "tp1": margin_plan["tp1"], "tp2": margin_plan["tp2"], "tp3": margin_plan["tp3"],
        "tp1_margin_pct": margin_plan["tp1_margin_pct"], "tp2_margin_pct": margin_plan["tp2_margin_pct"], "tp3_margin_pct": margin_plan["tp3_margin_pct"],
        "tp1_pnl_usdt": margin_plan["tp1_pnl_usdt"], "tp2_pnl_usdt": margin_plan["tp2_pnl_usdt"], "tp3_pnl_usdt": margin_plan["tp3_pnl_usdt"],
            "target_price_move_pct": margin_plan["target_price_move_pct"],
            "flow_conviction": flow_conviction,
            "structural_target_margin_pct": structural_margin_pct,
            "tp_target_source": tp_calibration["target_source"],
            "tp_trend_strength": tp_calibration["trend_strength"],
            "tp_desired_reward_r": tp_calibration["desired_reward_r"],
            "risk_pct": risk_pct,
            "reward_r": reward,
            "atr_pct": atr_pct,
            "entry_distance_atr": distance_atr,
            "timing_score": calibration.get("timing_score"),
            "volume_ratio_5m": calibration.get("volume_ratio_5m"),
            "volume_regime": calibration.get("volume_regime", ""),
            "flow_score": calibration.get("flow_score"),
            "sweep_score": calibration.get("sweep_score"),
            "regime_score_15m": calibration.get("regime_score_15m"),
            "calibration_inputs": calibration.get("calibration_inputs", ""),
            "execution_ready": execution_ready,
            "watch_reason": "" if execution_ready else timing["reason"],
            "entry_calibration": calibration.get("anchor_source", "100c"),
            "entry_anchor_100": calibration.get("anchor_100", calibration.get("anchor")),
            "entry_anchor_40": calibration.get("anchor_40", calibration.get("anchor")),
            "entry_anchor_source": calibration.get("anchor_source", "legacy"),
            "entry_buffer": calibration["buffer"],
            "entry_zone_low": timing.get("entry_zone_low"),
            "entry_zone_high": timing.get("entry_zone_high"),
            "location_15m": location,
            "participation": participation,
            "volume_ratio_5m": volume,
            "impulse_5m": impulse,
            "liquidity_sweep_5m": sweep,
            "timeframes": "15m/5m",
            "reason": (
                f"alpha regime: location={location:.2f}, participation={participation:.2f}, "
                f"vol={volume:.2f}x, impulse={impulse:.3%}, ATR={atr_pct:.3f}%; "
                f"geometry={geometry_reason}"
            ),
        }
        if best is None or candidate["confidence"] > best["confidence"]:
            best = candidate

    return best or {"status": "WAIT", "reason": "alpha execution geometry unavailable", "atr_pct": atr_pct}

def build_plan(rows_15m, rows_5m, context=None):
    """Return only execution-ready Alpha opportunities.

    ``context`` carries optional order-flow/whale/liquidation features into the
    timing calibration layer. It never changes canonical SL/TP geometry.
    """
    return _build_plan(rows_15m, rows_5m, allow_watch=False, context=context)


def build_discovery_plan(rows_15m, rows_5m, context=None):
    """Return the best Alpha discovery candidate, including a pending watch.

    WATCH is discovery evidence, not an executable trade. The calibrated
    100-candle entry remains unchanged; the scanner simply records that price
    has not reached the execution zone yet.
    """
    return _build_plan(rows_15m, rows_5m, allow_watch=True, context=context)