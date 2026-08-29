# Universal Phone Harness

[![CI](https://github.com/ZachDreamZ/universal-phone-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/ZachDreamZ/universal-phone-harness/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ZachDreamZ/universal-phone-harness/actions/workflows/codeql.yml/badge.svg)](https://github.com/ZachDreamZ/universal-phone-harness/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](pyproject.toml)

Universal Phone Harness is a Python MCP server, CLI, and library for controlling Android and iOS devices from AI agents. It turns accessibility hierarchies into bounded indexed DOMs, grounds actions to observed generations, verifies postconditions, and blocks unconfirmed destructive targets.

Android uses ADB and UIAutomator. The iOS backend uses WebDriverAgent. A deterministic mock backend supports local development and CI.

> [!WARNING]
> This project can control a real phone. Review agent actions, keep destructive-action confirmation enabled, and never expose the MCP server to untrusted clients.

## Features

- 16 MCP tools for observation, taps, typing, gestures, navigation, waits, assertions, dialogs, clipboard access, and health checks
- Indexed UI elements with stale-observation rejection
- Accessibility-first grounding with local OCR fallback for canvas and WebView surfaces
- Explicit post-action assertions and one re-grounded retry
- Destructive-action gates, step budgets, loop detection, and PII masking
- Hard output budgets: 600 estimated tokens for observations and 200 for post-action DOMs by default
- Compact JSON and native MCP image content
- Android, WebDriverAgent-based iOS, and deterministic mock backends
- CLI and Python APIs for direct automation

## Measured results

Tests on a Huawei JLN-LX1 running Android 12 used one warm-up and five measured samples:

| Operation | Baseline median | Current median | Change |
|---|---:|---:|---:|
| Text clear | 321.183 ms | 73.176 ms | 77.22% faster |
| Type 32 characters | 892.845 ms | 873.101 ms | 2.21% faster |
| Screen hierarchy observation | 2621.626 ms | 2615.850 ms | 0.22% faster |

The clear baseline reproduces the earlier incomplete delete sequence. The comparison measures the cost and speed of the corrected implementation, not an overall system speedup. Full samples and assertions live in [`artifacts/android-hardening-benchmark.json`](artifacts/android-hardening-benchmark.json).

Live MCP measurement reduced one Settings post-action DOM from 2,313 to 751 characters, a 67.53% reduction. Image requests now use MCP image blocks instead of embedding base64 inside JSON text.

## Requirements

- Python 3.10 or newer
- Android: USB debugging or wireless ADB authorization
- iOS: a reachable WebDriverAgent server
- Optional OCR: `rapidocr-onnxruntime` and OpenCV

## Installation

```bash
git clone https://github.com/ZachDreamZ/universal-phone-harness.git
cd universal-phone-harness
python -m pip install -e ".[dev]"
```

Install OCR support when needed:

```bash
python -m pip install -e ".[ocr]"
```

## Android setup

1. Enable Developer options and USB debugging.
2. Connect and authorize the phone.
3. Confirm ADB sees it:

```bash
adb devices -l
phone-harness doctor
```

The default backend is Android and fails closed. It will not silently substitute the mock backend when no device is connected.

## MCP setup

After installation, register this stdio server in any MCP client:

```json
{
  "mcpServers": {
    "phone-harness": {
      "command": "python",
      "args": ["-m", "phone_harness.mcp_server"]
    }
  }
}
```

Call `phone_observe` before indexed actions. Pass its `observation_generation` with the index:

```json
{
  "index": 3,
  "observation_generation": 12
}
```

Text and coordinate selectors do not require a generation. Typed text is not echoed in MCP responses.

## CLI

```bash
phone-harness doctor
phone-harness observe
phone-harness tap Settings
phone-harness settings wifi
phone-harness swipe up --distance medium
phone-harness press HOME
phone-harness wait --text Connected --timeout 5000
phone-harness serve
```

## Python API

```python
from phone_harness import ActionRequest, ActionType, PhoneHarness, VerificationSpec

harness = PhoneHarness()
state = harness.observe()

settings = next(element for element in state.elements if element.text == "Settings")
result = harness.execute_action(
    ActionRequest(
        action=ActionType.TAP,
        target_index=settings.id,
        observation_generation=state.generation,
        verify=VerificationSpec(assert_app_package="com.android.settings"),
    )
)

print(result.new_state.current_app_package)
```

Use the mock backend explicitly in tests:

```python
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.harness import PhoneHarness

harness = PhoneHarness(device=MockPhoneDevice())
```

Other explicit backend choices:

```python
from phone_harness.core.config import HarnessConfig

android_config = HarnessConfig(default_platform="android")
ios_config = HarnessConfig(default_platform="ios")
mock_config = HarnessConfig(default_platform="mock")
```

`allow_mock_fallback=True` is opt-in because silent fallback can make an agent believe it controls a real device when it does not.

## MCP tools

| Tool | Purpose |
|---|---|
| `phone_observe` | Return indexed DOM and optional native MCP images |
| `phone_tap` | Tap by index, text, or coordinates |
| `phone_type` | Type into a focused or indexed field |
| `phone_swipe` | Swipe directionally or by coordinates |
| `phone_press_key` | Press system keys such as HOME and BACK |
| `phone_open_app` | Launch an Android package identifier |
| `phone_assert_state` | Verify text and foreground-package conditions |
| `phone_wait_for` | Poll locally until conditions pass or time out |
| `phone_open_url` | Open a validated HTTP or HTTPS URL |
| `phone_open_settings` | Open a system Settings section |
| `phone_set_clipboard` | Set and verify clipboard content |
| `phone_dismiss_dialog` | Respond to detected dialogs; defaults to deny |
| `phone_long_press` | Long-press a target |
| `phone_double_tap` | Double-tap a target |
| `phone_efficiency_report` | Return step and latency metrics |
| `phone_health_check` | Return backend and device health |

## Architecture

```text
phone_harness/
  backends/        Android, iOS, and mock device adapters
  core/            Models, configuration, device interface, exceptions
  engine/          Verification, safety, dialogs, sessions, trajectories
  perception/      Tree compaction, OCR matching, visual detection, SoM
  plugins/         Example MCP client configurations
  cli.py           Command-line interface
  harness.py       Action and observation orchestration
  mcp_server.py    MCP JSON-RPC stdio server
tests/             Unit and integration tests
benchmarks/        Reproducible connected-device benchmark
```

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m compileall -q phone_harness benchmarks
python -m build
python -m twine check dist/*
```

The test suite contains 108 tests and does not require connected hardware. `verify_all.py` adds optional live-device checks.

## Security

Report vulnerabilities privately. See [`SECURITY.md`](SECURITY.md). Do not include credentials, phone contents, screenshots, or private device identifiers in reports.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Contributions require tests and must pass CI.

## License

MIT. See [`LICENSE`](LICENSE).
