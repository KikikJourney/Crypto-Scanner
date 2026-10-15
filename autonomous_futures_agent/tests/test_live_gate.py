import unittest

from autonomous_futures_agent.exchange import ExchangeNotConfigured, UnconfiguredExchange
from autonomous_futures_agent.models import TradingConfig
from autonomous_futures_agent.worker import LIVE_ACK_VALUE, assert_live_ready


class FakeExchange:
    exchange_id = "example-venue"
    configured = True

    def get_positions(self):
        return []

    def place_entry(self, order):
        raise AssertionError("The readiness gate must not place orders")

    def place_protective_orders(self, position, protection):
        raise AssertionError("The readiness gate must not place orders")


class LiveGateTests(unittest.TestCase):
    def test_unconfigured_exchange_fails_closed(self):
        with self.assertRaises(ExchangeNotConfigured):
            UnconfiguredExchange().get_positions()

    def test_missing_exchange_id_blocks_live(self):
        with self.assertRaises(ExchangeNotConfigured):
            assert_live_ready(TradingConfig(live_enabled=True), FakeExchange(), LIVE_ACK_VALUE)

    def test_live_disabled_by_default(self):
        config = TradingConfig(exchange_id="example-venue")
        with self.assertRaises(ExchangeNotConfigured):
            assert_live_ready(config, FakeExchange(), LIVE_ACK_VALUE)

    def test_acknowledgement_required(self):
        config = TradingConfig(exchange_id="example-venue", live_enabled=True)
        with self.assertRaises(ExchangeNotConfigured):
            assert_live_ready(config, FakeExchange(), None)

    def test_exchange_identity_must_match(self):
        config = TradingConfig(exchange_id="different-venue", live_enabled=True)
        with self.assertRaises(ExchangeNotConfigured):
            assert_live_ready(config, FakeExchange(), LIVE_ACK_VALUE)

    def test_readiness_gate_passes_only_when_prerequisites_match(self):
        config = TradingConfig(exchange_id="example-venue", live_enabled=True)
        assert_live_ready(config, FakeExchange(), LIVE_ACK_VALUE)


if __name__ == "__main__":
    unittest.main()
