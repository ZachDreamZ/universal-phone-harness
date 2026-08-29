"""
Task 5 Fix Round 2: deterministic benchmark unit tests.

These tests exercise the benchmark runner's pure logic and command construction
without touching real hardware or subprocess:

  * timing methodology: the timer wraps ONLY the named target operation
    (untimed setup runs before the clock is read);
  * legacy baseline clear reproduces KEYCODE_MOVE_END + fixed ~20 deletes;
  * candidate clear calls the production clear_text implementation;
  * median / per-op change / clear-only change math is deterministic;
  * SHA-256 provenance fingerprints are stable hex digests;
  * the sanitized no-device report is deterministic and contains no sensitive
    data, and never reports an overall gain derived from unrelated diagnostics.
"""

import json
import sys

import pytest

# Ensure repo root importable.
_ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import benchmarks.android_hardening_benchmark as bm  # noqa: E402
from phone_harness.backends.android import AndroidPhoneDevice  # noqa: E402
from phone_harness.core.models import UIElement, DeviceSummary  # noqa: E402

# Shared fake clock advanced by device commands; the benchmark timer reads it.
_FAKE_CLOCK = {"t": 0.0}


class _RecordingDevice(AndroidPhoneDevice):
    """Records command construction without touching subprocess/hardware."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def _run_adb(self, args, timeout=5.0):
        self.calls.append(list(args))
        return ""

    def get_clipboard(self):
        return ""


class _ClockDevice(AndroidPhoneDevice):
    """Records commands and advances a fake clock per adb call. ``set_clipboard``
    is overridden to a no-op so transient text population succeeds without a real
    device; ``dump_hierarchy`` returns a single safe search element so setup can
    locate/focus the field."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def _run_adb(self, args, timeout=5.0):
        self.calls.append(list(args))
        # Each adb command costs 1 ms (0.001 s); the benchmark multiplies the
        # perf_counter delta by 1000 to report milliseconds.
        _FAKE_CLOCK["t"] += 0.001
        return ""

    def get_clipboard(self):
        return ""

    def set_clipboard(self, text):
        self.calls.append(["set_clipboard", text])

    def dump_hierarchy(self):
        return [
            UIElement.create(
                1, "EditText", (100, 100, 500, 200),
                text="Search", is_editable=True, is_clickable=True,
                resource_id="com.android.settings/search",
            )
        ]


def _joined(dev):
    return [" ".join(c) for c in dev.calls]


# --------------------------------------------------------------------------- #
# Pure math determinism
# --------------------------------------------------------------------------- #
def test_median_basic_and_empty():
    assert bm._median([1.0, 2.0, 3.0]) == 2.0
    assert bm._median([3.0, 1.0, 2.0]) == 2.0
    assert bm._median([]) is None
    # Deterministic across repeated calls.
    assert bm._median([5.0, 1.0, 3.0, 2.0, 4.0]) == bm._median([5.0, 1.0, 3.0, 2.0, 4.0])


def test_compute_change_handles_missing_and_zero():
    baseline = {op: [100.0] * 5 for op in bm.OPERATIONS}
    candidate = {op: [90.0] * 5 for op in bm.OPERATIONS}
    change = bm._compute_change(baseline, candidate)
    # -10% for every op.
    assert change["observe"] == -10.0
    # Missing candidate -> None.
    missing = {op: [] for op in bm.OPERATIONS}
    assert bm._compute_change(baseline, missing)["observe"] is None
    # Zero baseline -> None (avoid divide-by-zero).
    zero = {op: [0.0] * 5 for op in bm.OPERATIONS}
    assert bm._compute_change(zero, candidate)["observe"] is None


def test_compute_clear_change_only_uses_clear_op():
    baseline = {op: [100.0] * 5 for op in bm.OPERATIONS}
    candidate = {op: [100.0] * 5 for op in bm.OPERATIONS}
    # Clear improves by 10%, but an unrelated op regresses by 50%.
    baseline["clear"] = [100.0] * 5
    candidate["clear"] = [90.0] * 5
    baseline["observe"] = [100.0] * 5
    candidate["observe"] = [150.0] * 5
    # Accepted metric reflects ONLY the clear operation (+10% => -10.0).
    assert bm._compute_clear_change(baseline, candidate) == -10.0
    # No clear samples -> None.
    assert bm._compute_clear_change({op: [] for op in bm.OPERATIONS}, candidate) is None


