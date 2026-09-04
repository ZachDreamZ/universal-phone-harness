"""
Comprehensive test suite for MCP upgrades in Phone Harness:
- phone_get_clipboard tool
- phone_save_screenshot tool (raw & Set-of-Marks)
- MCP resources/list and resources/read
- MCP prompts/list and prompts/get
- CLI commands: screenshot, clipboard, report
"""

import json
import os
import tempfile
from click.testing import CliRunner

from phone_harness.mcp_server import PhoneHarnessMCPServer
from phone_harness.harness import PhoneHarness
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.cli import cli


def test_mcp_tool_list_includes_new_tools():
    server = PhoneHarnessMCPServer()
    tools = server.get_tool_definitions()
    names = [t["name"] for t in tools]

    assert "phone_get_clipboard" in names
    assert "phone_save_screenshot" in names
    assert "phone_set_clipboard" in names


def test_mcp_clipboard_roundtrip():
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    server = PhoneHarnessMCPServer(harness=harness)

    # 1. Set clipboard via MCP
    res_set = server.handle_tool_call("phone_set_clipboard", {"text": "VERIFICATION_CODE_9482"})
    assert "isError" not in res_set
    data_set = json.loads(res_set["content"][0]["text"])
    assert data_set["status"] == "success"
    assert data_set["clipboard_set"] is True

    # 2. Get clipboard via MCP
    res_get = server.handle_tool_call("phone_get_clipboard", {})
    assert "isError" not in res_get
    data_get = json.loads(res_get["content"][0]["text"])
    assert data_get["status"] == "success"
    assert data_get["clipboard_text"] == "VERIFICATION_CODE_9482"


def test_mcp_save_screenshot():
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    server = PhoneHarnessMCPServer(harness=harness)

    with tempfile.TemporaryDirectory() as tmpdir:
        raw_path = os.path.join(tmpdir, "raw_screen.png")
        som_path = os.path.join(tmpdir, "som_screen.png")

        # Save raw screenshot
        res_raw = server.handle_tool_call("phone_save_screenshot", {"output_path": raw_path, "include_som": False})
        assert "isError" not in res_raw
        data_raw = json.loads(res_raw["content"][0]["text"])
        assert data_raw["status"] == "success"
        assert data_raw["saved_path"] == raw_path
        assert data_raw["width"] == 1080
        assert data_raw["height"] == 2400
        assert os.path.exists(raw_path)
        assert os.path.getsize(raw_path) > 0

        # Save SoM screenshot in a nested, non-existent directory
        nested_som_path = os.path.join(tmpdir, "nested", "sub", "som_screen.png")
        res_som = server.handle_tool_call("phone_save_screenshot", {"output_path": nested_som_path, "include_som": True})
        assert "isError" not in res_som
        data_som = json.loads(res_som["content"][0]["text"])
        assert data_som["status"] == "success"
        assert data_som["som_annotated"] is True
        assert os.path.exists(nested_som_path)
        assert os.path.getsize(nested_som_path) > 0


def test_mcp_resources_list_and_read():
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    server = PhoneHarnessMCPServer(harness=harness)

    # 1. resources/list
    resources = server.get_resource_definitions()
    uris = [r["uri"] for r in resources]
    assert "phone://device/status" in uris
    assert "phone://screen/dom" in uris
    assert "phone://diagnostics/efficiency" in uris

    # 2. resources/read phone://device/status
    res_status = server.handle_resource_read("phone://device/status")
    status_content = json.loads(res_status["contents"][0]["text"])
    assert status_content["platform"] == "mock"
    assert status_content["is_connected"] is True
    assert status_content["model"] == "Simulated Pixel 9 Pro"

    # 3. resources/read phone://screen/dom
    res_dom = server.handle_resource_read("phone://screen/dom")
    dom_text = res_dom["contents"][0]["text"]
    assert len(dom_text) > 0
    assert "[3] Button" in dom_text or "Settings" in dom_text

    # 4. resources/read phone://diagnostics/efficiency
    res_eff = server.handle_resource_read("phone://diagnostics/efficiency")
    eff_content = json.loads(res_eff["contents"][0]["text"])
    assert "steps_executed" in eff_content
    assert "efficiency_score" in eff_content


def test_mcp_prompts_list_and_get():
    server = PhoneHarnessMCPServer()

    # 1. prompts/list
    prompts = server.get_prompt_definitions()
    names = [p["name"] for p in prompts]
    assert "mobile_flow_qa" in names
    assert "extract_screen_data" in names
    assert "troubleshoot_screen" in names

    # 2. prompts/get mobile_flow_qa
    res_qa = server.handle_prompt_get(
        "mobile_flow_qa",
        {"target_flow": "Wi-Fi toggle", "expected_outcome": "Wi-Fi is disconnected"},
    )
    assert "Wi-Fi toggle" in res_qa["description"]
    assert len(res_qa["messages"]) >= 1
    assert "phone_observe" in res_qa["messages"][0]["content"]["text"]

    # 3. prompts/get extract_screen_data
    res_data = server.handle_prompt_get("extract_screen_data", {"data_schema": "{wifi: bool, bluetooth: bool}"})
    assert len(res_data["messages"]) >= 1
    assert "phone_observe" in res_data["messages"][0]["content"]["text"]

    # 4. prompts/get troubleshoot_screen
    res_trouble = server.handle_prompt_get("troubleshoot_screen", {})
    assert len(res_trouble["messages"]) >= 1
    assert "phone_health_check" in res_trouble["messages"][0]["content"]["text"]


def test_cli_screenshot_and_clipboard(monkeypatch):
    device = MockPhoneDevice()
    monkeypatch.setattr(PhoneHarness, "_auto_detect_device", lambda self: device)

    runner = CliRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        screen_file = os.path.join(tmpdir, "screen.png")

        # CLI screenshot
        result_screen = runner.invoke(cli, ["screenshot", screen_file, "--no-som"])
        assert result_screen.exit_code == 0
        assert "Saved Raw screenshot" in result_screen.output
        assert os.path.exists(screen_file)

        # CLI clipboard set
        result_clip_set = runner.invoke(cli, ["clipboard", "--set", "SECRET_TOKEN_4455"])
        assert result_clip_set.exit_code == 0
        assert "Set clipboard to: SECRET_TOKEN_4455" in result_clip_set.output

        # CLI clipboard get
        result_clip_get = runner.invoke(cli, ["clipboard"])
        assert result_clip_get.exit_code == 0
        assert "Clipboard content: SECRET_TOKEN_4455" in result_clip_get.output

        # CLI report
        result_report = runner.invoke(cli, ["report", "--optimal-steps", "4"])
        assert result_report.exit_code == 0
        assert "efficiency_score" in result_report.output
