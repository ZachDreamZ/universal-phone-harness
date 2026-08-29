"""
End-to-End Comprehensive Verification Suite for Universal Phone Harness.
Validates all tools, perception modules, actuation engines, safety gates, and integrations.
"""

import argparse
import sys
import time
import json
from pathlib import Path
from io import BytesIO
from PIL import Image

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table

from phone_harness.core.models import (
    UIElement,
    ActionRequest,
    ActionResult,
    ActionType,
    KeyCode,
    SwipeDirection,
    VerificationSpec,
)
from phone_harness.core.config import HarnessConfig
from phone_harness.core.exceptions import DestructiveActionGatedError, AssertionFailedError
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.backends.android import AndroidPhoneDevice
from phone_harness.harness import PhoneHarness
from phone_harness.perception.tree_simplifier import TreeSimplifier
from phone_harness.perception.visual_som import VisualSoMAnnotator
from phone_harness.perception.visual_detector import VisualElementDetector
from phone_harness.perception.ocr_matcher import TextMatcher
from phone_harness.engine.verifier import ZeroMistakeVerifier
from phone_harness.engine.safety import SafetyGuard
from phone_harness.engine.dialog_handler import SystemDialogHandler
from phone_harness.engine.trajectory import TrajectoryRecorder
from phone_harness.mcp_server import PhoneHarnessMCPServer

console = Console()


