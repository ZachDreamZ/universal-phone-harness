"""
Unified Task Session Runner.
Executes multi-step agent actions within a warm, persistent memory context.
Enforces hard step budgets, measures latency breakdown, and computes task efficiency scores.
"""

import time
from typing import List, Dict, Any, Optional, Callable
from pydantic import BaseModel, Field

from phone_harness.core.models import ActionRequest, ActionResult, PhoneState, ActionType, KeyCode
from phone_harness.core.config import HarnessConfig, DEFAULT_CONFIG
from phone_harness.core.exceptions import StepBudgetExceededError
from phone_harness.harness import PhoneHarness


class TaskSessionResult(BaseModel):
    task_name: str
    success: bool
    total_elapsed_sec: float
    total_steps: int
    optimal_steps: int
    efficiency_score: str
    total_perception_chars: int
    estimated_tokens: int
    step_latencies_ms: List[float] = Field(default_factory=list)
    final_app: str = ""
    error: Optional[str] = None


class TaskSessionRunner:
    """Runs automated multi-step agent routines in a warm process session."""

    def __init__(self, harness: Optional[PhoneHarness] = None, max_step_budget: int = 15):
        cfg = HarnessConfig(max_step_budget=max_step_budget)
        self.harness = harness or PhoneHarness(config=cfg)
        self.max_step_budget = max_step_budget

    def execute_plan(
        self,
        task_name: str,
        step_definitions: List[Dict[str, Any]],
        optimal_steps: int = 5,
    ) -> TaskSessionResult:
        """
        Executes a sequence of steps in a warm memory session with zero OS process restart overhead.
        """
        t_start = time.time()
        self.harness.step_guard.reset()
        latencies: List[float] = []
        total_chars = 0
        last_state: Optional[PhoneState] = None

        try:
            for step in step_definitions:
                t0 = time.time()
                action_name = step.get("action", "observe")

                if action_name == "open_settings":
                    last_state = self.harness.open_settings(step.get("section", "settings"))
                    total_chars += len(last_state.compact_dom)

                elif action_name == "open_app":
                    req = ActionRequest(action=ActionType.OPEN_APP, package_name=step["package_name"])
                    res = self.harness.execute_action(req)
                    last_state = res.new_state
                    if last_state:
                        total_chars += len(last_state.compact_dom)

                elif action_name == "open_url":
                    last_state = self.harness.open_url(step["url"])
                    total_chars += len(last_state.compact_dom)

                elif action_name == "observe":
                    last_state = self.harness.observe()
                    total_chars += len(last_state.compact_dom)

                elif action_name == "tap":
                    # Support index or text query
                    req = ActionRequest(
                        action=ActionType.TAP,
                        target_index=step.get("index"),
                        target_text=step.get("text"),
                    )
                    res = self.harness.execute_action(req)
                    last_state = res.new_state
                    if last_state:
                        total_chars += len(last_state.compact_dom)

                elif action_name == "type":
                    req = ActionRequest(
                        action=ActionType.TYPE,
                        text_to_type=step["text"],
                        target_index=step.get("index"),
                        target_text=step.get("text_query"),
                        press_enter=step.get("enter", False),
                    )
                    res = self.harness.execute_action(req)
                    last_state = res.new_state
                    if last_state:
                        total_chars += len(last_state.compact_dom)

                elif action_name == "press":
                    req = ActionRequest(action=ActionType.PRESS_KEY, key=KeyCode(step["key"]))
                    res = self.harness.execute_action(req)
                    last_state = res.new_state

                elif action_name == "wait":
                    self.harness.wait_for_condition(
                        text_present=step.get("text_present"),
                        app_package=step.get("app_package"),
                        timeout_ms=step.get("timeout_ms", 3000),
                    )

                step_lat = (time.time() - t0) * 1000.0
                latencies.append(round(step_lat, 2))

            total_elapsed = time.time() - t_start
            eff = self.harness.get_efficiency_report(optimal_steps=optimal_steps)

            return TaskSessionResult(
                task_name=task_name,
                success=True,
                total_elapsed_sec=round(total_elapsed, 2),
                total_steps=len(step_definitions),
                optimal_steps=optimal_steps,
                efficiency_score=eff.get("efficiency_score", "100%"),
                total_perception_chars=total_chars,
                estimated_tokens=total_chars // 4,
                step_latencies_ms=latencies,
                final_app=last_state.current_app_package if last_state else "unknown",
            )

        except Exception as e:
            total_elapsed = time.time() - t_start
            return TaskSessionResult(
                task_name=task_name,
                success=False,
                total_elapsed_sec=round(total_elapsed, 2),
                total_steps=len(latencies),
                optimal_steps=optimal_steps,
                efficiency_score="0%",
                total_perception_chars=total_chars,
                estimated_tokens=total_chars // 4,
                step_latencies_ms=latencies,
                error=str(e),
            )
