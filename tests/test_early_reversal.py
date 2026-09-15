"""Regression tests for the Early Reversal layer.

These tests define the intended contract before production scoring is changed:
- early reversal must not require expansion confirmation;
- location, exhaustion and flow are the primary early evidence;
- weak/no structural response must remain a monitor, not an entry;
- confirmed PRE-EXPANSION behavior remains separate from EARLY REVERSAL.
"""

from scanner_v2 import clamp


def early_reversal_score(parts):
    """Reference score for calibration only; production integration comes later."""
    weights = {"location": 30, "exhaustion": 25, "flow": 25, "structure": 20}
    return round(sum(weights[k] * clamp(parts[k]) for k in weights), 1)


def classify_early(parts):
    score = early_reversal_score(parts)
    # Early signal deliberately does not require expansion.
    if score >= 65 and parts["location"] >= 0.65 and parts["exhaustion"] >= 0.50 and parts["flow"] >= 0.55:
        return "EARLY REVERSAL LONG"
    return "MONITOR"


def test_early_reversal_does_not_require_expansion():
    parts = {"location": .90, "exhaustion": .70, "flow": .62, "structure": .20}
    assert classify_early(parts) == "EARLY REVERSAL LONG"


def test_mid_range_is_not_early_reversal():
    parts = {"location": .40, "exhaustion": .80, "flow": .70, "structure": .60}
    assert classify_early(parts) == "MONITOR"


def test_weak_flow_is_not_early_reversal():
    parts = {"location": .90, "exhaustion": .70, "flow": .48, "structure": .30}
    assert classify_early(parts) == "MONITOR"


def test_weak_exhaustion_is_not_early_reversal():
    parts = {"location": .90, "exhaustion": .35, "flow": .65, "structure": .30}
    assert classify_early(parts) == "MONITOR"