def run_full_verification(require_hardware: bool = False):
    console.print("\n[bold cyan]===========================================================[/bold cyan]")
    console.print("[bold cyan]   UNIVERSAL PHONE HARNESS - FULL END-TO-END VERIFICATION  [/bold cyan]")
    console.print("[bold cyan]===========================================================[/bold cyan]\n")

    results = []

    # -------------------------------------------------------------
    # 1. Perception & Token Compaction
    # -------------------------------------------------------------
    t0 = time.time()
    raw_nodes = [
        UIElement.create(1, "TextView", (50, 100, 400, 200), text="Settings", is_clickable=True),
        UIElement.create(2, "Button", (50, 250, 400, 350), text="Search", is_clickable=True),
        UIElement.create(3, "FrameLayout", (0, 0, 1080, 2400), text=None, is_clickable=False),  # should be pruned
    ]
    compact = TreeSimplifier.filter_and_index_elements(raw_nodes, (1080, 2400), interactive_only=True)
    dom_text = TreeSimplifier.generate_compact_dom(compact)
    p1_pass = len(compact) == 2 and "[1]" in dom_text and "[2]" in dom_text
    results.append(("Perception: Tree Pruning & Bounded Compaction", p1_pass, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 2. Visual Set-of-Marks (SoM) Annotator
    # -------------------------------------------------------------
    t0 = time.time()
    img = Image.new("RGB", (1080, 2400), color=(30, 30, 30))
    annotated = VisualSoMAnnotator.annotate(img, compact)
    p2_pass = annotated.size == (1080, 2400) and annotated != img
    results.append(("Perception: Visual Set-of-Marks (SoM) Badges", p2_pass, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 3. OCR Matcher & Fuzzy Grounding
    # -------------------------------------------------------------
    t0 = time.time()
    score = TextMatcher.similarity("Settings", "settings")
    fuzzy_target = TextMatcher.find_best_match("Wi-Fi & Networks", [UIElement.create(1, "Text", (0, 0, 10, 10), text="Wi-Fi Network")])
    p3_pass = score > 0.9 and fuzzy_target is not None
    results.append(("Perception: Fuzzy Text Grounding Engine", p3_pass, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 4. RapidOCR Visual Detector Fallback
    # -------------------------------------------------------------
    t0 = time.time()
    ocr_avail = VisualElementDetector.is_available()
    results.append(("Perception: RapidOCR Canvas/Flutter Fallback", ocr_avail, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 5. Closed-Loop Verification & Perceptual Hash
    # -------------------------------------------------------------
    t0 = time.time()
    from PIL import ImageDraw
    img1 = Image.new("RGB", (100, 100), color=(0, 0, 0))
    d1 = ImageDraw.Draw(img1)
    d1.rectangle([(0, 0), (50, 50)], fill=(255, 255, 255))
    phash1 = ZeroMistakeVerifier.calculate_perceptual_hash(img1)

    img2 = Image.new("RGB", (100, 100), color=(255, 255, 255))
    d2 = ImageDraw.Draw(img2)
    d2.rectangle([(0, 0), (50, 50)], fill=(0, 0, 0))
    phash2 = ZeroMistakeVerifier.calculate_perceptual_hash(img2)

    p5_pass = phash1 != phash2 and len(phash1) == 16
    results.append(("Engine: Closed-Loop pHash State Differencing", p5_pass, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 6. Safety Guard & Destructive Action Gate
    # -------------------------------------------------------------
    t0 = time.time()
    safety = SafetyGuard()
    dest_elem = UIElement.create(1, "Button", (100, 100, 200, 200), text="Delete Account", is_clickable=True)
    gate_blocked = False
    try:
        safety.check_destructive_action(dest_elem, "tap", confirm_destructive=False)
    except DestructiveActionGatedError:
        gate_blocked = True
    results.append(("Engine: Destructive Action Safety Gate", gate_blocked, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 7. System Permission & Alert Dialog Interceptor
    # -------------------------------------------------------------
    t0 = time.time()
    dialog_elems = [
        UIElement.create(1, "TextView", (100, 100, 800, 200), text="Allow Maps to access location?", is_clickable=False),
        UIElement.create(2, "Button", (100, 300, 800, 400), text="While using the app", is_clickable=True),
        UIElement.create(3, "Button", (100, 450, 800, 550), text="Don't allow", is_clickable=True),
    ]
    is_dlg = SystemDialogHandler.is_permission_or_alert_dialog("com.android.permissioncontroller", dialog_elems)
    allow_btn = SystemDialogHandler.find_action_button("allow", dialog_elems)
    p7_pass = is_dlg and allow_btn and allow_btn.id == 2
    results.append(("Engine: System Dialog & Permission Interceptor", bool(p7_pass), round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 8. Trajectory Recorder
    # -------------------------------------------------------------
    t0 = time.time()
    recorder = TrajectoryRecorder(session_id="verify_sess", device_id="mock", platform="mock")
    req_act = ActionRequest(action=ActionType.TAP, target_index=1)
    res_act = ActionResult(success=True, action="tap", target_info="[1] Settings", latency_ms=12.5, verification_passed=True)
    recorder.record_step(req_act, res_act)
    session_data = recorder.finalize()
    p8_pass = len(session_data["steps"]) == 1 and session_data["session_id"] == "verify_sess"
    results.append(("Engine: Trajectory Recorder & Audit Logging", p8_pass, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 9. Dynamic Wait Poller (wait_for_condition)
    # -------------------------------------------------------------
    t0 = time.time()
    mock_dev = MockPhoneDevice()
    mock_harness = PhoneHarness(device=mock_dev)
    passed_wait, _ = mock_harness.wait_for_condition(text_present=["Settings"], timeout_ms=500)
    results.append(("Engine: Dynamic Client-side State Poller", passed_wait, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 10. Validated HTTP(S) URL and Settings intents
    # -------------------------------------------------------------
    t0 = time.time()
    st_url = mock_harness.open_url("https://google.com")
    st_set = mock_harness.open_settings("wifi")
    p10_pass = st_url.current_app_package == "com.android.chrome" and st_set.current_app_package == "com.android.settings"
    results.append(("HAL: Validated URL & Settings Intents", p10_pass, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 11. Clipboard Fast Paste & Unicode Injection
    # -------------------------------------------------------------
    t0 = time.time()
    mock_harness.set_clipboard("Unicode Test 🚀 🔥 日本語")
    clip_val = mock_harness.get_clipboard()
    results.append(("HAL: Clipboard Fast Paste & Unicode Injection", clip_val == "Unicode Test 🚀 🔥 日本語", round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 12. MCP Server JSON-RPC Protocol
    # -------------------------------------------------------------
    t0 = time.time()
    mcp_srv = PhoneHarnessMCPServer(harness=mock_harness)
    tools = mcp_srv.get_tool_definitions()
    tool_names = [t["name"] for t in tools]
    required_tools = {
        "phone_observe", "phone_tap", "phone_type", "phone_set_clipboard",
        "phone_open_url", "phone_open_settings", "phone_wait_for", "phone_dismiss_dialog",
        "phone_swipe", "phone_press_key", "phone_open_app", "phone_assert_state", "phone_health_check",
        "phone_long_press", "phone_double_tap", "phone_efficiency_report",
    }
    p12_pass = required_tools.issubset(set(tool_names))
    results.append((f"MCP: Protocol Compliance ({len(tool_names)} Tools Registered)", p12_pass, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 13. Physical Hardware Diagnostics (Connected Android Device)
    # -------------------------------------------------------------
    t0 = time.time()
    android_dev = AndroidPhoneDevice()
    hw_connected = android_dev.connect()
    if hw_connected:
        summary = android_dev.get_device_summary()
        hw_pass = summary.is_connected and summary.screen_resolution[0] > 0
        results.append((f"Live Hardware: {summary.model} ({summary.os_version})", hw_pass, round((time.time() - t0) * 1000, 2)))
    else:
        hardware_status = False if require_hardware else None
        results.append(("Live Hardware: Physical Device Connection", hardware_status, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 14. Live Physical Screen Observation & Token Compaction
    # -------------------------------------------------------------
    if hw_connected:
        t0 = time.time()
        live_harness = PhoneHarness(device=android_dev, config=HarnessConfig(enable_loop_detection=False))
        live_state = live_harness.observe()
        live_pass = len(live_state.elements) > 0 and len(live_state.compact_dom) > 0
        results.append((f"Live Perception: Indexed DOM ({len(live_state.elements)} nodes, {len(live_state.compact_dom)} chars)", live_pass, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # 15. Plugin Manifest Integrity
    # -------------------------------------------------------------
    t0 = time.time()
    try:
        project_root = Path(__file__).resolve().parent
        plugin_manifest = json.loads((project_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        claude_config = json.loads(
            (project_root / "phone_harness" / "plugins" / "claude_desktop_config.json").read_text(encoding="utf-8")
        )
        plugin_ok = plugin_manifest.get("name") == "phone-harness" and plugin_manifest.get("version") == "1.0.0"
        mcp_ok = "phone-harness" in claude_config.get("mcpServers", {})
        results.append(("Plugin Manifests: Package Integrity", plugin_ok and mcp_ok, round((time.time() - t0) * 1000, 2)))
    except Exception:
        results.append(("Plugin Manifests: Package Integrity", False, round((time.time() - t0) * 1000, 2)))

    # -------------------------------------------------------------
    # Render Results Table
    # -------------------------------------------------------------
    table = Table(title="Phone Harness Verification Matrix", show_header=True, header_style="bold magenta")
    table.add_column("Component / Capability", style="cyan", width=52)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Latency", justify="right", width=12)

    all_passed = True
    for name, passed, latency in results:
        if passed is None:
            status_str = "[bold yellow][SKIP][/bold yellow]"
        elif passed:
            status_str = "[bold green][PASS][/bold green]"
        else:
            status_str = "[bold red][FAIL][/bold red]"
            all_passed = False
        table.add_row(name, status_str, f"{latency} ms")

    console.print(table)
    console.print()
    if all_passed:
        console.print("[bold green][SUCCESS] All required verification checks passed.[/bold green]\n")
    else:
        console.print("[bold red][WARNING] Some required checks failed. Review table above.[/bold red]\n")
    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify Phone Harness subsystems")
    parser.add_argument(
        "--require-hardware",
        action="store_true",
        help="Fail when no authorized Android device is connected",
    )
    arguments = parser.parse_args()
    raise SystemExit(0 if run_full_verification(require_hardware=arguments.require_hardware) else 1)
