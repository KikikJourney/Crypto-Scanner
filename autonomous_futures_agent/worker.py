"""Fail-closed runtime gates; this foundation intentionally does not submit live orders."""
from .exchange import ExchangeAdapter, ExchangeNotConfigured
from .models import TradingConfig

LIVE_ACK_VALUE = "I_UNDERSTAND_REAL_MONEY"


def assert_live_ready(
    config: TradingConfig,
    exchange: ExchangeAdapter,
    live_ack: str | None,
) -> None:
    """Raise unless explicit readiness prerequisites are met; this is not a profitability check."""
    if not config.exchange_id.strip():
        raise ExchangeNotConfigured("EXCHANGE_ID is missing; live trading remains blocked.")
    if not exchange.configured:
        raise ExchangeNotConfigured("Exchange adapter is not configured and verified.")
    if exchange.exchange_id.lower() != config.exchange_id.lower():
        raise ExchangeNotConfigured("Configured exchange does not match the adapter identity.")
    if not config.live_enabled:
        raise ExchangeNotConfigured("LIVE_TRADING_ENABLED is false; live trading remains blocked.")
    if live_ack != LIVE_ACK_VALUE:
        raise ExchangeNotConfigured("Explicit live-trading acknowledgement is missing.")
    # Deliberately no order-submission loop is provided until the venue is specified and tested.
