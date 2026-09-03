"""
Universal Phone Harness Controller.
Orchestrates perception, actuation, zero-mistake verification, and safety across Android, iOS, and Mock devices.
"""

import time
from typing import Optional, List, Dict, Any, Tuple
from PIL import Image

from phone_harness.core.device import BasePhoneDevice
from phone_harness.core.models import (
    UIElement,
    PhoneState,
    ActionRequest,
    ActionResult,
    ActionType,
    DeviceSummary,
    VerificationSpec,
    KeyCode,
    SwipeDirection,
)
from phone_harness.core.config import HarnessConfig, DEFAULT_CONFIG
from phone_harness.core.exceptions import PhoneHarnessError, AssertionFailedError, DeviceDisconnectedError, StaleObservationError
from phone_harness.perception.tree_simplifier import TreeSimplifier
from phone_harness.perception.visual_som import VisualSoMAnnotator
from phone_harness.perception.hybrid_grounding import HybridGroundingEngine
from phone_harness.engine.verifier import ZeroMistakeVerifier
from phone_harness.engine.safety import SafetyGuard, StepBudgetGuard
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.backends.android import AndroidPhoneDevice
from phone_harness.backends.ios import IOSPhoneDevice


class PhoneHarness:
    """Main Phone Harness runtime."""

    def __init__(self, device: Optional[BasePhoneDevice] = None, config: HarnessConfig = DEFAULT_CONFIG):
        self.config = config
        self._device = device
        self.safety_guard = SafetyGuard(loop_threshold=config.max_loop_threshold)
        self.step_guard = StepBudgetGuard(max_step_budget=config.max_step_budget)
        self.last_state: Optional[PhoneState] = None
        self._observation_generation: int = 0

    @property
    def device(self) -> BasePhoneDevice:
        if self._device is None:
            self._device = self._auto_detect_device()
        return self._device

    @device.setter
    def device(self, dev: BasePhoneDevice) -> None:
        self._device = dev

    def _auto_detect_device(self) -> BasePhoneDevice:
        """Selects a device according to HarnessConfig.default_platform.

        Policy (fail-closed):
          * default_platform == "mock"  -> return Mock without probing real hardware.
          * default_platform == "android"/"ios" -> probe the requested real backend.
              - on successful connect, return it;
              - on failure, return Mock only when allow_mock_fallback is True,
                otherwise raise DeviceDisconnectedError.
          * unknown platform -> raise DeviceDisconnectedError.
        """
        platform = self.config.default_platform

        if platform == "mock":
            dev = MockPhoneDevice()
            dev.connect()
            return dev

        if platform == "android":
            dev: BasePhoneDevice = AndroidPhoneDevice()
        elif platform == "ios":
            dev = IOSPhoneDevice()
        else:
            raise DeviceDisconnectedError(
                "unknown",
                f"HarnessConfig.default_platform '{platform}' is not a recognized platform (android, ios, mock).",
            )

        try:
            if dev.connect():
                return dev
        except Exception as exc:
            if self.config.allow_mock_fallback:
                mock_dev = MockPhoneDevice()
                mock_dev.connect()
                return mock_dev
            raise DeviceDisconnectedError(
                getattr(dev, "device_id", getattr(dev, "serial", platform)),
                f"Failed to connect to {platform} device: {exc}",
            ) from exc

        # Connection attempt returned False (device not reachable / unauthorized).
        if self.config.allow_mock_fallback:
            mock_dev = MockPhoneDevice()
            mock_dev.connect()
            return mock_dev
        raise DeviceDisconnectedError(
            getattr(dev, "device_id", getattr(dev, "serial", platform)),
            f"No {platform} device connected or authorized. Set allow_mock_fallback=True for offline Mock execution.",
        )

    def observe(
        self,
        include_som_image: bool = False,
        include_raw_image: bool = False,
        filter_interactive_only: bool = True,
        skip_loop_detection: bool = False,
    ) -> PhoneState:
        """
        Captures the live screen and accessibility hierarchy, producing a token-compacted DOM.
        """
        t0 = time.time()
        if not self.device.is_connected():
            if not self.device.connect():
                raise DeviceDisconnectedError("active-device")

        # 1. Extract raw accessibility elements
        raw_elements = self.device.dump_hierarchy()

        # 2. Filter & index elements
        elements = TreeSimplifier.filter_and_index_elements(
            raw_elements=raw_elements,
            screen_size=(self.device.screen_width, self.device.screen_height),
            interactive_only=filter_interactive_only,
        )

        # 5. Capture frame if images requested or visual OCR fallback needed
        raw_frame: Optional[Image.Image] = None
        raw_b64: Optional[str] = None
        som_b64: Optional[str] = None
        p_hash: Optional[str] = None

        if len(elements) == 0 or include_som_image or include_raw_image:
            try:
                raw_frame = self.device.capture_frame()
                p_hash = ZeroMistakeVerifier.calculate_perceptual_hash(raw_frame)
            except Exception:
                p_hash = ZeroMistakeVerifier.calculate_tree_hash(elements)
        else:
            p_hash = ZeroMistakeVerifier.calculate_tree_hash(elements)

        # Visual OCR Fallback for Flutter / Unity / Canvas / Video surfaces
        if len(elements) == 0 and raw_frame:
            from phone_harness.perception.visual_detector import VisualElementDetector
            if VisualElementDetector.is_available():
                visual_elems = VisualElementDetector.detect_elements_from_image(raw_frame)
                if visual_elems:
                    elements = TreeSimplifier.filter_and_index_elements(
                        raw_elements=visual_elems,
                        screen_size=(self.device.screen_width, self.device.screen_height),
                        interactive_only=False,
                    )

        # 3. Apply PII sanitization
        if self.config.enable_pii_masking:
            elements = [self.safety_guard.sanitize_element(e) for e in elements]

        # 4. Generate token-compact DOM
        compact_dom = TreeSimplifier.generate_compact_dom(elements, max_tokens=self.config.max_tokens_compact_dom)

        if include_raw_image and raw_frame:
            raw_b64 = VisualSoMAnnotator.to_base64_jpeg(raw_frame, quality=self.config.jpeg_quality)

        if include_som_image and raw_frame:
            som_img = VisualSoMAnnotator.annotate(raw_frame, elements, mask_passwords=self.config.enable_pii_masking)
            som_b64 = VisualSoMAnnotator.to_base64_jpeg(som_img, quality=self.config.jpeg_quality)

        foreground_pkg = self.device.get_foreground_app()
        kb_visible = self.device.is_keyboard_visible()

        self._observation_generation += 1
        state = PhoneState(
            device_id=getattr(self.device, "device_id", "phone-01"),
            platform=getattr(self.device, "platform", "mock"),
            screen_width=self.device.screen_width,
            screen_height=self.device.screen_height,
            current_app_package=foreground_pkg,
            keyboard_visible=kb_visible,
            elements=elements,
            compact_dom=compact_dom,
            screenshot_base64=raw_b64,
            som_screenshot_base64=som_b64,
            perceptual_hash=p_hash,
            timestamp=time.time(),
            generation=self._observation_generation,
        )

        self.last_state = state

        # NOTE: Observations never affect loop history. Action loops are recorded
        # only after a completed, verified action (see execute_action).

        return state

    def execute_action(self, req: ActionRequest) -> ActionResult:
        """
        Executes an action request with closed-loop verification and safety gating.
        """
        t0 = time.time()

        # Step 1: Pre-actuation budget gate (BEFORE any observation / backend
        # call). An exhausted budget must perform no observation (no
        # dump_hierarchy / capture) and no actuation, so we gate before
        # refreshing state rather than after it.
        self.step_guard.check_budget()

        # Step 2: Ensure fresh state
        current_state = self.last_state or self.observe()

        # Step 2a: Stale observation generation guard (indexed actions only)
        # Indexed requests without a generation keep Python compatibility: they
        # ground against the current fresh state and proceed.
        if req.target_index is not None and req.observation_generation is not None:
            if req.observation_generation != self.last_state.generation:
                raise StaleObservationError(
                    expected_generation=req.observation_generation,
                    current_generation=self.last_state.generation,
                )

        # Step 3: Target Grounding & Pre-checks
        target_x: Optional[int] = None
        target_y: Optional[int] = None
        target_elem: Optional[UIElement] = None

        target_x, target_y, target_elem = self._resolve_action_target(req, current_state)

        # Step 3: Actuation
        self._dispatch_actuation(req, target_x, target_y)

        # Step 4: Quiescence / Settle
        settle_time = req.verify.settle_ms if req.verify else self.config.default_settle_ms
        if settle_time > 0:
            time.sleep(settle_time / 1000.0)

        # Step 5: Post-Action Observation & Verification
        new_state = self.observe(include_som_image=False, include_raw_image=False)
        verification_passed = True
        error_msg: Optional[str] = None

        if req.verify and self.config.enable_zero_mistake_verification:
            passed, failure_reason = ZeroMistakeVerifier.evaluate_post_assertions(req.verify, new_state)
            if not passed:
                if req.verify.auto_retry_on_fail:
                    # Self-healing retry: re-ground against a freshly observed state and
                    # re-run safety + precondition checks, then dispatch once. The stale
                    # generation guard is intentionally NOT re-applied here: this retry is
                    # harness-internal, not a new user request pinned to an old generation.
                    time.sleep(0.15)
                    retry_state = self.observe(include_som_image=False, include_raw_image=False)
                    target_x, target_y, target_elem = self._resolve_action_target(req, retry_state)
                    self._dispatch_actuation(req, target_x, target_y)
                    time.sleep(0.15)
                    new_state = self.observe()
                    passed_retry, failure_retry = ZeroMistakeVerifier.evaluate_post_assertions(req.verify, new_state)
                    if not passed_retry:
                        raise AssertionFailedError("Post-Action Verification", str(req.verify), failure_retry or "Assertion failed")
                else:
                    raise AssertionFailedError("Post-Action Verification", str(req.verify), failure_reason or "Assertion failed")

        elapsed_ms = (time.time() - t0) * 1000.0

        # Record completed step only after successful post-action verification
        self.step_guard.record_step(elapsed_ms)

        # Action-only loop detection: record post-action signature after success.
        if self.config.enable_loop_detection:
            action_signature = self._build_action_signature(req, target_elem, target_x, target_y, new_state)
            state_hash = new_state.perceptual_hash or ZeroMistakeVerifier.calculate_tree_hash(new_state.elements)
            self.safety_guard.record_and_check_action_loop(action_signature, state_hash)

        target_info = f"[{target_elem.id}] {target_elem.text or target_elem.type}" if target_elem else f"({target_x}, {target_y})" if target_x else req.action.value

        return ActionResult(
            success=True,
            action=req.action.value,
            target_info=target_info,
            latency_ms=round(elapsed_ms, 2),
            verification_passed=verification_passed,
            new_state=new_state,
        )

    def _resolve_action_target(
        self,
        req: ActionRequest,
        state: PhoneState,
    ) -> Tuple[Optional[int], Optional[int], Optional[UIElement]]:
        """
        Grounds an action request to (x, y, element) against the supplied state.

        Runs the same safety and precondition checks used for the initial attempt. The
        caller is responsible for any stale-generation gating; this helper only resolves
        the target for the given state so it can be reused for self-healing retries on a
        freshly observed hierarchy.
        """
        if req.action not in (ActionType.TAP, ActionType.DOUBLE_TAP, ActionType.LONG_PRESS, ActionType.TYPE):
            return None, None, None

        if not (
            req.target_index is not None
            or req.target_text is not None
            or (req.x is not None and req.y is not None)
        ):
            return None, None, None

        target_x, target_y, target_elem = HybridGroundingEngine.resolve_target_element(
            action_req=req,
            elements=state.elements,
            screen_size=(self.device.screen_width, self.device.screen_height),
        )

        # Coordinate taps cannot inherit safety from an unlabeled container.
        is_coordinate_target = (
            req.x is not None
            and req.y is not None
            and req.target_index is None
            and req.target_text is None
        )
        safety_target = target_elem
        if is_coordinate_target and target_elem is not None:
            target_label = " ".join(
                value
                for value in (
                    target_elem.text,
                    target_elem.description,
                    target_elem.resource_id,
                )
                if value
            ).strip()
            if not target_label:
                safety_target = None

        if self.config.enable_destructive_safety_gate:
            self.safety_guard.check_destructive_action(
                target_element=safety_target,
                action_name=req.action.value,
                confirm_destructive=req.confirm_destructive,
            )

        # Pre-condition verification
        ZeroMistakeVerifier.verify_pre_conditions(req, target_elem)

        return target_x, target_y, target_elem

    def _build_action_signature(
        self,
        req: ActionRequest,
        target_elem: Optional[UIElement],
        target_x: Optional[int],
        target_y: Optional[int],
        new_state: PhoneState,
    ) -> str:
        """Builds the action-state signature used for action-only loop detection."""
        action = req.action.value
        if target_elem is not None:
            target_identity = str(target_elem.id)
        elif target_x is not None and target_y is not None:
            target_identity = f"({target_x},{target_y})"
        else:
            target_identity = "none"
        package = new_state.current_app_package
        return f"{action}:{target_identity}:{package}"

    def _dispatch_actuation(self, req: ActionRequest, target_x: Optional[int], target_y: Optional[int]) -> None:
        """Sends atomic low-level input to the device HAL."""
        if req.action == ActionType.TAP:
            if target_x is None or target_y is None:
                raise PhoneHarnessError("Tap action missing target coordinates.")
            self.device.tap(target_x, target_y)

        elif req.action == ActionType.DOUBLE_TAP:
            if target_x is None or target_y is None:
                raise PhoneHarnessError("Double tap missing target coordinates.")
            self.device.double_tap(target_x, target_y)

        elif req.action == ActionType.LONG_PRESS:
            if target_x is None or target_y is None:
                raise PhoneHarnessError("Long press missing target coordinates.")
            self.device.long_press(target_x, target_y, req.duration_ms)

        elif req.action == ActionType.TYPE:
            if target_x is not None and target_y is not None:
                self.device.tap(target_x, target_y)
                time.sleep(0.05)
            text_str = req.text_to_type or ""
            self.device.type_text(text_str, clear_existing=req.clear_existing, press_enter=req.press_enter)

        elif req.action == ActionType.CLEAR:
            self.device.clear_text()

        elif req.action == ActionType.SWIPE:
            if req.direction:
                self.device.swipe_directional(req.direction, distance=req.swipe_distance, duration_ms=req.duration_ms)
            elif req.start_x is not None and req.start_y is not None and req.end_x is not None and req.end_y is not None:
                self.device.swipe(req.start_x, req.start_y, req.end_x, req.end_y, req.duration_ms)

        elif req.action == ActionType.PRESS_KEY:
            if not req.key:
                raise PhoneHarnessError("Press key action requires a valid KeyCode.")
            self.device.press_key(req.key)

        elif req.action == ActionType.OPEN_APP:
            if not req.package_name:
                raise PhoneHarnessError("Open app requires package_name.")
            self.device.launch_app(req.package_name, stop_existing=req.stop_existing)

        elif req.action == ActionType.WAIT:
            time.sleep(max(0.05, req.duration_ms / 1000.0))

    def wait_for_condition(
        self,
        text_present: Optional[List[str]] = None,
        text_absent: Optional[List[str]] = None,
        app_package: Optional[str] = None,
        timeout_ms: int = 5000,
        poll_interval_ms: int = 150,
    ) -> Tuple[bool, PhoneState]:
        """
        Locally polls the device until target assertions pass or timeout is reached.
        Saves LLM tokens and roundtrips during loading screens and async transitions.
        """
        spec = VerificationSpec(
            assert_text_present=text_present,
            assert_text_absent=text_absent,
            assert_app_package=app_package,
            timeout_ms=timeout_ms,
        )
        t_start = time.time()
        max_duration = timeout_ms / 1000.0
        last_state = self.observe(skip_loop_detection=True)

        while (time.time() - t_start) < max_duration:
            passed, _ = ZeroMistakeVerifier.evaluate_post_assertions(spec, last_state)
            if passed:
                return (True, last_state)
            time.sleep(poll_interval_ms / 1000.0)
            last_state = self.observe(skip_loop_detection=True)

        passed, reason = ZeroMistakeVerifier.evaluate_post_assertions(spec, last_state)
        return (passed, last_state)

    def open_url(self, url: str) -> PhoneState:
        """Open a validated HTTP or HTTPS URL in the default browser."""
        self.device.open_url(url)
        time.sleep(0.3)
        return self.observe()

    def open_settings(self, section: str = "settings") -> PhoneState:
        """Directly opens a system settings section (wifi, bluetooth, apps, etc.)."""
        self.device.open_settings_section(section)
        time.sleep(0.3)
        return self.observe()

    def set_clipboard(self, text: str) -> None:
        """Copies text to device clipboard for fast pasting."""
        self.device.set_clipboard(text)

    def get_clipboard(self) -> str:
        """Reads device clipboard."""
        return self.device.get_clipboard()

    def dismiss_dialog(self, action: str = "deny") -> ActionResult:
        """Detects and automatically clicks Allow/Deny on system permission or alert dialogs."""
        from phone_harness.engine.dialog_handler import SystemDialogHandler
        state = self.last_state or self.observe()
        btn = SystemDialogHandler.find_action_button(action, state.elements)
        if not btn:
            raise PhoneHarnessError(f"No dialog action button matching '{action}' found on screen.")
        req = ActionRequest(action=ActionType.TAP, target_index=btn.id)
        return self.execute_action(req)

    def get_efficiency_report(self, optimal_steps: int = 5) -> dict:
        """Returns step budget and task efficiency telemetry."""
        return self.step_guard.get_efficiency_report(optimal_steps=optimal_steps)

    def save_screenshot(
        self,
        output_path: str,
        include_som: bool = False,
    ) -> Tuple[int, int]:
        """Captures and saves a phone screenshot directly to a local file. Returns (width, height)."""
        raw_frame = self.device.capture_frame()
        if include_som:
            raw_elements = self.device.dump_hierarchy()
            elements = TreeSimplifier.filter_and_index_elements(
                raw_elements=raw_elements,
                screen_size=(self.device.screen_width, self.device.screen_height),
                interactive_only=True,
            )
            som_img = VisualSoMAnnotator.annotate(
                raw_frame,
                elements,
                mask_passwords=self.config.enable_pii_masking,
            )
            som_img.convert("RGB").save(output_path)
            return som_img.size

        raw_frame.convert("RGB").save(output_path)
        return raw_frame.size

