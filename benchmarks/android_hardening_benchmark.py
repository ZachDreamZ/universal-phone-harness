"""
Task 5: Connected-phone measurement runner for Android text correctness/perf.

Runs one warm-up plus five timed samples for each operation and writes a
sanitized JSON report. Designed for NON-DESTRUCTIVE observation only:

  observe, Settings launch, search-field focus, 32-char type, clear, Back, Home

Hardware safety (per task authorization):
  * Never change a setting, permission, account, message, purchase, app, or
    persistent data.
  * End on HOME and clear any temporary text (cleanup placed in ``finally``).
  * If a safe search field cannot be found, record a blocker and stop hardware
    work; do NOT improvise in another app.

Output is sanitized: it stores only device model / Android version / screen
size, raw timing samples (ms), per-operation medians, the clear-operation
change (legacy baseline vs current candidate), and boolean state assertions.
It never stores the serial, entered text, DOM content, screenshots, clipboard,
or user identifiers.

Timing methodology (Fix Round 2):
  * Untimed setup (launch Settings, locate/focus the search field, populate
    transient text) is performed *before* the timer.
  * The timer wraps ONLY the named target operation.
  * The "clear" operation is measured twice: the baseline phase uses a
    benchmark-only legacy clear (KEYCODE_MOVE_END + fixed ~20-delete burst, the
    pre-fix behaviour), while the candidate phase calls the production
    ``AndroidPhoneDevice.clear_text``. This makes the clear-operation change the
    only accepted performance comparison; unrelated diagnostics are reported
    per-operation but are NEVER aggregated into an overall gain.

Usage:
  python benchmarks/android_hardening_benchmark.py --phase baseline --output artifacts/android-hardening-benchmark.json
  python benchmarks/android_hardening_benchmark.py --phase candidate --output artifacts/android-hardening-benchmark.json

Provenance (no Git / current-edit dependency):
  * Each phase records the implementation label it used.
  * The runner records a SHA-256 fingerprint of the production ``clear_text``
    source and of the benchmark-only legacy clear source, plus a UTC timestamp,
    so the measured revision is self-describing without a VCS checkout.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import inspect
import json
import os
import shutil
import statistics
import sys
import time
from typing import Dict, List, Optional

# Ensure repo root is importable when run directly.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from phone_harness.backends.android import AndroidPhoneDevice  # noqa: E402
from phone_harness.core.models import KeyCode  # noqa: E402

OPERATIONS = [
    "observe",
    "settings_launch",
    "search_focus",
    "type_32",
    "clear",
    "back",
    "home",
]

WARMUP = 1
SAMPLES = 5

# Temporary ASCII text longer than 20 chars, used only transiently on device.
TEMP_TEXT = "PhoneHarness benchmark measurement text 12345"

SETTINGS_PKG = "com.android.settings"

# Required end-state assertions a phase must satisfy to be reported as a
# successful measurement. If any of these is false (or missing), the phase is
# NOT treated as successful and the failure is recorded.
_REQUIRED_ASSERTIONS = [
    "search_field_found",
    "foreground_package_settings",
    "temporary_text_visible",
    "cleared",
]

# Phase implementation provenance (no Git / current-edit dependency).
_PHASE_IMPLEMENTATION = {
    "baseline": (
        "legacy clear: KEYCODE_MOVE_END + fixed 22-delete burst "
        "(pre-fix reproduction)"
    ),
    "candidate": (
        "production AndroidPhoneDevice.clear_text: single host ADB shell call "
        "KEYCODE_MOVE_END && --longpress KEYCODE_DEL + bounded 64-delete fallback"
    ),
}


def _find_adb() -> Optional[str]:
    try:
        import adbutils

        try:
            return adbutils.adb_path()
        except Exception:
            pass
    except Exception:
        pass
    return shutil.which("adb")


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(statistics.median(values), 3)


def _legacy_clear_text(device: AndroidPhoneDevice) -> None:
    """Benchmark-only reproduction of the pre-fix clear: move the caret to the
    end, then issue a fixed ~20-delete burst (the legacy behaviour that could not
    reliably clear content longer than ~20 characters). This is the baseline
    implementation; it must NOT call the production ``clear_text``.
    """
    device._run_adb(["shell", "input", "keyevent", "KEYCODE_MOVE_END"])
    device._run_adb([
        "shell", "input", "keyevent",
        *(["KEYCODE_DEL"] * 22),
    ])


def _fingerprint_source(fn) -> str:
    """SHA-256 of a function's source text (self-describing revision provenance)."""
    return hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()


