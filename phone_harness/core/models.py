"""
Core data models for Universal Phone Harness (UPH).
Defines schemas for elements, states, actions, verifications, and device summaries.
"""

from __future__ import annotations
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field


class ActionType(str, Enum):
    TAP = "tap"
    DOUBLE_TAP = "double_tap"
    LONG_PRESS = "long_press"
    TYPE = "type"
    CLEAR = "clear"
    SWIPE = "swipe"
    DRAG = "drag"
    PRESS_KEY = "press_key"
    OPEN_APP = "open_app"
    ASSERT = "assert"
    WAIT = "wait"


class KeyCode(str, Enum):
    HOME = "HOME"
    BACK = "BACK"
    APP_SWITCH = "APP_SWITCH"
    ENTER = "ENTER"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    POWER = "POWER"
    DELETE = "DELETE"
    TAB = "TAB"


class SwipeDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class BoundingBox(BaseModel):
    """Normalized or physical pixel bounding box [xmin, ymin, xmax, ymax]."""
    xmin: int
    ymin: int
    xmax: int
    ymax: int

    @property
    def width(self) -> int:
        return max(0, self.xmax - self.xmin)

    @property
    def height(self) -> int:
        return max(0, self.ymax - self.ymin)

    @property
    def center(self) -> Tuple[int, int]:
        return (self.xmin + self.width // 2, self.ymin + self.height // 2)

    @property
    def area(self) -> int:
        return self.width * self.height

    def contains(self, x: int, y: int) -> bool:
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.xmin, self.ymin, self.xmax, self.ymax)


class UIElement(BaseModel):
    """Represents an interactive or informative on-screen UI element."""
    id: int = Field(description="Deterministic integer badge ID [1, 2, 3, ...]")
    type: str = Field(default="View", description="Widget class (Button, EditText, TextView, CheckBox, etc.)")
    text: Optional[str] = Field(default=None, description="Visible text content")
    description: Optional[str] = Field(default=None, description="Accessibility contentDescription or label")
    resource_id: Optional[str] = Field(default=None, description="Android resource-id or iOS accessibilityIdentifier")
    bounds: Tuple[int, int, int, int] = Field(description="[xmin, ymin, xmax, ymax] in physical pixels")
    center: Tuple[int, int] = Field(description="Calculated (center_x, center_y)")
    is_clickable: bool = Field(default=False)
    is_focusable: bool = Field(default=False)
    is_scrollable: bool = Field(default=False)
    is_editable: bool = Field(default=False)
    is_checked: Optional[bool] = Field(default=None)
    is_enabled: bool = Field(default=True)
    is_password: bool = Field(default=False)
    value: Optional[str] = Field(default=None, description="Current text value for input fields")

    @classmethod
    def create(
        cls,
        id: int,
        type: str,
        bounds: Tuple[int, int, int, int],
        text: Optional[str] = None,
        description: Optional[str] = None,
        resource_id: Optional[str] = None,
        is_clickable: bool = True,
        is_focusable: bool = False,
        is_scrollable: bool = False,
        is_editable: bool = False,
        is_checked: Optional[bool] = None,
        is_enabled: bool = True,
        is_password: bool = False,
        value: Optional[str] = None,
    ) -> "UIElement":
        xmin, ymin, xmax, ymax = bounds
        center_x = xmin + (xmax - xmin) // 2
        center_y = ymin + (ymax - ymin) // 2
        return cls(
            id=id,
            type=type,
            text=text,
            description=description,
            resource_id=resource_id,
            bounds=bounds,
            center=(center_x, center_y),
            is_clickable=is_clickable,
            is_focusable=is_focusable,
            is_scrollable=is_scrollable,
            is_editable=is_editable,
            is_checked=is_checked,
            is_enabled=is_enabled,
            is_password=is_password,
            value=value,
        )

    def to_compact_line(self) -> str:
        """Returns a single token-optimized line for LLM prompts."""
        label_parts = []
        if self.text:
            label_parts.append(f'"{self.text}"')
        if self.description and self.description != self.text:
            label_parts.append(f'desc="{self.description}"')
        if self.resource_id:
            res_short = self.resource_id.split("/")[-1]
            label_parts.append(f'id="{res_short}"')

        label_str = " ".join(label_parts) if label_parts else '""'

        flags = []
        if self.is_clickable:
            flags.append("clickable")
        if self.is_editable:
            flags.append("editable")
        if self.is_focusable:
            flags.append("focusable")
        if self.is_scrollable:
            flags.append("scrollable")
        if self.is_checked is not None:
            flags.append(f"checked={str(self.is_checked).lower()}")
        if not self.is_enabled:
            flags.append("disabled")
        if self.is_password:
            flags.append("password")

        flags_str = f" [{', '.join(flags)}]" if flags else ""
        val_str = f' value="{self.value}"' if self.value is not None else ""

        w = self.bounds[2] - self.bounds[0]
        h = self.bounds[3] - self.bounds[1]
        bounds_str = f"{{{self.bounds[0]}, {self.bounds[1]}, {w}, {h}}}"

        return f"[{self.id}] {self.type} {label_str} {bounds_str}{flags_str}{val_str}".strip()


