"""
Session Recording & Deterministic Self-Healing Trace Replayer.
Records mobile agent actions to reproducible .trace.jsonl files and provides
self-healing replay that recovers when accessibility IDs shift across app versions.
"""

import os
import json
import time
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field

from phone_harness.core.models import ActionRequest, ActionResult, ActionType, PhoneState, UIElement
from phone_harness.core.exceptions import PhoneHarnessError


class TraceStep(BaseModel):
    """Represents a single recorded interaction step."""
    step_number: int
    timestamp: float = Field(default_factory=time.time)
    action_type: str
    target_id: Optional[int] = None
    target_text: Optional[str] = None
    target_resource_id: Optional[str] = None
    target_bounds: Optional[Tuple[int, int, int, int]] = None
    action_params: Dict[str, Any] = Field(default_factory=dict)
    pre_app_package: Optional[str] = None
    pre_element_count: int = 0
    post_app_package: Optional[str] = None
    success: bool = True


class ReplayResult(BaseModel):
    """Summary of a trace replay execution."""
    trace_path: str
    total_steps: int
    executed_steps: int
    healed_steps: int
    failed_steps: int
    is_success: bool
    step_details: List[Dict[str, Any]] = Field(default_factory=list)


class SessionTracer:
    """Records interaction sessions to a .trace.jsonl file."""

    def __init__(self, output_path: Optional[str] = None):
        self.output_path: Optional[str] = output_path
        self.is_recording: bool = False
        self.step_counter: int = 0
        self._file_handle = None

        if output_path:
            self.start_recording(output_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_recording()

    def start_recording(self, output_path: str) -> None:
        """Starts recording session steps to the specified path."""
        parent_dir = os.path.dirname(os.path.abspath(output_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        self.output_path = output_path
        self._file_handle = open(output_path, "w", encoding="utf-8")
        self.is_recording = True
        self.step_counter = 0

    def record_step(
        self,
        request: ActionRequest,
        result: ActionResult,
        pre_state: PhoneState,
        post_state: Optional[PhoneState] = None,
    ) -> TraceStep:
        """Serializes and writes an action step to the trace log."""
        if not self.is_recording or self._file_handle is None:
            raise PhoneHarnessError("Cannot record step: SessionTracer is not actively recording.")

        self.step_counter += 1

        # Locate target element attributes for self-healing replay
        target_text: Optional[str] = getattr(request, "target_text", None)
        target_resource_id: Optional[str] = None
        target_bounds: Optional[Tuple[int, int, int, int]] = None
        target_id: Optional[int] = request.target_index

        if request.target_index is not None:
            for element in pre_state.elements:
                if element.id == request.target_index:
                    target_text = element.text
                    target_resource_id = element.resource_id
                    if isinstance(element.bounds, tuple) and len(element.bounds) >= 4:
                        target_bounds = (int(element.bounds[0]), int(element.bounds[1]), int(element.bounds[2]), int(element.bounds[3]))
                    break
        elif request.target_text is not None:
            for element in pre_state.elements:
                if element.text == request.target_text:
                    target_id = element.id
                    target_resource_id = element.resource_id
                    if isinstance(element.bounds, tuple) and len(element.bounds) >= 4:
                        target_bounds = (int(element.bounds[0]), int(element.bounds[1]), int(element.bounds[2]), int(element.bounds[3]))
                    break

        action_params: Dict[str, Any] = {}
        if getattr(request, "text_to_type", None) is not None:
            action_params["text_to_type"] = request.text_to_type
        if getattr(request, "direction", None) is not None:
            action_params["direction"] = request.direction.value if hasattr(request.direction, "value") else str(request.direction)
        if getattr(request, "key_code", None) is not None:
            action_params["key_code"] = request.key_code.value if hasattr(request.key_code, "value") else str(request.key_code)
        if getattr(request, "x", None) is not None and getattr(request, "y", None) is not None:
            action_params["x"] = request.x
            action_params["y"] = request.y

        step = TraceStep(
            step_number=self.step_counter,
            action_type=request.action.value,
            target_id=target_id,
            target_text=target_text,
            target_resource_id=target_resource_id,
            target_bounds=target_bounds,
            action_params=action_params,
            pre_app_package=pre_state.current_app_package,
            pre_element_count=len(pre_state.elements),
            post_app_package=post_state.current_app_package if post_state else None,
            success=result.success,
        )

        line_json = step.model_dump_json()
        self._file_handle.write(line_json + "\n")
        self._file_handle.flush()
        return step

    def stop_recording(self) -> Optional[str]:
        """Finalizes recording and closes the trace file."""
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None
        self.is_recording = False
        return self.output_path


class TraceReplayer:
    """Replays a recorded session with optional self-healing re-grounding."""

    @staticmethod
    def load_trace(trace_path: str) -> List[TraceStep]:
        """Parses a .trace.jsonl file into a list of TraceSteps."""
        if not os.path.exists(trace_path):
            raise FileNotFoundError(f"Trace file not found: {trace_path}")

        steps: List[TraceStep] = []
        with open(trace_path, "r", encoding="utf-8") as handle:
            for line in handle:
                clean_line = line.strip()
                if clean_line:
                    data = json.loads(clean_line)
                    steps.append(TraceStep.model_validate(data))
        return steps

    @classmethod
    def find_healed_target_element(cls, step: TraceStep, active_elements: List[UIElement]) -> Optional[int]:
        """
        Attempts to re-ground a target element when its numerical index has changed.
        Priority: 1) exact resource_id, 2) exact text match, 3) nearest bounding box center.
        """
        # 1. Match by unique resource ID
        if step.target_resource_id:
            for element in active_elements:
                if element.resource_id == step.target_resource_id:
                    return element.id

        # 2. Match by exact text
        if step.target_text:
            for element in active_elements:
                if element.text == step.target_text:
                    return element.id

        # 3. Match by spatial center proximity
        if step.target_bounds is not None:
            expected_cx = (step.target_bounds[0] + step.target_bounds[2]) / 2.0
            expected_cy = (step.target_bounds[1] + step.target_bounds[3]) / 2.0

            best_match_id: Optional[int] = None
            min_distance = float("inf")

            for element in active_elements:
                b = element.bounds
                if isinstance(b, tuple) and len(b) >= 4:
                    cx = (b[0] + b[2]) / 2.0
                    cy = (b[1] + b[3]) / 2.0
                elif hasattr(b, "left"):
                    cx = (b.left + b.right) / 2.0
                    cy = (b.top + b.bottom) / 2.0
                else:
                    continue

                distance = ((cx - expected_cx) ** 2 + (cy - expected_cy) ** 2) ** 0.5

                if distance < min_distance and distance < 200.0:  # within 200px radius
                    min_distance = distance
                    best_match_id = element.id

            if best_match_id is not None:
                return best_match_id

        return None

    @classmethod
    def replay_trace(
        cls,
        harness: Any,
        trace_path: str,
        enable_self_healing: bool = True,
    ) -> ReplayResult:
        """
        Replays recorded trace steps sequentially through the given PhoneHarness.
        """
        steps = cls.load_trace(trace_path)
        executed_count = 0
        healed_count = 0
        failed_count = 0
        details: List[Dict[str, Any]] = []

        for step in steps:
            # Capture current screen state
            current_state = harness.observe()

            target_index = step.target_id
            was_healed = False

            # Check if index needs healing (element missing OR shifted to different index)
            if target_index is not None:
                current_element = next((el for el in current_state.elements if el.id == target_index), None)
                needs_healing = False

                if current_element is None:
                    needs_healing = True
                elif step.target_resource_id and current_element.resource_id != step.target_resource_id:
                    needs_healing = True
                elif step.target_text and current_element.text != step.target_text:
                    needs_healing = True

                if needs_healing:
                    if enable_self_healing:
                        healed_id = cls.find_healed_target_element(step, current_state.elements)
                        if healed_id is not None:
                            target_index = healed_id
                            was_healed = True
                            healed_count += 1
                        else:
                            failed_count += 1
                            details.append({
                                "step": step.step_number,
                                "action": step.action_type,
                                "status": "failed",
                                "error": f"Element {step.target_id} not found and self-healing was unsuccessful.",
                            })
                            return ReplayResult(
                                trace_path=trace_path,
                                total_steps=len(steps),
                                executed_steps=executed_count,
                                healed_steps=healed_count,
                                failed_steps=failed_count,
                                is_success=False,
                                step_details=details,
                            )
                    else:
                        failed_count += 1
                        details.append({
                            "step": step.step_number,
                            "action": step.action_type,
                            "status": "failed",
                            "error": f"Element {step.target_id} not found.",
                        })
                        return ReplayResult(
                            trace_path=trace_path,
                            total_steps=len(steps),
                            executed_steps=executed_count,
                            healed_steps=healed_count,
                            failed_steps=failed_count,
                            is_success=False,
                            step_details=details,
                        )

            # Build and execute ActionRequest
            action_type = ActionType(step.action_type)
            action_req = ActionRequest(
                action=action_type,
                target_index=target_index,
                target_text=step.target_text if target_index is None else None,
                observation_generation=current_state.generation,
                text_to_type=step.action_params.get("text_to_type"),
                x=step.action_params.get("x"),
                y=step.action_params.get("y"),
            )

            try:
                res = harness.execute_action(action_req)
                executed_count += 1
                details.append({
                    "step": step.step_number,
                    "action": step.action_type,
                    "target_index": target_index,
                    "healed": was_healed,
                    "status": "success" if res.success else "failed",
                })
            except Exception as exc:
                failed_count += 1
                details.append({
                    "step": step.step_number,
                    "action": step.action_type,
                    "status": "exception",
                    "error": str(exc),
                })
                return ReplayResult(
                    trace_path=trace_path,
                    total_steps=len(steps),
                    executed_steps=executed_count,
                    healed_steps=healed_count,
                    failed_steps=failed_count,
                    is_success=False,
                    step_details=details,
                )

        return ReplayResult(
            trace_path=trace_path,
            total_steps=len(steps),
            executed_steps=executed_count,
            healed_steps=healed_count,
            failed_steps=failed_count,
            is_success=(failed_count == 0),
            step_details=details,
        )
