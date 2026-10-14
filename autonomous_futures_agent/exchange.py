"""Exchange boundary. A venue-specific adapter must implement this protocol."""
from typing import Protocol, runtime_checkable


class ExchangeNotConfigured(RuntimeError):
    """Raised when a live exchange adapter has not been configured and verified."""


@runtime_checkable
class ExchangeAdapter(Protocol):
    exchange_id: str
    configured: bool

    def get_positions(self) -> list[dict]: ...
    def place_entry(self, order: dict) -> dict: ...
    def place_protective_orders(self, position: dict, protection: dict) -> dict: ...


class UnconfiguredExchange:
    exchange_id = ""
    configured = False

    def _deny(self) -> None:
        raise ExchangeNotConfigured(
            "No exchange was selected. Live trading is disabled until a venue-specific "
            "adapter, credentials, permissions, symbol rules, and protection-order behavior are verified."
        )

    def get_positions(self) -> list[dict]:
        self._deny()

    def place_entry(self, order: dict) -> dict:
        self._deny()

    def place_protective_orders(self, position: dict, protection: dict) -> dict:
        self._deny()
