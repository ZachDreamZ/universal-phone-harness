"""
Tests for Advanced Features: Dialog Handler, Trajectory Recorder, Poller, and Intent tools.
"""

from PIL import Image
from phone_harness.core.models import UIElement, ActionRequest, ActionType, VerificationSpec
from phone_harness.engine.dialog_handler import SystemDialogHandler
from phone_harness.engine.trajectory import TrajectoryRecorder
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.harness import PhoneHarness
from phone_harness.perception.visual_detector import VisualElementDetector


def test_system_dialog_handler():
    elements = [
        UIElement.create(1, "TextView", (100, 200, 900, 300), text="Allow Maps to access this device's location?"),
        UIElement.create(2, "Button", (100, 500, 900, 600), text="While using the app", is_clickable=True),
        UIElement.create(3, "Button", (100, 650, 900, 750), text="Don't allow", is_clickable=True),
    ]

    is_dialog = SystemDialogHandler.is_permission_or_alert_dialog("com.android.permissioncontroller", elements)
    assert is_dialog is True

    allow_btn = SystemDialogHandler.find_action_button("allow", elements)
    assert allow_btn is not None
    assert allow_btn.id == 2

    deny_btn = SystemDialogHandler.find_action_button("deny", elements)
    assert deny_btn is not None
    assert deny_btn.id == 3


def test_trajectory_recorder():
    recorder = TrajectoryRecorder(session_id="test_sess", device_id="mock_dev", platform="mock")
    req = ActionRequest(action=ActionType.TAP, target_index=1)
    dev = MockPhoneDevice()
    harness = PhoneHarness(device=dev)
    res = harness.execute_action(req)

    step = recorder.record_step(req, res, pre_state=None)
    assert step.step_id == 1
    assert step.result["success"] is True

    data = recorder.finalize()
    assert data["session_id"] == "test_sess"
    assert len(data["steps"]) == 1


def test_wait_for_condition_mock():
    dev = MockPhoneDevice()
    harness = PhoneHarness(device=dev)

    # Condition already met on home screen
    passed, state = harness.wait_for_condition(text_present=["Settings"], timeout_ms=500)
    assert passed is True
    assert state.current_app_package == "com.google.android.apps.nexuslauncher"

    # Non-existent condition times out cleanly without throwing unhandled error
    passed_fail, _ = harness.wait_for_condition(text_present=["NonExistentRandomText12345"], timeout_ms=300)
    assert passed_fail is False


def test_open_url_and_clipboard():
    dev = MockPhoneDevice()
    harness = PhoneHarness(device=dev)

    # Test clipboard
    harness.set_clipboard("Test Clipboard 🚀")
    assert harness.get_clipboard() == "Test Clipboard 🚀"

    # Test URL open
    state = harness.open_url("https://example.com")
    assert state.current_app_package == "com.android.chrome"


def test_step_budget_guard():
    import pytest
    from phone_harness.core.exceptions import StepBudgetExceededError
    from phone_harness.core.config import HarnessConfig

    dev = MockPhoneDevice()
    cfg = HarnessConfig(max_step_budget=2, enable_loop_detection=False)
    harness = PhoneHarness(device=dev, config=cfg)

    # Step 1
    harness.execute_action(ActionRequest(action=ActionType.TAP, target_index=1))
    # Step 2
    harness.execute_action(ActionRequest(action=ActionType.TAP, target_index=1))
    assert harness.step_guard.step_count == 2
    assert harness.step_guard.get_remaining_budget() == 0

    # Step 3 exceeds budget of 2
    with pytest.raises(StepBudgetExceededError):
        harness.execute_action(ActionRequest(action=ActionType.TAP, target_index=1))

    report = harness.get_efficiency_report(optimal_steps=2)
    assert report["steps_executed"] == 2
    assert "efficiency_score" in report
