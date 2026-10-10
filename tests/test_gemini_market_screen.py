import json
import unittest
import io
import contextlib
import urllib.error
from gemini_market_screen import DEFAULT_MODEL, _extract_json, normalize_picks, screen_market_packets, should_use_qwen_fallback


class GeminiMarketScreenTests(unittest.TestCase):
    def setUp(self):
        self.packets = [
            {"symbol": "PEPEUSDT", "price": 0.00001, "range_pos": 0.1},
            {"symbol": "SHIBUSDT", "price": 0.00002, "range_pos": 0.9},
        ]

    def test_default_model_is_available_gemini_flash_lite(self):
        self.assertEqual(DEFAULT_MODEL, "gemini-3.5-flash-lite")

    def test_extracts_json_array_from_model_text(self):
        self.assertEqual(_extract_json('[{"symbol":"PEPEUSDT"}]')[0]["symbol"], "PEPEUSDT")

    def test_rejects_unknown_symbols_and_invalid_directions(self):
        picks = normalize_picks([
            {"symbol": "NOTREALUSDT", "direction": "LONG", "score": 90},
            {"symbol": "PEPEUSDT", "direction": "HOLD", "score": 90},
            {"symbol": "SHIBUSDT", "direction": "SHORT", "score": 80},
        ], self.packets)
        self.assertEqual(list(picks), ["SHIBUSDT"])

    def test_rejects_candidates_not_ready_for_directional_entry(self):
        packets = [
            {"symbol": "PEPEUSDT", "long_entry_ready": False, "short_entry_ready": True},
            {"symbol": "SHIBUSDT", "long_entry_ready": True, "short_entry_ready": False},
        ]
        picks = normalize_picks([
            {"symbol": "PEPEUSDT", "direction": "LONG", "score": 95},
            {"symbol": "SHIBUSDT", "direction": "LONG", "score": 80},
            {"symbol": "SHIBUSDT", "direction": "SHORT", "score": 90},
        ], packets)
        self.assertEqual(list(picks), ["SHIBUSDT"])
        self.assertEqual(picks["SHIBUSDT"]["direction"], "LONG")

    def test_clamps_score_and_limits_to_six(self):
        packets = [{"symbol": f"T{i}USDT"} for i in range(10)]
        raw = [{"symbol": p["symbol"], "direction": "LONG", "score": 140} for p in packets]
        picks = normalize_picks(raw, packets)
        self.assertEqual(len(picks), 6)
        self.assertEqual(picks["T0USDT"]["score"], 100)

    def test_gemini_only_mode_skips_heavy_qwen_fallback(self):
        self.assertFalse(should_use_qwen_fallback({}, gemini_only=True))
        self.assertTrue(should_use_qwen_fallback({}, gemini_only=False))
        self.assertFalse(should_use_qwen_fallback({"PEPEUSDT": {"direction": "LONG"}}, gemini_only=False))

    def test_missing_key_does_not_call_api(self):
        self.assertEqual(screen_market_packets(self.packets, api_key="  "), {})

    def test_api_response_is_validated(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                body = {"candidates": [{"content": {"parts": [{"text":
                    json.dumps([{"symbol":"PEPEUSDT","direction":"LONG","score":77,"reason":"near range low"},
                                {"symbol":"FAKEUSDT","direction":"SHORT","score":99}] )
                }]}}]}
                return json.dumps(body).encode()
        def fake_open(request, timeout):
            self.assertIn("key", request.headers.get("X-goog-api-key", ""))
            self.assertEqual(timeout, 20)
            return Response()
        picks = screen_market_packets(self.packets, api_key=" key ", opener=fake_open)
        self.assertEqual(list(picks), ["PEPEUSDT"])
        self.assertEqual(picks["PEPEUSDT"]["score"], 77)

    def test_http_error_logs_status_without_failing_scan(self):
        error = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com", 429, "quota", {}, io.BytesIO(b'{"error":{"message":"quota exceeded"}}')
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            picks = screen_market_packets(self.packets, api_key="key", opener=lambda *a, **k: (_ for _ in ()).throw(error))
        self.assertEqual(picks, {})
        self.assertIn("status=429", output.getvalue())
        self.assertIn("quota exceeded", output.getvalue())

    def test_malformed_response_fails_open(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"candidates":[{"content":{"parts":[{"text":"not json"}]}}]}'
        self.assertEqual(screen_market_packets(self.packets, api_key="key", opener=lambda *a, **k: Response()), {})


if __name__ == "__main__":
    unittest.main()
