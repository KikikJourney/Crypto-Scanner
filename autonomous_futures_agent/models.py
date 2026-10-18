"""Typed domain models for exchange-independent futures planning."""
from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class TradingConfig:
    # The user's stated allocation is margin per position, not notional value.
    margin_usdt: float = 5.0
    leverage: int = 20
    margin_mode: str = "isolated"
    stop_loss_margin_pct: float = 10.0
    take_profit_margin_pcts: tuple[float, ...] = (30.0, 60.0, 120.0)
    exchange_id: str = ""
    live_enabled: bool = False

    def __post_init__(self) -> None:
        if self.margin_usdt <= 0:
            raise ValueError("margin_usdt must be positive")
        if self.leverage < 1:
            raise ValueError("leverage must be at least 1")
        if self.margin_mode.lower() != "isolated":
            raise ValueError("Only isolated margin is supported by this initial foundation")
        if not 0 < self.stop_loss_margin_pct < 100:
            raise ValueError("stop_loss_margin_pct must be between 0 and 100")
        if not self.take_profit_margin_pcts or any(p <= 0 for p in self.take_profit_margin_pcts):
            raise ValueError("Take-profit percentages must all be positive")


@dataclass(frozen=True)
class TradePlan:
    side: Side
    entry_price: float
    notional_usdt: float
    quantity: float
    stop_loss_price: float
    take_profit_prices: tuple[float, ...]