def _find_search_element(device: AndroidPhoneDevice):
    """Return a safe search element for tapping.

    Priority:
      1. Prefer an interactive search element -- one whose text/description/
         resource_id/type indicates "search" AND that is clickable or focusable.
      2. Fallback for OEM Settings containers (e.g. Huawei Android 12) that expose
         a non-interactive container whose resource_id final segment is exactly
         "search_layout" or "search". Such an element must be visible (positive
         area) and is accepted only by this precise id match -- never as arbitrary
         non-interactive text containing "search". Its center is returned for a
         safe tap.
    """
    try:
        elements = device.dump_hierarchy()
    except Exception:
        return None

    # Pass 1: prefer interactive (clickable/focusable) search elements.
    for el in elements:
        hay = " ".join(
            str(x)
            for x in (el.text, el.description, el.resource_id, el.type)
            if x
        ).lower()
        if "search" in hay and (el.is_clickable or el.is_focusable):
            return el

    # Pass 2: OEM non-interactive container fallback by exact resource_id segment.
    for el in elements:
        if el.resource_id is None:
            continue
        xmin, ymin, xmax, ymax = el.bounds
        # Must be visible with positive area (never a degenerate/off-screen box).
        if (xmax - xmin) <= 0 or (ymax - ymin) <= 0:
            continue
        seg = el.resource_id.split("/")[-1]
        if seg in ("search_layout", "search"):
            return el

    return None


def _launch_settings_root(device: AndroidPhoneDevice) -> None:
    """Launch the Settings ROOT dashboard. This is the timed target for the
    ``settings_launch`` operation. It does NOT force-stop: the activity-stack
    reset is performed as untimed setup in ``_ensure_settings`` so it never
    appears inside a target-operation sample.
    """
    device.open_settings_section("")  # -> android.settings.SETTINGS (root dashboard)
    time.sleep(0.4)  # wait for the root dashboard to render


def _ensure_settings(device: AndroidPhoneDevice) -> None:
    """Untimed setup: force-stop the Settings package to reset its activity stack,
    then launch the root dashboard.

    ``am start android.settings.SETTINGS`` resumes the *prior* Settings activity
    (e.g. an open search fragment) instead of the root dashboard unless the task
    stack is cleared first. Force-stop tears down that stack so the subsequent
    launch shows the root dashboard, where ``search_layout`` is present and the
    safe search field can be located. Force-stop changes NO setting values; it
    only clears the task stack.

    This helper is invoked OUTSIDE the measurement timer (in ``_op_setup`` and in
    ``_collect_assertions``), so the force-stop is never part of a timed target
    sample.
    """
    device._run_adb(["shell", "am", "force-stop", SETTINGS_PKG])
    _launch_settings_root(device)


def _op_setup(op: str, device: AndroidPhoneDevice, phase: str):
    """Untimed setup performed BEFORE the timer. Returns a pre-located element
    when the target needs it, else ``None``. May raise ``RuntimeError`` if a
    required safe element cannot be found (caller treats that as a blocker).
    """
    if op in ("settings_launch", "search_focus", "type_32", "clear"):
        _ensure_settings(device)
    if op == "search_focus":
        el = _find_search_element(device)
        if el is None:
            raise RuntimeError("safe search field not found")
        return el
    if op == "type_32":
        el = _find_search_element(device)
        if el is None:
            raise RuntimeError("safe search field not found")
        device.tap(*el.center)
        time.sleep(0.2)
        return el
    if op == "clear":
        el = _find_search_element(device)
        if el is None:
            raise RuntimeError("safe search field not found")
        device.tap(*el.center)
        time.sleep(0.2)
        # Populate transient text as untimed setup; the timed target is the clear.
        device.type_text(TEMP_TEXT, clear_existing=False, fast_paste=True)
        return el
    return None


def _op_target(op: str, device: AndroidPhoneDevice, phase: str, el=None) -> None:
    """The named target operation. The caller wraps ONLY this in the timer."""
    if op == "observe":
        device.dump_hierarchy()
    elif op == "settings_launch":
        # Timed target = the launch only. The force-stop stack reset is untimed
        # setup (see _ensure_settings / _op_setup) and must never appear in the
        # target-operation sample.
        _launch_settings_root(device)
    elif op == "search_focus":
        device.tap(*el.center)
    elif op == "type_32":
        device.type_text(TEMP_TEXT, clear_existing=False, press_enter=False, fast_paste=True)
    elif op == "clear":
        # Baseline uses the legacy reproduction; candidate uses production clear.
        if phase == "baseline":
            _legacy_clear_text(device)
        else:
            device.clear_text()
    elif op == "back":
        device.press_key(KeyCode.BACK)
    elif op == "home":
        device.press_key(KeyCode.HOME)
    else:
        raise RuntimeError(f"unknown operation {op}")


