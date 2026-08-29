"""
Finding #2 regression: StaleObservationError.to_dict must expose
expected_generation and current_generation while retaining the base contract
(error / message / suggestions).
"""

from phone_harness.core.exceptions import StaleObservationError


def test_stale_observation_error_dict_includes_generations():
    err = StaleObservationError(expected_generation=7, current_generation=3)
    d = err.to_dict()

    # Stable contract fields retained.
    assert d["error"] == "StaleObservationError"
    assert isinstance(d["message"], str) and d["message"]
    assert isinstance(d["suggestions"], list) and d["suggestions"]

    # Generation numbers exposed for structured callers.
    assert d["expected_generation"] == 7
    assert d["current_generation"] == 3

    # Nothing else leaks into the contract.
    assert set(d.keys()) == {
        "error",
        "expected_generation",
        "current_generation",
        "message",
        "suggestions",
    }


def test_stale_observation_error_round_trip_distinct_values():
    err = StaleObservationError(expected_generation=0, current_generation=42)
    d = err.to_dict()
    assert d["expected_generation"] == 0
    assert d["current_generation"] == 42
