"""Unit tests for remote MCP HTTP/SSE transport bridge."""

import json
import socket
import urllib.request
import urllib.error
import pytest

from phone_harness.harness import PhoneHarness
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.mcp_server import PhoneHarnessMCPServer
from phone_harness.transport.sse_server import MCPSSEBridge


def get_free_port() -> int:
    """Finds an available local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def test_bridge():
    """Starts a local MCPSSEBridge on a free port and tears it down after the test."""
    port = get_free_port()
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    mcp_server = PhoneHarnessMCPServer(harness=harness)
    bridge = MCPSSEBridge(mcp_server=mcp_server, host="127.0.0.1", port=port)
    bridge.start(background=True)
    yield bridge
    bridge.stop()


def test_sse_server_health_check(test_bridge):
    url = f"{test_bridge.server_url}/health"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "healthy"
        assert data["platform"] == "mock"


def test_sse_server_jsonrpc_message(test_bridge):
    url = f"{test_bridge.server_url}/message"

    # Test tools/list
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "tools" in data["result"]
        tool_names = [t["name"] for t in data["result"]["tools"]]
        assert "phone_observe" in tool_names
        assert "phone_get_clipboard" in tool_names

    # Test initialize
    init_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}).encode("utf-8")
    init_req = urllib.request.Request(url, data=init_payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(init_req) as resp:
        assert resp.status == 200
        init_data = json.loads(resp.read().decode("utf-8"))
        assert init_data["result"]["protocolVersion"] == "2024-11-05"
        assert "resources" in init_data["result"]["capabilities"]


def test_sse_server_auth_token():
    port = get_free_port()
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    mcp_server = PhoneHarnessMCPServer(harness=harness)
    bridge = MCPSSEBridge(mcp_server=mcp_server, host="127.0.0.1", port=port, auth_token="test-secret-token")
    bridge.start(background=True)

    try:
        url = f"{bridge.server_url}/message"
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")

        # 1. Unauthenticated request: should fail with HTTP 401
        unauth_req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(unauth_req)
        assert exc_info.value.code == 401

        # 2. Authenticated request: should succeed with HTTP 200
        auth_req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-secret-token",
            },
        )
        with urllib.request.urlopen(auth_req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["id"] == 1

        # 3. Health check without token does not leak device metadata
        health_req = urllib.request.Request(f"{bridge.server_url}/health")
        with urllib.request.urlopen(health_req) as resp:
            assert resp.status == 200
            health_data = json.loads(resp.read().decode("utf-8"))
            assert health_data["status"] == "healthy"
            assert "device_id" not in health_data

    finally:
        bridge.stop()


def test_sse_concurrent_streaming_and_messaging():
    """Verifies that ThreadingHTTPServer serves POST /message concurrently while /sse is streaming."""
    import threading
    import time

    port = get_free_port()
    device = MockPhoneDevice()
    harness = PhoneHarness(device=device)
    mcp_server = PhoneHarnessMCPServer(harness=harness)
    bridge = MCPSSEBridge(mcp_server=mcp_server, host="127.0.0.1", port=port)
    bridge.start(background=True)

    sse_received = []
    stop_event = threading.Event()

    def stream_sse():
        try:
            req = urllib.request.Request(f"{bridge.server_url}/sse")
            with urllib.request.urlopen(req) as resp:
                for line in resp:
                    decoded = line.decode("utf-8")
                    sse_received.append(decoded)
                    if stop_event.is_set():
                        break
        except Exception:
            pass

    t = threading.Thread(target=stream_sse, daemon=True)
    t.start()

    try:
        # Give SSE time to connect
        time.sleep(0.3)
        assert len(sse_received) >= 1  # event: endpoint

        # Concurrent message POST should execute immediately without timing out
        msg_payload = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping"}).encode("utf-8")
        msg_req = urllib.request.Request(
            f"{bridge.server_url}/message",
            data=msg_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(msg_req, timeout=2.0) as resp:
            assert resp.status == 200
            resp_data = json.loads(resp.read().decode("utf-8"))
            assert resp_data["id"] == 99
    finally:
        stop_event.set()
        bridge.stop()
        t.join(timeout=1.0)


def test_sse_server_cors_options(test_bridge):
    """Verifies CORS OPTIONS preflight request handling."""
    req = urllib.request.Request(f"{test_bridge.server_url}/message", method="OPTIONS")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
        assert "OPTIONS" in resp.headers.get("Access-Control-Allow-Methods", "")
