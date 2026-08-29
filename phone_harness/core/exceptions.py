"""
Domain exceptions for Phone Harness.
Provides structured, actionable error messages for LLM agents to recover from.
"""

from typing import Optional, List


class PhoneHarnessError(Exception):
    """Base exception for all Phone Harness errors."""
    def __init__(self, message: str, suggestions: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.suggestions = suggestions or []

    def to_dict(self):
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "suggestions": self.suggestions,
        }


class DeviceDisconnectedError(PhoneHarnessError):
    """Raised when the target phone device is unreachable or disconnected."""
    def __init__(self, device_id: str, message: Optional[str] = None):
        msg = message or f"Phone device '{device_id}' is disconnected or unauthorized via ADB/WDA."
        suggestions = [
            "Check USB cable connection or Wi-Fi ADB pairing.",
            "Run 'adb devices' or verify WebDriverAgent is active.",
            "Call 'phone_device_list' to discover available devices.",
        ]
        super().__init__(msg, suggestions)


class ElementNotFoundError(PhoneHarnessError):
    """Raised when an element specified by index or text cannot be located."""
    def __init__(self, target: str, available_elements_summary: Optional[str] = None):
        msg = f"Target element '{target}' could not be located on the current screen."
        if available_elements_summary:
            msg += f"\nCurrent interactive elements:\n{available_elements_summary}"
        suggestions = [
            "Call 'phone_observe' to get the latest indexed DOM.",
            "The screen may have scrolled or transitioned; check if the view refreshed.",
            "Use fuzzy text matching or directional swipe if the element is off-screen.",
        ]
        super().__init__(msg, suggestions)


class AmbiguousTargetError(PhoneHarnessError):
    """Raised when multiple matching elements exist without a clear discriminator."""
    def __init__(self, query: str, match_count: int, matched_indexes: List[int]):
        msg = f"Query '{query}' matches {match_count} distinct elements with IDs {matched_indexes}."
        suggestions = [
            f"Specify an exact index (e.g. index={matched_indexes[0]}) instead of ambiguous text.",
            "Call 'phone_observe' to view the specific bounding boxes.",
        ]
        super().__init__(msg, suggestions)


class AssertionFailedError(PhoneHarnessError):
    """Raised when a post-action verification assertion fails."""
    def __init__(self, assertion_type: str, expected: str, actual: str):
        msg = f"Zero-Mistake Assertion Failed ({assertion_type}): Expected '{expected}', but actual screen state was '{actual}'."
        suggestions = [
            "The target action might have had no effect, or opened an unexpected screen/dialog.",
            "Call 'phone_observe' to inspect the unexpected screen state.",
            "Check if an animation or network loading delay requires a retry or longer settle time.",
        ]
        super().__init__(msg, suggestions)


class DestructiveActionGatedError(PhoneHarnessError):
    """Raised when an agent attempts a sensitive/destructive action without confirmation."""
    def __init__(self, element_label: str):
        msg = f"Safety Gate Intercepted: Action targets potentially destructive element '{element_label}'."
        suggestions = [
            "Set 'confirm_destructive=True' in your action request if this action is explicitly intended.",
            "Verify the user intended to perform a deletion, reset, or financial transaction.",
        ]
        super().__init__(msg, suggestions)


class StateLoopDetectedError(PhoneHarnessError):
    """Raised when the agent gets trapped in a cyclical loop of identical UI states."""
    def __init__(self, loop_count: int):
        msg = f"State Loop Detected: The agent has cycled through identical UI states {loop_count} times without progress."
        suggestions = [
            "The previous actions did not change the screen or repeated a back-and-forth cycle.",
            "Inspect the screen hierarchy to try an alternative navigation route.",
            "Press BACK key or return to HOME to reset flow.",
        ]
        super().__init__(msg, suggestions)


class StaleObservationError(PhoneHarnessError):
    """Raised when an indexed action references an observation generation that no longer matches live state."""

    def __init__(self, expected_generation: int, current_generation: int):
        self.expected_generation = expected_generation
        self.current_generation = current_generation
        msg = (
            f"Stale Observation: Action was grounded on observation generation "
            f"{expected_generation}, but the live state is now generation {current_generation}. "
            f"Re-observe and resubmit the action."
        )
        suggestions = [
            "Call 'phone_observe' to capture the current screen generation.",
            "Resubmit the action with observation_generation set to the latest state.generation.",
            "For a fresh grounding pass, omit observation_generation (Python compatibility path).",
        ]
        super().__init__(msg, suggestions)

    def to_dict(self):
        # Retain the base contract (error / message / suggestions) and add the
        # two generation numbers so structured callers (e.g. the MCP server) can
        # surface and act on them without parsing the message string.
        return {
            "error": self.__class__.__name__,
            "expected_generation": self.expected_generation,
            "current_generation": self.current_generation,
            "message": self.message,
            "suggestions": self.suggestions,
        }


class ActionTimeoutError(PhoneHarnessError):
    """Raised when an action or settling detection exceeds timeout."""
    def __init__(self, action_name: str, timeout_ms: int):
        msg = f"Action '{action_name}' timed out after {timeout_ms}ms."
        suggestions = [
            "Check if the device or app has frozen / crashed.",
            "Call 'phone_observe' or 'phone_health_check' to verify responsiveness.",
        ]
        super().__init__(msg, suggestions)


class StepBudgetExceededError(PhoneHarnessError):
    """Raised when an agent exceeds the maximum allowed action step budget for a task."""
    def __init__(self, current_steps: int, max_budget: int):
        msg = f"Step Budget Exceeded: Agent executed {current_steps} steps, exceeding the hard budget of {max_budget} steps."
        suggestions = [
            "Review your trajectory to see if the agent is stuck in repetitive actions or unnecessary intermediate steps.",
            "Increase max_step_budget in HarnessConfig if this task legitimately requires more steps.",
            "Use direct intent navigation (phone_open_url, phone_open_settings) to reduce multi-step navigation overhead.",
        ]
        super().__init__(msg, suggestions)