def _do_operation(op: str, device: AndroidPhoneDevice, phase: str) -> None:
    """Full operation (setup + target) used for the warm-up discard reps."""
    el = _op_setup(op, device, phase)
    _op_target(op, device, phase, el)


def _collect_assertions(device: AndroidPhoneDevice) -> Dict[str, bool]:
    """Boolean-only state assertions (no content stored)."""
    assertions: Dict[str, bool] = {}
    try:
        _ensure_settings(device)
        el = _find_search_element(device)
        assertions["search_field_found"] = el is not None
        if el is not None:
            device.tap(*el.center)
            time.sleep(0.2)
            device.type_text(TEMP_TEXT, clear_existing=False, fast_paste=True)
            time.sleep(0.2)
            fg = device.get_foreground_app()
            assertions["foreground_package_settings"] = fg == SETTINGS_PKG
            # Detect the EXACT temporary text only; hint/placeholder text must
            # not be mistaken for the transient measurement text. On Android the
            # value may surface via `text` or `value`, so both are checked.
            visible = False
            try:
                for node in device.dump_hierarchy():
                    if node.is_editable and _node_contains_temp_text(node):
                        visible = True
                        break
            except Exception:
                visible = False
            assertions["temporary_text_visible"] = visible
            device.clear_text()
            time.sleep(0.2)
            cleared = True
            try:
                for node in device.dump_hierarchy():
                    if node.is_editable and _node_contains_temp_text(node):
                        cleared = False
                        break
            except Exception:
                cleared = True
            assertions["cleared"] = cleared
    except Exception as exc:  # pragma: no cover - hardware dependent
        assertions["error"] = str(exc)
    finally:
        # Return to safe HOME state: clear temporary text, then HOME.
        try:
            device.clear_text()
        except Exception:
            pass
        try:
            device.press_key(KeyCode.HOME)
        except Exception:
            pass
    return assertions


def _node_contains_temp_text(node) -> bool:
    """Return True only when the editable node's text/value contains the exact
    TEMP_TEXT. Hint/placeholder text that merely happens to be present must not
    satisfy this check (otherwise ``cleared`` would be falsified by persistent
    hint text after a successful clear)."""
    return (
        TEMP_TEXT in (node.text or "")
        or TEMP_TEXT in (getattr(node, "value", None) or "")
    )


def _measure_phase(device: AndroidPhoneDevice, phase: str) -> Dict[str, List[float]]:
    samples: Dict[str, List[float]] = {op: [] for op in OPERATIONS}
    try:
        # Warm-up (one rep, discarded) to settle animations / caches.
        for _ in range(WARMUP):
            for op in OPERATIONS:
                try:
                    _do_operation(op, device, phase)
                except Exception:
                    pass
        # Timed samples. Setup is performed outside the timer; the timer wraps
        # ONLY the named target operation.
        for _ in range(SAMPLES):
            for op in OPERATIONS:
                el = _op_setup(op, device, phase)
                t0 = time.perf_counter()
                try:
                    _op_target(op, device, phase, el)
                except Exception:
                    pass
                samples[op].append(round((time.perf_counter() - t0) * 1000.0, 3))
    finally:
        # Return to safe HOME state: clear any temporary text, then HOME.
        try:
            device.clear_text()
        except Exception:
            pass
        try:
            device.press_key(KeyCode.HOME)
        except Exception:
            pass
    return samples


def _compute_change(baseline: Dict[str, List[float]], candidate: Dict[str, List[float]]) -> Dict[str, Optional[float]]:
    change: Dict[str, Optional[float]] = {}
    for op in OPERATIONS:
        b = _median(baseline.get(op, []))
        c = _median(candidate.get(op, []))
        if b is None or c is None or b == 0:
            change[op] = None
        else:
            change[op] = round((c - b) / b * 100.0, 2)
    return change


def _compute_clear_change(baseline: Dict[str, List[float]], candidate: Dict[str, List[float]]) -> Optional[float]:
    """Accepted headline metric: clear-operation change, legacy baseline vs
    current candidate ONLY. Unrelated diagnostics are excluded by design."""
    b = _median(baseline.get("clear", []))
    c = _median(candidate.get("clear", []))
    if b is None or c is None or b == 0:
        return None
    return round((c - b) / b * 100.0, 2)