# --------------------------------------------------------------------------- #
# Legacy baseline vs production candidate clear construction
# --------------------------------------------------------------------------- #
def test_legacy_clear_reproduces_move_end_plus_22_deletes():
    dev = _RecordingDevice()
    bm._legacy_clear_text(dev)
    joined = _joined(dev)
    # Must contain KEYCODE_MOVE_END and a fixed 22-delete burst.
    assert any("KEYCODE_MOVE_END" in j for j in joined), joined
    del_cmds = [c for c in dev.calls if c[1:3] == ["input", "keyevent"] and "KEYCODE_DEL" in c]
    assert del_cmds, joined
    n = max(c.count("KEYCODE_DEL") for c in del_cmds)
    assert n == 22, joined
    # Legacy must NOT use the modern keycombination select-all chord.
    assert not any("keycombination" in c for c in dev.calls), joined
    # Order: MOVE_END before the delete burst.
    move_i = next(i for i, c in enumerate(dev.calls) if "KEYCODE_MOVE_END" in c)
    del_i = next(i for i, c in enumerate(dev.calls) if "KEYCODE_DEL" in c)
    assert move_i < del_i, joined


def test_candidate_clear_uses_production_clear_text():
    dev = _RecordingDevice()
    dev.clear_text()  # production clear_text
    joined = _joined(dev)
    # The candidate target must be the fast single-call primary path: exactly one
    # host ADB shell call carrying KEYCODE_MOVE_END then --longpress KEYCODE_DEL.
    assert len(dev.calls) == 1, joined
    assert any(
        "KEYCODE_MOVE_END" in s and "--longpress KEYCODE_DEL" in s
        for s in joined
    ), joined
    # No select-all chord in the production clear.
    assert not any("keycombination" in s for s in joined), joined
    # The legacy reproduction must NOT contain the production primary command.
    dev2 = _RecordingDevice()
    bm._legacy_clear_text(dev2)
    legacy = _joined(dev2)
    assert not any("KEYCODE_MOVE_END &&" in s for s in legacy), legacy
    assert not any("--longpress KEYCODE_DEL" in s for s in legacy), legacy


# --------------------------------------------------------------------------- #
# Timing methodology: timer wraps ONLY the target operation
# --------------------------------------------------------------------------- #
def test_timed_region_wraps_only_target_operation(monkeypatch):
    _FAKE_CLOCK["t"] = 0.0
    dev = _ClockDevice()
    monkeypatch.setattr(bm.time, "perf_counter", lambda: _FAKE_CLOCK["t"])
    monkeypatch.setattr(bm.time, "sleep", lambda *a, **k: None)

    samples = bm._measure_phase(dev, "candidate")

    # The "clear" target is production clear_text: a SINGLE host ADB shell call
    # carrying all ordered input commands => exactly 1.0 ms per sample,
    # independent of the (much larger) untimed setup cost that ran before the
    # clock was read.
    assert samples["clear"] == [1.0] * bm.SAMPLES, samples["clear"]

    # Every operation's timed samples are identical (deterministic timing):
    # proof that the timer wraps only the target, not the setup.
    for op, vals in samples.items():
        assert len(set(vals)) == 1, f"{op} samples not deterministic: {vals}"


def test_baseline_clear_target_cost_differs_from_candidate(monkeypatch):
    _FAKE_CLOCK["t"] = 0.0
    dev = _ClockDevice()
    monkeypatch.setattr(bm.time, "perf_counter", lambda: _FAKE_CLOCK["t"])
    monkeypatch.setattr(bm.time, "sleep", lambda *a, **k: None)

    baseline = bm._measure_phase(dev, "baseline")
    _FAKE_CLOCK["t"] = 0.0
    candidate = bm._measure_phase(dev, "candidate")

    # Baseline legacy clear = MOVE_END + 22-delete = 2 calls => 2.0 ms.
    assert baseline["clear"] == [2.0] * bm.SAMPLES, baseline["clear"]
    # Candidate production clear = 1 call (single shell roundtrip) => 1.0 ms
    # (the only accepted delta).
    assert candidate["clear"] == [1.0] * bm.SAMPLES, candidate["clear"]


# --------------------------------------------------------------------------- #
# Provenance fingerprints
# --------------------------------------------------------------------------- #
def test_fingerprint_is_deterministic_sha256():
    fp1 = bm._fingerprint_source(AndroidPhoneDevice.clear_text)
    fp2 = bm._fingerprint_source(AndroidPhoneDevice.clear_text)
    assert fp1 == fp2
    assert len(fp1) == 64 and all(c in "0123456789abcdef" for c in fp1)
    legacy = bm._fingerprint_source(bm._legacy_clear_text)
    assert legacy != fp1
    assert len(legacy) == 64


