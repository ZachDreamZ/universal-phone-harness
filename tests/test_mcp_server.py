"""
Tests for MCP Server tool dispatching and integration with PhoneHarness.
"""

import json
from phone_harness.mcp_server import PhoneHarnessMCPServer
from phone_harness.harness import PhoneHarness
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.core.config import HarnessConfig


def test_mcp_tool_list():
    server = PhoneHarnessMCPServer()
    tools = server.get_tool_definitions()
    names = [t["name"] for t in tools]

    assert "phone_observe" in names
    assert "phone_tap" in names
    assert "phone_type" in names
    assert "phone_swipe" in names
    assert "phone_press_key" in names
    assert "phone_open_app" in names
    assert "phone_assert_state" in names
    assert "phone_health_check" in names


def test_mcp_observe_and_tap():
    mock_dev = MockPhoneDevice()
    harness = PhoneHarness(device=mock_dev)
    server = PhoneHarnessMCPServer(harness=harness)

    # 1. Observe screen
    res_obs = server.handle_tool_call("phone_observe", {})
    assert "content" in res_obs
    data = json.loads(res_obs["content"][0]["text"])
    assert data["foreground_app"] == "com.google.android.apps.nexuslauncher"
    assert "compact_dom" in data
    assert data["observation_generation"] >= 1
    assert "[3] Button \"Settings\"" in data["compact_dom"]

    # 2. Tap Settings button (index 3) grounded on the observed generation
    res_tap = server.handle_tool_call(
        "phone_tap",
        {"index": 3, "observation_generation": data["observation_generation"]},
    )
    assert "isError" not in res_tap
    tap_data = json.loads(res_tap["content"][0]["text"])
    assert tap_data["status"] == "success"
    assert tap_data["foreground_app"] == "com.android.settings"
    assert tap_data["observation_generation"] >= 1

    # 3. Assert State
    res_assert = server.handle_tool_call(
        "phone_assert_state",
        {"assert_app_package": "com.android.settings", "assert_text_present": ["Wi-Fi"]},
    )
    assert "isError" not in res_assert


def test_mcp_observe_returns_generation():
    server = PhoneHarnessMCPServer(harness=PhoneHarness(device=MockPhoneDevice()))
    response = server.handle_tool_call("phone_observe", {})
    payload = json.loads(response["content"][0]["text"])
    assert payload["observation_generation"] >= 1


def test_mcp_indexed_tap_uses_observation_generation():
    server = PhoneHarnessMCPServer(harness=PhoneHarness(device=MockPhoneDevice()))
    observed = json.loads(server.handle_tool_call("phone_observe", {})["content"][0]["text"])
    response = server.handle_tool_call(
        "phone_tap",
        {"index": 3, "observation_generation": observed["observation_generation"]},
    )
    assert "isError" not in response


def test_mcp_indexed_tap_without_generation_rejected(monkeypatch):
    """Indexed actions require observation_generation. Omitting it must return a
    structured MCP error and must NOT actuate the device."""
    harness = PhoneHarness(device=MockPhoneDevice())
    server = PhoneHarnessMCPServer(harness=harness)

    # Ensure the harness is never reached if an actuation were attempted.
    monkeypatch.setattr(harness, "execute_action", lambda req: (_ for _ in ()).throw(AssertionError("actuated")))

    response = server.handle_tool_call("phone_tap", {"index": 3})
    assert response["isError"] is True
    payload = json.loads(response["content"][0]["text"])
    assert set(payload.keys()) == {"error", "message"}
    assert payload["error"] == "MissingObservationGeneration"
    # Device was never actuated: still on launcher, no observation cached.
    assert harness.last_state is None
    assert harness.device.current_package == "com.google.android.apps.nexuslauncher"


def test_mcp_text_or_coordinate_tap_compatible_without_generation(monkeypatch):
    """Text/coordinate selectors remain compatible without observation_generation."""
    harness = PhoneHarness(device=MockPhoneDevice())
    server = PhoneHarnessMCPServer(harness=harness)

    # Coordinate tap (no index, no generation) should reach the harness.
    response = server.handle_tool_call("phone_tap", {"x": 200, "y": 900})
    assert "isError" not in response
    # Text tap (no index, no generation) should reach the harness.
    response = server.handle_tool_call("phone_tap", {"text": "Settings"})
    assert "isError" not in response


def test_mcp_stale_observation_returns_structured_error(monkeypatch):
    """An indexed action pinned to a stale generation must return a structured
    StaleObservationError carrying expected_generation and current_generation,
    and must NOT be downgraded to the generic InternalHarnessError."""
    harness = PhoneHarness(device=MockPhoneDevice())
    server = PhoneHarnessMCPServer(harness=harness)

    observed = json.loads(server.handle_tool_call("phone_observe", {})["content"][0]["text"])
    gen = observed["observation_generation"]

    # Pin the action to a generation that no longer matches live state.
    response = server.handle_tool_call(
        "phone_tap", {"index": 3, "observation_generation": gen + 1}
    )
    assert response["isError"] is True
    payload = json.loads(response["content"][0]["text"])

    assert payload["error"] == "StaleObservationError"
    assert payload["expected_generation"] == gen + 1
    assert payload["current_generation"] == gen
    assert "message" in payload
    assert "suggestions" in payload
    # Must not collapse into the generic catch-all.
    assert payload["error"] != "InternalHarnessError"