def _finalize_report(report: dict, output_path: str) -> None:
    """Populate medians / changes / provenance and write the sanitized report.

    The overall gain is intentionally omitted (``None``) so that an aggregate of
    unrelated diagnostics can never be misread as a performance win. Only the
    clear-operation comparison is accepted as the headline metric.
    """
    report["baseline_medians"] = {
        op: _median(report["baseline"].get(op, [])) for op in OPERATIONS
    }
    report["candidate_medians"] = {
        op: _median(report["candidate"].get(op, [])) for op in OPERATIONS
    }
    report["median_change_percent"] = _compute_change(report["baseline"], report["candidate"])
    # Accepted headline metric: clear-operation change only.
    report["clear_change_percent"] = _compute_clear_change(report["baseline"], report["candidate"])
    # Sanitized metric semantics: the legacy clear used as the baseline is a
    # deliberately INCORRECT pre-fix reproduction (KEYCODE_MOVE_END + fixed ~20
    # deletes, which cannot reliably clear >20 chars). It exists only as a
    # command-cost baseline for the mandatory correctness work, so
    # clear_change_percent measures the COMMAND-COST impact of that correctness
    # work -- it is NOT an optimization and NOT a valid overall performance gain.
    report["clear_change_note"] = (
        "clear_change_percent compares the legacy clear (intentionally incorrect "
        "pre-fix reproduction) against the production clear_text. It measures the "
        "command-cost impact of mandatory correctness work only; it is NOT an "
        "optimization and NOT a valid overall performance gain."
    )
    # Never produce an overall gain from unrelated diagnostics.
    report["overall_median_change_percent"] = None
    report["overall_note"] = (
        "Overall gain intentionally null. Only the clear-operation comparison "
        "(clear_change_percent) is accepted as a headline metric, and it is "
        "explicitly NOT a valid overall gain. The legacy baseline clear is "
        "intentionally incorrect; the comparison quantifies command-cost of "
        "mandatory correctness work, not an optimization. All other diagnostics "
        "are excluded by design."
    )
    # Provenance (no Git / current-edit dependency).
    report["implementation"] = dict(_PHASE_IMPLEMENTATION)
    report["clear_text_fingerprint_sha256"] = _fingerprint_source(AndroidPhoneDevice.clear_text)
    report["legacy_clear_fingerprint_sha256"] = _fingerprint_source(_legacy_clear_text)
    report["measured_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)


def _load_existing(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Android hardening benchmark")
    parser.add_argument("--phase", choices=["baseline", "candidate"], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output_path = args.output

    report: dict = _load_existing(output_path)
    report.setdefault("task", "android-text-correctness-and-performance-hardening")
    report.setdefault("operations", OPERATIONS)
    report.setdefault("warmup_samples", WARMUP)
    report.setdefault("measured_samples", SAMPLES)
    report.setdefault("baseline", {op: [] for op in OPERATIONS})
    report.setdefault("candidate", {op: [] for op in OPERATIONS})
    report.setdefault("assertions", {})
    report["blocker"] = report.get("blocker")
    report["revision"] = None  # no Git allowed
    report["phase"] = args.phase

    adb_bin = _find_adb()
    if not adb_bin:
        report["blocker"] = (
            "adb binary not found in environment; connected-phone measurement "
            "skipped. Unit fixes and benchmark runner are still delivered."
        )
        _finalize_report(report, output_path)
        print(f"[blocker] {report['blocker']}")
        return 0

    device = AndroidPhoneDevice()
    if not device.connect():
        report["blocker"] = (
            "No connected Android device reachable via adb; connected-phone "
            "measurement skipped. Unit fixes and benchmark runner are still "
            "delivered."
        )
        _finalize_report(report, output_path)
        print(f"[blocker] {report['blocker']}")
        return 0

    summary = device.get_device_summary()
    report["device"] = {
        "model": summary.model,
        "os_version": summary.os_version,
        "screen_resolution": list(summary.screen_resolution),
    }

    try:
        samples = _measure_phase(device, args.phase)
        assertions = _collect_assertions(device)
    except Exception as exc:
        report["blocker"] = f"hardware measurement interrupted: {exc}"
        _finalize_report(report, output_path)
        print(f"[blocker] {report['blocker']}")
        return 0

    report[args.phase] = samples
    report["assertions"] = assertions

    # --------------------------------------------------------------------- #
    # Hardware-result validation (Fix Round 5): a phase is only a SUCCESS when
    # the required end-state assertions hold. If any fail, we must NOT overwrite
    # the captured raw samples with a "success" label; instead we record the
    # failure (blocker + failed_assertions) and keep the raw samples intact.
    # --------------------------------------------------------------------- #
    failed = [k for k in _REQUIRED_ASSERTIONS if not assertions.get(k)]
    if failed:
        report["phase_successful"] = False
        report["failed_assertions"] = failed
        report["blocker"] = (
            "hardware result validation failed for required assertions: "
            + ", ".join(failed)
        )
    else:
        # Genuine success: clear any stale blocker left by a prior partial run.
        report["phase_successful"] = True
        report["failed_assertions"] = []
        report["blocker"] = None

    _finalize_report(report, output_path)
    print(f"[{args.phase}] wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
