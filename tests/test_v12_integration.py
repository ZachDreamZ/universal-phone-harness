"""Comprehensive integration tests for v1.2.0 upgrades (settle, tracer, crawler, sse)."""

import os
import json
import tempfile
import pytest
from click.testing import CliRunner

from phone_harness.harness import PhoneHarness
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.mcp_server import PhoneHarnessMCPServer
from phone_harness.cli import cli


def test_mcp_settle_tool():
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    server = PhoneHarnessMCPServer(harness=harness)

    res = server.handle_tool_call("phone_wait_for_settle", {"max_wait_seconds": 0.5})
    assert "isError" not in res
    data = json.loads(res["content"][0]["text"])
    assert data["status"] == "success"
    assert data["is_settled"] is True


def test_mcp_recording_tools_and_resource():
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    server = PhoneHarnessMCPServer(harness=harness)

    with tempfile.TemporaryDirectory() as tmpdir:
        trace_path = os.path.join(tmpdir, "mcp_session.trace.jsonl")

        # 1. Start recording
        res_start = server.handle_tool_call("phone_start_recording", {"output_path": trace_path})
        assert "isError" not in res_start

        # 2. Check recording status resource
        res_status = server.handle_resource_read("phone://recording/status")
        data_status = json.loads(res_status["contents"][0]["text"])
        assert data_status["is_recording"] is True
        assert data_status["output_path"] == trace_path

        # 3. Perform an action via MCP
        server.handle_tool_call("phone_tap", {"text": "Settings"})

        # 4. Stop recording
        res_stop = server.handle_tool_call("phone_stop_recording", {})
        assert "isError" not in res_stop
        data_stop = json.loads(res_stop["content"][0]["text"])
        assert data_stop["status"] == "recording_stopped"
        assert os.path.exists(trace_path)

        # 5. Reset device screen back to home and replay trace via MCP tool
        harness.device.current_screen = "home"
        res_replay = server.handle_tool_call("phone_replay_trace", {"trace_path": trace_path})
        assert "isError" not in res_replay
        data_replay = json.loads(res_replay["content"][0]["text"])
        assert data_replay["is_success"] is True
        assert data_replay["total_steps"] >= 1


def test_mcp_crawler_tool():
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    server = PhoneHarnessMCPServer(harness=harness)

    with tempfile.TemporaryDirectory() as tmpdir:
        res = server.handle_tool_call(
            "phone_crawl_app",
            {"step_budget": 4, "max_depth": 2, "output_directory": tmpdir},
        )
        assert "isError" not in res
        data = json.loads(res["content"][0]["text"])
        assert data["screens_discovered"] >= 1
        assert os.path.exists(data["report_markdown_path"])


def test_cli_v12_commands(monkeypatch):
    device = MockPhoneDevice()
    monkeypatch.setattr(PhoneHarness, "_auto_detect_device", lambda self: device)
    runner = CliRunner()

    # 1. Test settle CLI
    res_settle = runner.invoke(cli, ["settle", "--timeout", "0.5"])
    assert res_settle.exit_code == 0
    assert "Screen settled visually" in res_settle.output

    # 2. Test crawl CLI
    with tempfile.TemporaryDirectory() as tmpdir:
        res_crawl = runner.invoke(cli, ["crawl", "--budget", "4", "--output-dir", tmpdir])
        assert res_crawl.exit_code == 0
        assert "Crawl finished" in res_crawl.output
