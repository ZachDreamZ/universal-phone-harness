"""
Tests for Zero-Mistake Verifier & Safety Guard.
"""

import pytest
from phone_harness.core.models import UIElement, PhoneState, VerificationSpec, ActionRequest, ActionType
from phone_harness.core.exceptions import AssertionFailedError, DestructiveActionGatedError, StateLoopDetectedError
from phone_harness.engine.verifier import ZeroMistakeVerifier
from phone_harness.engine.safety import SafetyGuard


def test_zero_mistake_post_assertion_success():
    spec = VerificationSpec(assert_text_present=["Connected", "Wi-Fi"])
    state = PhoneState(
        device_id="test",
        platform="mock",
        screen_width=1080,
        screen_height=2400,
        current_app_package="com.android.settings",
        compact_dom='[1] CheckBox "Wi-Fi Connected" {100, 100, 500, 200}',
    )
    passed, reason = ZeroMistakeVerifier.evaluate_post_assertions(spec, state)
    assert passed is True
    assert reason is None


def test_zero_mistake_post_assertion_failure():
    spec = VerificationSpec(assert_text_present=["Success Order Placed"])
    state = PhoneState(
        device_id="test",
        platform="mock",
        screen_width=1080,
        screen_height=2400,
        current_app_package="com.store",
        compact_dom='[1] Button "Pay Now" {100, 100, 500, 200}',
    )
    passed, reason = ZeroMistakeVerifier.evaluate_post_assertions(spec, state)
    assert passed is False
    assert "Expected text 'Success Order Placed' was NOT found" in reason


def test_safety_guard_destructive_gate():
    guard = SafetyGuard()
    elem = UIElement.create(1, "Button", (100, 100, 500, 200), text="Factory Reset Phone")

    # Should raise when confirm_destructive is False
    with pytest.raises(DestructiveActionGatedError):
        guard.check_destructive_action(elem, "tap", confirm_destructive=False)

    # Should succeed when confirm_destructive is True
    guard.check_destructive_action(elem, "tap", confirm_destructive=True)


@pytest.mark.parametrize(
    "label",
    ["Uninstall app", "Sign out", "Log out", "Disable account", "Clear data", "Reset device"],
)
def test_safety_guard_blocks_additional_destructive_labels(label):
    guard = SafetyGuard()
    element = UIElement.create(1, "Button", (100, 100, 500, 200), text=label)

    with pytest.raises(DestructiveActionGatedError):
        guard.check_destructive_action(element, "tap", confirm_destructive=False)


def test_safety_guard_blocks_unlabeled_coordinate_tap_without_confirmation():
    guard = SafetyGuard()

    with pytest.raises(DestructiveActionGatedError):
        guard.check_destructive_action(None, "tap", confirm_destructive=False)

    guard.check_destructive_action(None, "tap", confirm_destructive=True)


def test_safety_guard_loop_detection():
    guard = SafetyGuard(loop_threshold=3)
    guard.record_and_check_state_loop("hash_A")
    guard.record_and_check_state_loop("hash_B")
    guard.record_and_check_state_loop("hash_A")
    with pytest.raises(StateLoopDetectedError):
        guard.record_and_check_state_loop("hash_A")


def test_safety_guard_action_loop_detection():
    """Repeating the same post-action action-state signature trips the loop guard."""
    guard = SafetyGuard(loop_threshold=3)
    guard.record_and_check_action_loop("tap:3:com.example", "hash_A")
    guard.record_and_check_action_loop("tap:3:com.example", "hash_A")
    with pytest.raises(StateLoopDetectedError):
        guard.record_and_check_action_loop("tap:3:com.example", "hash_A")


def test_safety_guard_action_different_signatures_no_loop():
    """Different action signatures on the same observed state must not trigger a loop."""
    guard = SafetyGuard(loop_threshold=3)
    guard.record_and_check_action_loop("tap:3:com.example", "hash_A")
    guard.record_and_check_action_loop("tap:4:com.example", "hash_A")
    guard.record_and_check_action_loop("tap:5:com.example", "hash_A")
    # No exception expected.


def test_action_loop_distinct_state_hashes_no_loop():
    """Same action signature reaching different post-states must not trip the guard."""
    guard = SafetyGuard(loop_threshold=3)
    guard.record_and_check_action_loop("tap:3:com.example", "state_A")
    guard.record_and_check_action_loop("tap:3:com.example", "state_B")
    guard.record_and_check_action_loop("tap:3:com.example", "state_C")
    # No exception expected: each action landed on a distinct post-state.


def test_action_loop_same_signature_and_state_raises():
    """Same action signature AND same post-state reaches threshold and raises."""
    guard = SafetyGuard(loop_threshold=3)
    guard.record_and_check_action_loop("tap:3:com.example", "state_A")
    guard.record_and_check_action_loop("tap:3:com.example", "state_A")
    with pytest.raises(StateLoopDetectedError):
        guard.record_and_check_action_loop("tap:3:com.example", "state_A")
