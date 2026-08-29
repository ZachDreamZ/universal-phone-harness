"""
Phone Harness - High-Speed, Zero-Mistake Mobile Agent Harness.
"""

from phone_harness.harness import PhoneHarness
from phone_harness.core.models import (
    UIElement,
    PhoneState,
    ActionRequest,
    ActionResult,
    ActionType,
    KeyCode,
    SwipeDirection,
    VerificationSpec,
)
from phone_harness.core.exceptions import (
    PhoneHarnessError,
    ElementNotFoundError,
    AmbiguousTargetError,
    AssertionFailedError,
    DestructiveActionGatedError,
    StateLoopDetectedError,
    ActionTimeoutError,
    StepBudgetExceededError,
    DeviceDisconnectedError,
)

__version__ = "1.0.0"
__all__ = [
    "PhoneHarness",
    "UIElement",
    "PhoneState",
    "ActionRequest",
    "ActionResult",
    "ActionType",
    "KeyCode",
    "SwipeDirection",
    "VerificationSpec",
    "PhoneHarnessError",
    "ElementNotFoundError",
    "AmbiguousTargetError",
    "AssertionFailedError",
    "DestructiveActionGatedError",
    "StateLoopDetectedError",
    "ActionTimeoutError",
    "StepBudgetExceededError",
    "DeviceDisconnectedError",
]
