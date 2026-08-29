"""
Safety & Guardrails Engine.
Protects against destructive actions, loops, and PII leakage.
"""

import re
from typing import List, Optional
from collections import deque
from phone_harness.core.models import UIElement
from phone_harness.core.exceptions import DestructiveActionGatedError, StateLoopDetectedError, StepBudgetExceededError


class SafetyGuard:
    """Enforces safety guardrails across agent action requests."""

    DESTRUCTIVE_REGEX = re.compile(
        r"(?i)(delete|uninstall|remove\s+account|sign\s*out|log\s*out|"
        r"disable\s+(account|device|security|protection|app)|"
        r"clear\s+data|format|factory\s+reset|reset\s+(device|phone|account)|wipe|erase|"
        r"purchase|buy\s+now|pay\s+\$|send\s+money|transfer\s+funds)"
    )
    _COORDINATE_ACTIONS = {"tap", "double_tap", "long_press"}

    PII_KEYWORDS = re.compile(
        r"(?i)(password|pin|cvv|secret|token|passcode|private\s+key)"
    )

    def __init__(self, max_history_size: int = 10, loop_threshold: int = 3):
        self.state_hash_history: deque[str] = deque(maxlen=max_history_size)
        self.action_signature_history: deque[str] = deque(maxlen=max_history_size)
        self.loop_threshold = loop_threshold

    def check_destructive_action(
        self,
        target_element: Optional[UIElement],
        action_name: str,
        confirm_destructive: bool,
    ) -> None:
        """
        Gates actions that might cause irreversible data loss or financial transactions.
        """
        if target_element is None:
            if action_name in self._COORDINATE_ACTIONS and not confirm_destructive:
                raise DestructiveActionGatedError(element_label="unlabeled coordinate target")
            return

        label_to_check = f"{target_element.text or ''} {target_element.description or ''} {target_element.resource_id or ''}"
        if self.DESTRUCTIVE_REGEX.search(label_to_check):
            if not confirm_destructive:
                raise DestructiveActionGatedError(element_label=label_to_check.strip())

    def record_and_check_state_loop(self, state_hash: str) -> None:
        """
        Detects if the agent is trapped in an infinite cycle of identical UI states.
        Retained for explicit state-history callers; observe() no longer feeds it.
        """
        if not state_hash:
            return

        self.state_hash_history.append(state_hash)
        # Count frequency of the latest state in the sliding window
        occurrences = self.state_hash_history.count(state_hash)
        if occurrences >= self.loop_threshold:
            raise StateLoopDetectedError(loop_count=occurrences)

    def record_and_check_action_loop(self, action_signature: str, state_hash: str) -> None:
        """
        Detects action-only loops: identical post-action (action_signature, state_hash)
        pairs repeated without progress. Observations never affect this history; only
        completed actions/verifications feed it.

        The loop key is the action-state PAIR, not the action alone: three identical
        actions that each reach a different post-state are NOT a loop (they made
        progress), but three identical actions landing on the SAME state are.
        """
        if not action_signature:
            return

        loop_key = f"{action_signature}|{state_hash}"
        self.action_signature_history.append(loop_key)
        occurrences = self.action_signature_history.count(loop_key)
        if occurrences >= self.loop_threshold:
            raise StateLoopDetectedError(loop_count=occurrences)

    def sanitize_element(self, elem: UIElement) -> UIElement:
        """Masks sensitive values (passwords, PINs) from telemetry and compact trees."""
        if elem.is_password or (elem.resource_id and self.PII_KEYWORDS.search(elem.resource_id)):
            elem.is_password = True
            if elem.value:
                elem.value = "••••••••"
            if elem.text:
                elem.text = "••••••••"
        return elem


class StepBudgetGuard:
    """Monitors step execution, enforces hard step budgets, and calculates task efficiency."""

    def __init__(self, max_step_budget: int = 15):
        self.max_step_budget = max_step_budget
        self.step_count = 0
        self.step_latencies: List[float] = []

    def record_step(self, latency_ms: float = 0.0) -> None:
        self.step_count += 1
        self.step_latencies.append(latency_ms)

    def check_budget(self) -> None:
        """
        Pre-actuation budget gate. Raises before any grounding/backend call so a
        blocked action never mutates device state or increments the step count.
        """
        if self.step_count >= self.max_step_budget:
            raise StepBudgetExceededError(current_steps=self.step_count, max_budget=self.max_step_budget)

    def get_remaining_budget(self) -> int:
        return max(0, self.max_step_budget - self.step_count)

    def get_efficiency_report(self, optimal_steps: int = 5) -> dict:
        total_time = sum(self.step_latencies)
        avg_time = (total_time / len(self.step_latencies)) if self.step_latencies else 0.0
        score = min(100.0, round((optimal_steps / max(1, self.step_count)) * 100.0, 1))
        return {
            "steps_executed": self.step_count,
            "max_budget": self.max_step_budget,
            "budget_remaining": self.get_remaining_budget(),
            "avg_step_latency_ms": round(avg_time, 2),
            "total_execution_ms": round(total_time, 2),
            "efficiency_score": f"{score}%",
        }

    def reset(self) -> None:
        self.step_count = 0
        self.step_latencies.clear()
