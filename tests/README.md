# Tests

The Early Reversal test suite is intentionally created before production integration.

Run locally with:

```bash
python -m py_compile scanner_v2.py tests/test_early_reversal.py
python tests/test_early_reversal.py
```

The production scanner should only be changed after these behavioral contracts are reviewed and the integration tests are expanded to cover LONG and SHORT, real candle features, provider normalization, and future-only forward testing.
