import unittest

from traderspy_blueprint import (
    adx,
    blueprint_label,
    diagnose,
    ema,
    macd_histogram,
    rsi,
)


def make_rows(n=120):
    rows = []
    price = 100.0
    for i in range(n):
        # Deterministic rising tape with periodic larger candles/volume.
        step = 0.30 if i < n - 20 else 0.55
        open_price = price
        close = price + step
        high = close + 0.25
        low = open_price - 0.10
        volume = 1000.0 * (3.0 if i == n - 1 else 1.0)
        rows.append([i, open_price, high, low, close, volume])
        price = close
    return rows


class TraderSpyBlueprintTests(unittest.TestCase):
    def test_basic_indicators_have_values(self):
        rows = make_rows()
        closes = [row[4] for row in rows]
        self.assertIsNotNone(ema(closes, 20))
        self.assertIsNotNone(rsi(closes, 14))
        self.assertIsNotNone(macd_histogram(closes))
        self.assertIsNotNone(adx(rows, 14)[0])

    def test_diagnostic_is_non_blocking_and_structured(self):
        rows = make_rows()
        result = diagnose(rows, "LONG", {"funding": 0.001, "taker": 1.1, "book": 1.05})
        for key in (
            "context_score",
            "atr_pct",
            "adx",
            "volume_ratio",
            "rsi",
            "range_position",
            "reasons",
            "open_interest",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["open_interest"], None)
        self.assertGreaterEqual(result["context_score"], 0.0)
        self.assertLessEqual(result["context_score"], 100.0)

    def test_market_label(self):
        self.assertEqual(
            blueprint_label({
                "volatility_active": True,
                "volume_expanded": True,
                "trend_active": True,
            }),
            "ACTIVE",
        )
        self.assertEqual(
            blueprint_label({
                "volatility_active": False,
                "volume_expanded": False,
                "trend_active": False,
            }),
            "QUIET",
        )


if __name__ == "__main__":
    unittest.main()