class PhoneState(BaseModel):
    """Complete snapshot of phone device state."""
    device_id: str
    platform: str  # "android", "ios", "mock"
    screen_width: int
    screen_height: int
    orientation: str = "PORTRAIT"  # "PORTRAIT", "LANDSCAPE"
    current_app_package: str
    current_activity: Optional[str] = None
    keyboard_visible: bool = False
    elements: List[UIElement] = Field(default_factory=list)
    compact_dom: str = ""
    screenshot_base64: Optional[str] = None
    som_screenshot_base64: Optional[str] = None
    perceptual_hash: Optional[str] = None
    timestamp: float = 0.0
    generation: int = 0  # monotonic observation generation, incremented per capture


class VerificationSpec(BaseModel):
    """Deterministic assertions executed after an action to guarantee zero mistakes."""
    assert_text_present: Optional[List[str]] = Field(
        default=None, description="Strings that MUST appear on the screen after action"
    )
    assert_text_absent: Optional[List[str]] = Field(
        default=None, description="Strings that MUST NOT appear on the screen after action"
    )
    assert_app_package: Optional[str] = Field(
        default=None, description="Package that MUST be in foreground after action"
    )
    assert_element_exists: Optional[Dict[str, Any]] = Field(
        default=None, description="Key-value filters for element that must exist"
    )
    timeout_ms: int = Field(default=2000, description="Verification timeout window")
    settle_ms: int = Field(default=100, description="Settling delay before evaluation")
    auto_retry_on_fail: bool = Field(default=True, description="Attempt self-healing retry if assertion fails")


class ActionRequest(BaseModel):
    """Action payload requested by an agent."""
    action: ActionType
    target_index: Optional[int] = None
    target_text: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    text_to_type: Optional[str] = None
    clear_existing: bool = True
    press_enter: bool = False
    direction: Optional[SwipeDirection] = None
    swipe_distance: str = "medium"  # "short", "medium", "long"
    start_x: Optional[int] = None
    start_y: Optional[int] = None
    end_x: Optional[int] = None
    end_y: Optional[int] = None
    key: Optional[KeyCode] = None
    package_name: Optional[str] = None
    stop_existing: bool = False
    duration_ms: int = 250
    verify: Optional[VerificationSpec] = None
    confirm_destructive: bool = False
    observation_generation: Optional[int] = None  # generation the indexed target was resolved against


class ActionResult(BaseModel):
    """Result of an action execution."""
    success: bool
    action: str
    target_info: Optional[str] = None
    latency_ms: float
    verification_passed: bool = True
    new_state: Optional[PhoneState] = None
    error_message: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class DeviceSummary(BaseModel):
    """High-level hardware status and telemetry."""
    device_id: str
    platform: str
    model: str
    os_version: str
    screen_resolution: Tuple[int, int]
    is_connected: bool
    battery_level: Optional[int] = None
    active_package: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)


class MacroStep(BaseModel):
    """Single step in an automated deterministic macro."""
    step_id: int
    action: ActionRequest
    description: Optional[str] = None
    delay_after_ms: int = 100


class Macro(BaseModel):
    """Sequence of deterministic UI actions."""
    name: str
    description: Optional[str] = None
    steps: List[MacroStep] = Field(default_factory=list)