# --------------------------------------------------------------------------- #
# Sanitized no-device report (deterministic, no sensitive data, no overall gain)
# --------------------------------------------------------------------------- #
def test_no_device_path_emits_sanitized_blocker_report(tmp_path, monkeypatch):
    out = tmp_path / "report.json"
    monkeypatch.setattr(bm, "_find_adb", lambda: None)
    monkeypatch.setattr(sys, "argv", ["bench", "--phase", "baseline", "--output", str(out)])

    rc = bm.main()
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["blocker"]
    assert data["revision"] is None
    assert data["implementation"]["baseline"].startswith("legacy clear")
    assert data["implementation"]["candidate"].startswith("production")
    assert "clear_text_fingerprint_sha256" in data
    assert "legacy_clear_fingerprint_sha256" in data
    assert "measured_at" in data
    assert data["clear_change_percent"] is None
    # Never produce an overall gain from unrelated diagnostics.
    assert data["overall_median_change_percent"] is None
    assert data["overall_note"]

    # Sanitized: no serial, no entered temporary text, no clipboard content.
    blob = json.dumps(data)
    assert bm.TEMP_TEXT not in blob
    if data.get("device") is not None:
        assert "serial" not in str(data["device"]).lower()


def test_overall_gain_never_derived_from_diagnostics(tmp_path):
    report = {
        "baseline": {op: [] for op in bm.OPERATIONS},
        "candidate": {op: [] for op in bm.OPERATIONS},
    }
    # Diagnostics show a huge (-90%) gain; clear shows a small (+10%) regression.
    report["baseline"]["observe"] = [100.0] * 5
    report["candidate"]["observe"] = [10.0] * 5
    report["baseline"]["clear"] = [100.0] * 5
    report["candidate"]["clear"] = [110.0] * 5

    out = tmp_path / "r.json"
    bm._finalize_report(report, str(out))

    # Accepted headline reflects ONLY the clear operation (+10%).
    assert report["clear_change_percent"] == 10.0
    # Per-op diagnostics are still transparent...
    assert report["median_change_percent"]["observe"] == -90.0
    assert report["median_change_percent"]["clear"] == 10.0
    # ...but the overall aggregate is intentionally omitted (no diagnostic gain).
    assert report["overall_median_change_percent"] is None


def test_report_policy_legacy_clear_incorrect_and_clear_change_sanitized(tmp_path):
    """Finding #4: the report must document that the legacy clear baseline is
    intentionally INCORRECT and that clear_change_percent measures the
    command-cost impact of mandatory correctness work only -- not an optimization
    or a valid overall gain. The overall gain stays null."""
    report = {
        "baseline": {op: [] for op in bm.OPERATIONS},
        "candidate": {op: [] for op in bm.OPERATIONS},
    }
    # Clear worsens by 10% under the strict production clear; an unrelated op
    # improves by 90%. Only the clear comparison is the accepted headline.
    report["baseline"]["clear"] = [100.0] * 5
    report["candidate"]["clear"] = [110.0] * 5
    report["baseline"]["observe"] = [100.0] * 5
    report["candidate"]["observe"] = [10.0] * 5

    out = tmp_path / "policy.json"
    bm._finalize_report(report, str(out))
    data = json.loads(out.read_text(encoding="utf-8"))

    # Accepted headline metric computed from the clear operation only (+10%).
    assert data["clear_change_percent"] == 10.0
    # Overall gain intentionally null (never derived from unrelated diagnostics).
    assert data["overall_median_change_percent"] is None

    # Sanitized notes explain the policy without exposing device internals.
    assert "clear_change_note" in data
    assert "intentionally incorrect" in data["clear_change_note"]
    note_lc = data["clear_change_note"].lower()
    assert "not an optimization" in note_lc
    assert "not a valid overall" in note_lc



