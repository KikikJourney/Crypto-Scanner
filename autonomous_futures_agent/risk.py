"""Pure, exchange-independent risk geometry. No orders are sent from this module."""
from .models import Side, TradePlan, TradingConfig


def build_trade_plan(side: Side, entry_price: float, config: TradingConfig) -> TradePlan:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")

    notional = config.margin_usdt * config.leverage
    quantity = notional / entry_price
    # PnL as a percentage of allocated margin ~= price movement * leverage.
    stop_move = (config.stop_loss_margin_pct / 100.0) / config.leverage
    target_moves = tuple((pct / 100.0) / config.leverage for pct in config.take_profit_margin_pcts)

    if side is Side.LONG:
        stop = entry_price * (1.0 - stop_move)
        targets = tuple(entry_price * (1.0 + move) for move in target_moves)
    elif side is Side.SHORT:
        stop = entry_price * (1.0 + stop_move)
        targets = tuple(entry_price * (1.0 - move) for move in target_moves)
    else:
        raise ValueError(f"Unsupported side: {side!r}")

    if stop <= 0 or any(price <= 0 for price in targets):
        raise ValueError("Calculated order prices must be positive")

    return TradePlan(
        side=side,
        entry_price=entry_price,
        notional_usdt=notional,
        quantity=quantity,
        stop_loss_price=stop,
        take_profit_prices=targets,
    )
