import unittest
from evidence_audit import build_report


def row(ts, symbol="AAAUSDT", direction="LONG", confidence="85", outcome="FAIL", r="-1.0"):
    return {
        "timestamp": ts, "symbol": symbol, "provider": "Bitget",
        "direction": direction, "confidence": confidence,
        "strategy_version": "scalp-structure-v1",
        "first_touch": outcome, "outcome_r": r,
        "h15": outcome, "h30": outcome, "h60": outcome, "h120": outcome,
        "mfe_pct": "0.5", "mae_pct": "1.0",
        "location_15m": "1.0", "reversal_5m": "0.5",
    }


class EvidenceAuditTests(unittest.TestCase):
    def test_stratification_and_concentration(self):
        rows = [
            row("2026-09-20T10:00:00+00:00", "AAAUSDT", "LONG", "82"),
            row("2026-09-20T10:05:00+00:00", "AAAUSDT", "SHORT", "87"),
            row("2026-09-20T11:00:00+00:00", "BBBUSDT", "SHORT", "92", "EXPANSION", "2.0"),
        ]
        result = build_report(rows)
        self.assertEqual(result["sample_total"], 3)
        self.assertEqual(result["unique_symbols"], 2)
        self.assertAlmostEqual(result["top_symbol_share"], 2/3, places=5)
        self.assertEqual(result["friction_status"], "NOT_OBSERVED")
        self.assertEqual(result["mfe_observed"], 3)
        self.assertEqual(result["direction"][0][0], "LONG")
        self.assertEqual(result["direction"][1][0], "SHORT")

    def test_legacy_rows_are_excluded(self):
        rows = [row("2026-09-20T10:00:00+00:00")]
        rows[0]["strategy_version"] = "legacy"
        self.assertEqual(build_report(rows)["sample_total"], 0)


if __name__ == "__main__":
    unittest.main()