# --------------------------------------------------------------------------- #
# Task 5 Fix Round 4: _ensure_settings force-stop before launch (TDD)
# --------------------------------------------------------------------------- #
def test_ensure_settings_force_stops_then_launches_root():
    """Fix Round 4: _ensure_settings must force-stop com.android.settings BEFORE
    opening the Settings root, so a prior Settings activity (e.g. the search
    fragment) is not resumed when ``am start`` is issued against a stale task
    stack. Assert the force-stop command targets the Settings package and is
    ordered before the root-dashboard launch command."""
    dev = _RecordingDevice()
    bm._ensure_settings(dev)
    joined = _joined(dev)
    # force-stop present and targets the Settings package exactly.
    fs_calls = [
        c for c in dev.calls
        if c[1:3] == ["am", "force-stop"] and c[-1] == bm.SETTINGS_PKG
    ]
    assert fs_calls, joined
    # launch present and targets the root Settings action.
    launch_calls = [
        c for c in dev.calls
        if c[1:3] == ["am", "start"] and "android.settings.SETTINGS" in c[-1]
    ]
    assert launch_calls, joined
    # Order: force-stop strictly precedes the launch.
    fs_i = dev.calls.index(fs_calls[0])
    launch_i = dev.calls.index(launch_calls[0])
    assert fs_i < launch_i, joined
    # The force-stop changes no setting values; it only resets the task stack.
    assert bm.SETTINGS_PKG in fs_calls[0], joined


def test_settings_launch_target_excludes_force_stop(monkeypatch):
    """Fix Round 4: the timed target for settings_launch must NOT contain the
    force-stop reset. The force-stop is untimed setup run before the timer reads,
    so the target sample equals exactly the launch cost (1 adb call => 1.0 ms),
    independently of the (larger) untimed setup that preceded it."""
    _FAKE_CLOCK["t"] = 0.0
    dev = _ClockDevice()
    monkeypatch.setattr(bm.time, "perf_counter", lambda: _FAKE_CLOCK["t"])
    monkeypatch.setattr(bm.time, "sleep", lambda *a, **k: None)

    samples = bm._measure_phase(dev, "candidate")
    # 1 adb call (open_settings_section) => exactly 1.0 ms; if the force-stop were
    # inside the timed target the sample would instead be 2.0 ms (force-stop +
    # launch). Deterministic across all 5 reps proves the reset is excluded.
    assert samples["settings_launch"] == [1.0] * bm.SAMPLES, samples["settings_launch"]
    # Proof the timer wraps ONLY the target: every operation's samples are
    # deterministic (len(set) == 1).
    for op, vals in samples.items():
        assert len(set(vals)) == 1, f"{op} samples not deterministic: {vals}"


# --------------------------------------------------------------------------- #
# Task 5 Fix Round 3: _find_search_element OEM container fallback (TDD)
# --------------------------------------------------------------------------- #
class _ListDevice(AndroidPhoneDevice):
    """Returns a caller-supplied list of elements from ``dump_hierarchy``."""

    def __init__(self, elements):
        super().__init__()
        self.calls = []
        self._elements = list(elements)

    def _run_adb(self, args, timeout=5.0):
        self.calls.append(list(args))
        return ""

    def get_clipboard(self):
        return ""

    def dump_hierarchy(self):
        return self._elements


def test_find_search_element_huawei_android12_layout():
    """Observed Huawei Android 12 Settings search target:
    resource_id='com.android.settings:id/search_layout', bounds=(0,274,1080,442),
    is_clickable=False, is_focusable=False. No interactive search element exists,
    so the OEM container fallback must accept it and return its center for tap."""
    huawei = UIElement.create(
        1, "FrameLayout", (0, 274, 1080, 442),
        resource_id="com.android.settings:id/search_layout",
        is_clickable=False, is_focusable=False,
    )
    # A non-interactive decoy label that must NOT be the match.
    decoy = UIElement.create(
        2, "TextView", (0, 0, 80, 30),
        text="Search", is_clickable=False, is_focusable=False,
    )
    dev = _ListDevice([decoy, huawei])
    el = bm._find_search_element(dev)
    assert el is huawei, el
    # center of (0,274,1080,442) -> (540, 358)
    assert el.center == (540, 358), el.center


def test_find_search_element_accepts_search_segment_fallback():
    """Final resource_id segment exactly 'search' (no '_layout' suffix) is also
    an accepted non-interactive fallback container."""
    el = UIElement.create(
        1, "FrameLayout", (10, 10, 500, 120),
        resource_id="com.android.settings:id/search",
        is_clickable=False, is_focusable=False,
    )
    dev = _ListDevice([el])
    assert bm._find_search_element(dev) is el


