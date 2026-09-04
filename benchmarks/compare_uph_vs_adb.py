"""
Empirical Benchmark: Universal Phone Harness (UPH) vs Raw ADB.

Measures real-world latency, payload size, token footprint, and actuation
overhead on connected physical Android hardware.

Non-destructive:
- Operates on live screen / launcher
- Ends on HOME key
- Output is written to JSON and printed as an ASCII table
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = "D:\\workspace\\universal-phone-harness"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from phone_harness.harness import PhoneHarness
from phone_harness.backends.android import AndroidPhoneDevice
from phone_harness.core.models import ActionRequest, ActionType, KeyCode
from phone_harness.perception.tree_simplifier import TreeSimplifier

SAMPLE_COUNT = 5


def find_adb_binary() -> str:
    """Locates adb executable via adbutils or PATH."""
    try:
        import adbutils
        return adbutils.adb_path()
    except Exception:
        pass
    which_adb = shutil.which("adb")
    if which_adb:
        return which_adb
    return "adb"


def run_raw_adb_command(adb_bin: str, serial: Optional[str], args: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Executes a raw ADB CLI subprocess command."""
    cmd = [adb_bin]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def measure_screencap(adb_bin: str, device: AndroidPhoneDevice) -> Tuple[float, float, int]:
    """
    Compares raw ADB screencap vs UPH capture_frame().
    Returns (median_adb_ms, median_uph_ms, raw_image_bytes).
    """
    adb_times: List[float] = []
    uph_times: List[float] = []
    image_bytes: int = 0

    # Warmup
    _ = run_raw_adb_command(adb_bin, device.serial, ["exec-out", "screencap", "-p"])
    _ = device.capture_frame()

    for _ in range(SAMPLE_COUNT):
        start_adb = time.perf_counter()
        proc = run_raw_adb_command(adb_bin, device.serial, ["exec-out", "screencap", "-p"])
        adb_times.append((time.perf_counter() - start_adb) * 1000.0)
        image_bytes = len(proc.stdout)

        start_uph = time.perf_counter()
        _ = device.capture_frame()
        uph_times.append((time.perf_counter() - start_uph) * 1000.0)

    median_adb = round(statistics.median(adb_times), 2)
    median_uph = round(statistics.median(uph_times), 2)
    return median_adb, median_uph, image_bytes


