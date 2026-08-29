"""
Tests for Task 2: observation generations, action-only loop detection, and
pre-actuation budgets. All tests inject MockPhoneDevice; no hardware touched.
"""

import pytest

from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.core.config import HarnessConfig
from phone_harness.core.exceptions import (
    DestructiveActionGatedError,
    StaleObservationError,
    StepBudgetExceededError,
)
from phone_harness.core.models import ActionRequest, ActionType, UIElement, VerificationSpec
from phone_harness.harness import PhoneHarness


class UnlabeledContainerMockDevice(MockPhoneDevice):
    """Returns one full-screen clickable element without identifying text."""

    def dump_hierarchy(self):
        return [
            UIElement.create(
                1,
                "FrameLayout",
                (0, 0, self.screen_width, self.screen_height),
                is_clickable=True,
            )
        ]


class CoordinateShiftMockDevice(MockPhoneDevice):
    """Test device where the first tap shifts the target element's coordinates but the
    verification still fails; a re-grounded second tap on the refreshed hierarchy lands and
    satisfies the assertion."""

    def __init__(self):
        super().__init__()
        self.tapped_coords = []
        self.phase = 0

    def dump_hierarchy(self):
        if self.phase == 0:
            # Initial grounding target.
            return [UIElement.create(1, "Button", (100, 200, 300, 400), text="Target")]
        if self.phase == 1:
            # Same element, but shifted coordinates after the first tap.
            return [UIElement.create(1, "Button", (500, 600, 700, 800), text="Target")]
        # phase 2: the verification text is now present on screen.
        return [
            UIElement.create(1, "Button", (500, 600, 700, 800), text="Target"),
            UIElement.create(2, "TextView", (0, 0, 200, 100), text="Expected"),
        ]

    def tap(self, x: int, y: int) -> None:
        self.tapped_coords.append((x, y))
        if self.phase == 0 and (100 <= x <= 300 and 200 <= y <= 400):
            self.phase = 1
        elif self.phase == 1 and (500 <= x <= 700 and 600 <= y <= 800):
            self.phase = 2



def test_repeated_observation_does_not_count_as_action_loop():
    """Observations must never mutate loop history (action-only loop detection)."""
    harness = PhoneHarness(device=MockPhoneDevice())
    for _ in range(5):
        harness.observe()


def test_indexed_action_rejects_stale_generation():
    """An indexed action pinned to an old generation must raise StaleObservationError."""
    harness = PhoneHarness(device=MockPhoneDevice())
    first_state = harness.observe()
    current_state = harness.observe()
    assert current_state.generation > first_state.generation
    request = ActionRequest(
        action=ActionType.TAP,
        target_index=3,
        observation_generation=first_state.generation,
    )
    with pytest.raises(StaleObservationError):
        harness.execute_action(request)


def test_indexed_action_without_generation_proceeds():
    """Indexed requests lacking a generation keep Python compatibility."""
    harness = PhoneHarness(device=MockPhoneDevice())
    harness.observe()
    request = ActionRequest(action=ActionType.TAP, target_index=3)
    result = harness.execute_action(request)
    assert result.success is True
    assert harness.step_guard.step_count == 1


def test_budget_blocks_backend_before_tap():
    """A zero budget must block the action before any backend mutation."""
    device = MockPhoneDevice()
    harness = PhoneHarness(
        device=device,
        config=HarnessConfig(max_step_budget=0, enable_loop_detection=False),
    )
    initial_screen = device.current_screen
    with pytest.raises(StepBudgetExceededError):
        harness.execute_action(ActionRequest(action=ActionType.TAP, target_text="Settings"))
    assert device.current_screen == initial_screen
    assert harness.step_guard.step_count == 0


def test_unlabeled_coordinate_tap_requires_explicit_confirmation():
    device = UnlabeledContainerMockDevice()
    harness = PhoneHarness(device=device)

    with pytest.raises(DestructiveActionGatedError):
        harness.execute_action(ActionRequest(action=ActionType.TAP, x=10, y=10))

    result = harness.execute_action(
        ActionRequest(
            action=ActionType.TAP,
            x=10,
            y=10,
            confirm_destructive=True,
        )
    )
    assert result.success is True


def test_retry_re_grounds_to_refreshed_coordinates():
    """On verification failure the harness must re-observe, re-ground the target against the
    refreshed hierarchy, and dispatch once with the NEW coordinates."""
    device = CoordinateShiftMockDevice()
    harness = PhoneHarness(device=device)
    harness.observe()  # establish last_state on the phase-0 hierarchy

    request = ActionRequest(
        action=ActionType.TAP,
        target_index=1,
        verify=VerificationSpec(assert_text_present=["Expected"], auto_retry_on_fail=True),
    )
    result = harness.execute_action(request)

    assert result.success is True
    assert len(device.tapped_coords) == 2
    # Initial grounding resolves the phase-0 center; the retry uses the refreshed center.
    assert device.tapped_coords[0] == (200, 300)
    assert device.tapped_coords[1] == (600, 700)
    assert device.tapped_coords[0] != device.tapped_coords[1]


def test_zero_budget_blocks_observe_before_backend_call(monkeypatch):
    """Finding #3: check_budget() must run BEFORE the fresh-state observation, so
    an exhausted budget performs no observe() (no dump_hierarchy / capture) and no
    actuation. We spy on observe() and assert it is never called."""
    device = MockPhoneDevice()
    harness = PhoneHarness(
        device=device,
        config=HarnessConfig(max_step_budget=0, enable_loop_detection=False),
    )

    observe_calls = []
    real_observe = harness.observe

    def spy_observe(**kwargs):
        observe_calls.append(1)
        return real_observe(**kwargs)

    monkeypatch.setattr(harness, "observe", spy_observe)

    with pytest.raises(StepBudgetExceededError):
        harness.execute_action(
            ActionRequest(action=ActionType.TAP, target_text="Settings")
        )

    # No observation/backend call must occur when the budget is exhausted.
    assert observe_calls == [], "observe() was called despite an exhausted budget"
    assert harness.step_guard.step_count == 0