def test_find_search_element_prefers_interactive_match():
    """When both an interactive search element and a non-interactive
    'search_layout' container are present, the interactive one must win."""
    interactive = UIElement.create(
        1, "EditText", (100, 100, 500, 200),
        text="Search", is_clickable=True, is_focusable=True,
        resource_id="com.android.settings/search",
    )
    layout = UIElement.create(
        2, "FrameLayout", (0, 274, 1080, 442),
        resource_id="com.android.settings:id/search_layout",
        is_clickable=False, is_focusable=False,
    )
    dev = _ListDevice([layout, interactive])
    el = bm._find_search_element(dev)
    assert el is interactive, el


def test_find_search_element_rejects_noninteractive_text_only():
    """Arbitrary non-interactive text containing 'search' (without a matching
    resource_id) must NOT be accepted by the fallback."""
    decoy = UIElement.create(
        1, "TextView", (0, 0, 120, 30),
        text="Search results", is_clickable=False, is_focusable=False,
    )
    dev = _ListDevice([decoy])
    assert bm._find_search_element(dev) is None


def test_find_search_element_rejects_zero_area_layout():
    """A 'search_layout' resource_id with non-positive area is not visible and
    must not be accepted."""
    zero = UIElement.create(
        1, "FrameLayout", (0, 0, 0, 0),
        resource_id="com.android.settings:id/search_layout",
        is_clickable=False, is_focusable=False,
    )
    dev = _ListDevice([zero])
    assert bm._find_search_element(dev) is None


# --------------------------------------------------------------------------- #
# Task 5 Fix Round 5: exact TEMP_TEXT detection in editable node text/value
# --------------------------------------------------------------------------- #
class _AssertionDevice(AndroidPhoneDevice):
    """Stand-in device for ``_collect_assertions``: the heavy setup/clear/tap/
    type calls are no-ops, and ``dump_hierarchy`` returns caller-supplied
    editable nodes so the TEMP_TEXT detection is exercised in isolation."""

    def __init__(self, editable_nodes):
        super().__init__()
        self.calls = []
        self._nodes = list(editable_nodes)

    def _run_adb(self, args, timeout=5.0):
        self.calls.append(list(args))
        return ""

    def get_clipboard(self):
        return ""

    def tap(self, *a, **k):
        pass

    def type_text(self, *a, **k):
        pass

    def get_foreground_app(self):
        return bm.SETTINGS_PKG

    def clear_text(self):
        pass

    def dump_hierarchy(self):
        return self._nodes



def _dummy_search_element():
    return UIElement.create(
        1, "EditText", (0, 0, 100, 50),
        text="Search", is_editable=True, is_clickable=True,
        resource_id="com.android.settings/search",
    )


def test_assertions_detect_exact_temp_text_not_hint(monkeypatch):
    """Fix Round 5 (assertion precision): ``temporary_text_visible`` must be true
    ONLY when the exact TEMP_TEXT appears in an editable node, and ``cleared``
    must be true ONLY when TEMP_TEXT is absent. Persistent hint/placeholder text
    (e.g. 'Search') must NOT be mistaken for the transient measurement text."""
    monkeypatch.setattr(bm, "_ensure_settings", lambda dev: None)
    monkeypatch.setattr(bm, "_find_search_element", lambda dev: _dummy_search_element())

    # Only hint text present (no TEMP_TEXT): visibility false, cleared true.
    dev = _AssertionDevice([
        UIElement.create(1, "EditText", (0, 0, 100, 50), text="Search", is_editable=True),
    ])
    res = bm._collect_assertions(dev)
    assert res["temporary_text_visible"] is False, res
    assert res["cleared"] is True, res

    # TEMP_TEXT present in text: visibility true, cleared false.
    dev2 = _AssertionDevice([
        UIElement.create(1, "EditText", (0, 0, 100, 50), text=bm.TEMP_TEXT, is_editable=True),
    ])
    res2 = bm._collect_assertions(dev2)
    assert res2["temporary_text_visible"] is True, res2
    assert res2["cleared"] is False, res2


def test_assertions_detect_temp_text_in_value(monkeypatch):
    """Fix Round 5: the editable node's ``value`` field (some firmwares expose
    the field content there rather than ``text``) must also be checked for the
    exact TEMP_TEXT."""
    monkeypatch.setattr(bm, "_ensure_settings", lambda dev: None)
    monkeypatch.setattr(bm, "_find_search_element", lambda dev: _dummy_search_element())

    dev = _AssertionDevice([
        UIElement.create(
            1, "EditText", (0, 0, 100, 50), text="", value=bm.TEMP_TEXT, is_editable=True
        ),
    ])
    res = bm._collect_assertions(dev)
    assert res["temporary_text_visible"] is True, res
    assert res["cleared"] is False, res


