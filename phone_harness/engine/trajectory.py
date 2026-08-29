"""
Trajectory Recorder & Visual Replay Engine.
Captures step-by-step agent execution trajectories with visual diffs, timing metrics, and replay logs.
"""

import time
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from phone_harness.core.models import ActionRequest, ActionResult, PhoneState


class TrajectoryStep(BaseModel):
    step_id: int
    timestamp: float
    action: Dict[str, Any]
    result: Dict[str, Any]
    pre_app: str
    post_app: str
    pre_compact_dom: str
    post_compact_dom: str
    latency_ms: float


class TrajectorySession(BaseModel):
    session_id: str
    device_id: str
    platform: str
    start_time: float
    end_time: Optional[float] = None
    steps: List[TrajectoryStep] = Field(default_factory=list)
    total_latency_ms: float = 0.0


class TrajectoryRecorder:
    """Records agent execution trajectories for verification, auditing, and replay."""

    def __init__(self, session_id: Optional[str] = None, device_id: str = "auto", platform: str = "android"):
        self.session = TrajectorySession(
            session_id=session_id or f"session_{int(time.time())}",
            device_id=device_id,
            platform=platform,
            start_time=time.time(),
        )

    def record_step(
        self,
        action_req: ActionRequest,
        action_res: ActionResult,
        pre_state: Optional[PhoneState] = None,
    ) -> TrajectoryStep:
        step_id = len(self.session.steps) + 1
        pre_app = pre_state.current_app_package if pre_state else "unknown"
        post_app = action_res.new_state.current_app_package if action_res.new_state else pre_app
        pre_dom = pre_state.compact_dom if pre_state else ""
        post_dom = action_res.new_state.compact_dom if action_res.new_state else ""

        step = TrajectoryStep(
            step_id=step_id,
            timestamp=time.time(),
            action=action_req.model_dump(exclude_none=True),
            result={
                "success": action_res.success,
                "action": action_res.action,
                "target": action_res.target_info,
                "latency_ms": action_res.latency_ms,
            },
            pre_app=pre_app,
            post_app=post_app,
            pre_compact_dom=pre_dom,
            post_compact_dom=post_dom,
            latency_ms=action_res.latency_ms,
        )
        self.session.steps.append(step)
        self.session.total_latency_ms += action_res.latency_ms
        return step

    def finalize(self) -> Dict[str, Any]:
        self.session.end_time = time.time()
        return self.session.model_dump()

    def export_json(self) -> str:
        return self.session.model_dump_json(indent=2)