def measure_hierarchy_and_tokens(adb_bin: str, harness: PhoneHarness) -> Dict[str, Any]:
    """
    Compares raw ADB UIAutomator dump XML vs UPH Compact DOM extraction and token count.
    """
    raw_adb_times: List[float] = []
    uph_times: List[float] = []
    raw_xml_text = ""
    compact_dom_text = ""

    for _ in range(3):
        # Raw ADB uiautomator dump
        start_raw = time.perf_counter()
        _ = run_raw_adb_command(adb_bin, harness.device.serial, ["shell", "uiautomator", "dump", "/sdcard/uph_dump.xml"])
        read_proc = run_raw_adb_command(adb_bin, harness.device.serial, ["shell", "cat", "/sdcard/uph_dump.xml"])
        raw_adb_times.append((time.perf_counter() - start_raw) * 1000.0)
        raw_xml_text = read_proc.stdout.decode("utf-8", errors="ignore")

        # UPH observe & tree simplify
        start_uph = time.perf_counter()
        state = harness.observe(filter_interactive_only=True)
        uph_times.append((time.perf_counter() - start_uph) * 1000.0)
        compact_dom_text = state.compact_dom

    # Cleanup temp XML on device
    _ = run_raw_adb_command(adb_bin, harness.device.serial, ["shell", "rm", "-f", "/sdcard/uph_dump.xml"])

    # Approximate token count (1 token ~= 4 characters for structured DOM)
    raw_xml_chars = len(raw_xml_text)
    raw_tokens_est = max(1, raw_xml_chars // 4)

    compact_chars = len(compact_dom_text)
    compact_tokens_est = max(1, compact_chars // 4)

    token_savings_pct = round(((raw_tokens_est - compact_tokens_est) / max(1, raw_tokens_est)) * 100.0, 1)

    return {
        "raw_adb_dump_median_ms": round(statistics.median(raw_adb_times), 2),
        "uph_observe_median_ms": round(statistics.median(uph_times), 2),
        "raw_xml_bytes": raw_xml_chars,
        "raw_xml_tokens_est": raw_tokens_est,
        "uph_compact_dom_bytes": compact_chars,
        "uph_compact_dom_tokens_est": compact_tokens_est,
        "token_reduction_pct": token_savings_pct,
    }


def measure_navigation_key(adb_bin: str, harness: PhoneHarness) -> Tuple[float, float]:
    """
    Compares raw ADB keyevent vs UPH device.press_key(BACK).
    """
    adb_times: List[float] = []
    uph_times: List[float] = []

    for _ in range(SAMPLE_COUNT):
        start_adb = time.perf_counter()
        _ = run_raw_adb_command(adb_bin, harness.device.serial, ["shell", "input", "keyevent", "KEYCODE_BACK"])
        adb_times.append((time.perf_counter() - start_adb) * 1000.0)

        start_uph = time.perf_counter()
        harness.device.press_key(KeyCode.BACK)
        uph_times.append((time.perf_counter() - start_uph) * 1000.0)

    # Return home at the end
    harness.device.press_key(KeyCode.HOME)

    return round(statistics.median(adb_times), 2), round(statistics.median(uph_times), 2)


def run_full_benchmark(output_path: Optional[str] = None) -> Dict[str, Any]:
    """Runs the complete empirical benchmark suite and formats results."""
    adb_bin = find_adb_binary()
    device = AndroidPhoneDevice()
    summary = device.get_device_summary()
    harness = PhoneHarness(device=device)

    print(f"[*] Benchmarking Device: {summary.model} ({summary.platform.upper()} {summary.os_version})")
    print(f"[*] Screen Resolution: {summary.screen_resolution[0]}x{summary.screen_resolution[1]}")
    print(f"[*] ADB Binary: {adb_bin}\n")

    # 1. Screen Capture
    print("[1/3] Measuring Screen Capture Latency (5 samples)...")
    adb_screencap_ms, uph_screencap_ms, img_bytes = measure_screencap(adb_bin, device)

    # 2. Hierarchy & Tokens
    print("[2/3] Measuring UI Hierarchy Extraction & Token Footprint (3 samples)...")
    hierarchy_metrics = measure_hierarchy_and_tokens(adb_bin, harness)

    # 3. Navigation Key Actuation
    print("[3/3] Measuring Navigation Key Actuation Latency (5 samples)...")
    adb_key_ms, uph_key_ms = measure_navigation_key(adb_bin, harness)

    results: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "device": {
            "model": summary.model,
            "platform": summary.platform,
            "os_version": summary.os_version,
            "resolution": f"{summary.screen_resolution[0]}x{summary.screen_resolution[1]}",
        },
        "screencap": {
            "raw_adb_median_ms": adb_screencap_ms,
            "uph_median_ms": uph_screencap_ms,
            "frame_size_bytes": img_bytes,
        },
        "hierarchy_and_tokens": hierarchy_metrics,
        "navigation_key": {
            "raw_adb_key_median_ms": adb_key_ms,
            "uph_key_median_ms": uph_key_ms,
        },
        "qualitative_comparison": {
            "out_of_sync_protection": {
                "raw_adb": "None (taps stale coordinates blindly if screen shifted)",
                "uph": "observation_generation race-condition token guard",
            },
            "llm_token_efficiency": {
                "raw_adb": f"{hierarchy_metrics['raw_xml_tokens_est']} tokens (raw XML bloat)",
                "uph": f"{hierarchy_metrics['uph_compact_dom_tokens_est']} tokens ({hierarchy_metrics['token_reduction_pct']}% reduction)",
            },
            "layout_shift_resilience": {
                "raw_adb": "None (hardcoded pixel coordinates fail across screen sizes)",
                "uph": "Self-healing 3-tier fallback (ID -> Text -> Spatial Proximity)",
            },
            "transport_protocol": {
                "raw_adb": "Local USB/TCP socket pipe only",
                "uph": "Official MCP standard (stdio + remote HTTP/SSE streaming)",
            },
            "visual_grounding": {
                "raw_adb": "None (requires custom external vision scripts)",
                "uph": "Built-in Set-of-Marks (SoM) bounding visual annotator",
            },
            "animation_settle": {
                "raw_adb": "Arbitrary time.sleep() pauses",
                "uph": "Perceptual frame differencing (PerceptualSettleDetector)",
            },
        },
    }

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\n[OK] Benchmark metrics saved to: {output_path}")

    return results


def main():
    out_file = "D:\\workspace\\universal-phone-harness\\artifacts\\adb_vs_uph_benchmark.json"
    results = run_full_benchmark(output_path=out_file)
    print("\n" + "=" * 76)
    print("      UNIVERSAL PHONE HARNESS (UPH) vs RAW ADB BENCHMARK REPORT      ")
    print("=" * 76)
    print(f"Device: {results['device']['model']} | {results['device']['os_version']} | {results['device']['resolution']}")
    print("-" * 76)
    print(f"{'Benchmark Metric':<35} | {'Raw ADB':<18} | {'UPH (v1.2.0)':<18}")
    print("-" * 76)
    sc = results["screencap"]
    print(f"{'Screen Capture Latency':<35} | {sc['raw_adb_median_ms']:>14} ms | {sc['uph_median_ms']:>14} ms")

    ht = results["hierarchy_and_tokens"]
    print(f"{'DOM Dump & Parse Latency':<35} | {ht['raw_adb_dump_median_ms']:>14} ms | {ht['uph_observe_median_ms']:>14} ms")
    print(f"{'Payload Size':<35} | {ht['raw_xml_bytes']:>14} B  | {ht['uph_compact_dom_bytes']:>14} B ")
    print(f"{'LLM Token Footprint (est)':<35} | {ht['raw_xml_tokens_est']:>14} tok| {ht['uph_compact_dom_tokens_est']:>14} tok")
    print(f"{'Token Savings / Efficiency':<35} | {'0.0%':>18} | {ht['token_reduction_pct']:>17}%")

    nk = results["navigation_key"]
    print(f"{'Key Event Latency':<35} | {nk['raw_adb_key_median_ms']:>14} ms | {nk['uph_key_median_ms']:>14} ms")
    print("-" * 76)
    print("\n--- ARCHITECTURAL & SAFETY ADVANTAGES ---")
    for capability, data in results["qualitative_comparison"].items():
        cap_title = capability.replace("_", " ").title()
        print(f"\n[*] {cap_title}:")
        print(f"    - Raw ADB : {data['raw_adb']}")
        print(f"    - UPH     : {data['uph']}")
    print("\n" + "=" * 76)


if __name__ == "__main__":
    main()