# --------------------------------------------------------------------------- #
# Task 5 Fix Round 5: hardware-result validation + stale blocker clearing
# --------------------------------------------------------------------------- #
class _SuccessDevice(AndroidPhoneDevice):
    """Minimal stand-in for ``main``. Inherits the real ``AndroidPhoneDevice``
    so module-level provenance fingerprinting (``AndroidPhoneDevice.clear_text``)
    still resolves to the production method, while overriding connect/summary."""

    def connect(self):
        return True

    def get_device_summary(self):
        return DeviceSummary(
            device_id="fake", platform="android", model="Fake",
            os_version="Android 12", screen_resolution=(1080, 2400),
            is_connected=True, active_package=bm.SETTINGS_PKG, capabilities=[],
        )


def _write_stale_report(path):
    stale = {
        "task": "android-text-correctness-and-performance-hardening",
        "operations": bm.OPERATIONS,
        "warmup_samples": bm.WARMUP,
        "measured_samples": bm.SAMPLES,
        "baseline": {op: [] for op in bm.OPERATIONS},
        "candidate": {op: [] for op in bm.OPERATIONS},
        "assertions": {},
        # Stale blocker from a prior partial run (must be cleared on success).
        "blocker": "hardware measurement interrupted: safe search field not found",
    }
    path.write_text(json.dumps(stale), encoding="utf-8")


def test_stale_blocker_cleared_after_successful_phase(monkeypatch, tmp_path):
    """Fix Round 5 (#3): on a successful measurement the stale blocker carried
    from a prior partial run must be set to None before the report is written,
    and raw samples must be retained."""
    out = tmp_path / "report.json"
    _write_stale_report(out)

    monkeypatch.setattr(bm, "_find_adb", lambda: "adb")
    monkeypatch.setattr(bm, "AndroidPhoneDevice", _SuccessDevice)
    good_samples = {op: [100.0] * bm.SAMPLES for op in bm.OPERATIONS}
    monkeypatch.setattr(bm, "_measure_phase", lambda dev, phase: dict(good_samples))
    passing = {
        "search_field_found": True,
        "foreground_package_settings": True,
        "temporary_text_visible": True,
        "cleared": True,
    }
    monkeypatch.setattr(bm, "_collect_assertions", lambda dev: dict(passing))
    monkeypatch.setattr(
        sys, "argv", ["bench", "--phase", "candidate", "--output", str(out)]
    )

    rc = bm.main()
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["blocker"] is None, data
    assert data.get("phase_successful") is True
    assert data.get("failed_assertions") == []
    # Raw captured samples are preserved, not deleted.
    assert data["candidate"] == good_samples


def test_hardware_validation_blocks_failed_assertions_preserves_samples(monkeypatch, tmp_path):
    """Fix Round 5 (#4): when a required assertion fails (here ``cleared`` is
    False), the phase must NOT be reported successful; a blocker and
    ``failed_assertions`` field must be written, and the raw captured samples
    must be preserved (never deleted)."""
    out = tmp_path / "report.json"
    _write_stale_report(out)

    monkeypatch.setattr(bm, "_find_adb", lambda: "adb")
    monkeypatch.setattr(bm, "AndroidPhoneDevice", _SuccessDevice)
    good_samples = {op: [100.0] * bm.SAMPLES for op in bm.OPERATIONS}
    monkeypatch.setattr(bm, "_measure_phase", lambda dev, phase: dict(good_samples))
    failing = {
        "search_field_found": True,
        "foreground_package_settings": True,
        "temporary_text_visible": True,
        "cleared": False,  # assertion failed
    }
    monkeypatch.setattr(bm, "_collect_assertions", lambda dev: dict(failing))
    monkeypatch.setattr(
        sys, "argv", ["bench", "--phase", "candidate", "--output", str(out)]
    )

    rc = bm.main()
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    # Not successful: blocker + failed_assertions written.
    assert data.get("phase_successful") is False
    assert data["blocker"] is not None, data
    assert "cleared" in data.get("failed_assertions", [])
    # Raw samples preserved (not deleted) despite the validation failure.
    assert data["candidate"] == good_samples


def test_required_assertions_constant_matches_assertion_fields():
    """The required-assertions set must match the fields ``_collect_assertions``
    actually produces, so validation never inspects a phantom key."""
    assert bm._REQUIRED_ASSERTIONS == [
        "search_field_found",
        "foreground_package_settings",
        "temporary_text_visible",
        "cleared",
    ]