def test_mcp_internal_error_omits_exception_details(monkeypatch):
    server = PhoneHarnessMCPServer(harness=PhoneHarness(device=MockPhoneDevice()))
    monkeypatch.setattr(server.harness, "observe", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret detail")))
    response = server.handle_tool_call("phone_observe", {})
    payload = json.loads(response["content"][0]["text"])
    assert response["isError"] is True
    assert payload == {
        "error": "InternalHarnessError",
        "message": "Internal phone harness error.",
    }


def test_mcp_internal_error_stderr_redacted(capsys, monkeypatch):
    """Generic handler must never leak the exception message (which may carry
    typed text, clipboard, secrets, or DOM data) to stderr. The diagnostic may
    only contain the exception class and stack frame locations."""
    secret = "TASK4_LEAK_SECRET_8c4F2a1B9d"
    leak_msg = f"confidential payload {secret} and dom snapshot <node text='secret'>"
    server = PhoneHarnessMCPServer(harness=PhoneHarness(device=MockPhoneDevice()))
    monkeypatch.setattr(
        server.harness,
        "observe",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError(leak_msg)),
    )

    response = server.handle_tool_call("phone_observe", {})

    captured = capsys.readouterr()
    err = captured.err
    # Exception class and diagnostic marker must remain for operator debugging.
    assert "[MCP Internal Error]" in err
    assert "RuntimeError" in err
    assert "at " in err and ".py:" in err  # stack frame locations present
    # The secret/runtime values must NOT appear in stderr.
    assert secret not in err
    assert "confidential payload" not in err
    assert "dom snapshot" not in err
    assert "secret" not in err
    # Tool args must not be printed to stderr.
    assert "phone_observe" not in err
    # Client response also omits exception details.
    payload = json.loads(response["content"][0]["text"])
    assert response["isError"] is True
    assert payload == {
        "error": "InternalHarnessError",
        "message": "Internal phone harness error.",
    }
    assert secret not in response["content"][0]["text"]


def test_mcp_schema_uses_safe_dialog_default_and_exposes_tab_key():
    server = PhoneHarnessMCPServer(harness=PhoneHarness(device=MockPhoneDevice()))
    definitions = {tool["name"]: tool for tool in server.get_tool_definitions()}

    dialog_action = definitions["phone_dismiss_dialog"]["inputSchema"]["properties"]["action"]
    key_values = definitions["phone_press_key"]["inputSchema"]["properties"]["key"]["enum"]
    assert dialog_action["default"] == "deny"
    assert "TAB" in key_values


def test_mcp_json_payloads_use_compact_encoding():
    server = PhoneHarnessMCPServer(harness=PhoneHarness(device=MockPhoneDevice()))
    response = server.handle_tool_call("phone_observe", {})
    text = response["content"][0]["text"]

    assert "\n" not in text
    assert '": "' not in text
    assert json.loads(text)["foreground_app"] == "com.google.android.apps.nexuslauncher"


def test_mcp_observe_returns_native_image_content_without_base64_in_json():
    server = PhoneHarnessMCPServer(harness=PhoneHarness(device=MockPhoneDevice()))
    response = server.handle_tool_call(
        "phone_observe",
        {"include_raw_image": True, "include_som_image": True},
    )

    metadata = json.loads(response["content"][0]["text"])
    assert "raw_image_base64" not in metadata
    assert "som_image_base64" not in metadata

    images = [content for content in response["content"] if content["type"] == "image"]
    assert len(images) == 2
    assert {image["mimeType"] for image in images} == {"image/jpeg"}
    assert all(image["data"] for image in images)


def test_mcp_action_dom_uses_smaller_response_budget():
    config = HarnessConfig(default_platform="mock", max_tokens_action_dom=10)
    server = PhoneHarnessMCPServer(
        harness=PhoneHarness(device=MockPhoneDevice(), config=config)
    )
    observed = json.loads(server.handle_tool_call("phone_observe", {})["content"][0]["text"])
    response = server.handle_tool_call(
        "phone_tap",
        {"index": 3, "observation_generation": observed["observation_generation"]},
    )
    payload = json.loads(response["content"][0]["text"])

    assert len(payload["updated_compact_dom"]) <= 40


def test_mcp_type_response_does_not_echo_entered_text():
    device = MockPhoneDevice()
    device.current_screen = "login"
    device.current_package = "com.example.auth"
    device.history = ["home", "login"]
    server = PhoneHarnessMCPServer(harness=PhoneHarness(device=device))
    observed = json.loads(server.handle_tool_call("phone_observe", {})["content"][0]["text"])
    secret = "DO_NOT_ECHO_THIS_SECRET"

    response = server.handle_tool_call(
        "phone_type",
        {
            "index": 3,
            "observation_generation": observed["observation_generation"],
            "text": secret,
        },
    )
    response_text = response["content"][0]["text"]
    payload = json.loads(response_text)

    assert secret not in response_text
    assert "text_entered" not in payload
