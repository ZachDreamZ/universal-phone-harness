"""
Remote MCP Server with Server-Sent Events (SSE) & HTTP Transport.
Enables cloud AI agents (Modal, AWS, Fly.io, LangChain) to connect to phone harnesses
over HTTP/SSE with bearer token authentication without requiring local stdio.
"""

import json
import uuid
import queue
import threading
import hmac
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List

from phone_harness.mcp_server import PhoneHarnessMCPServer


class MCPSSEHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for MCP SSE stream and JSON-RPC message endpoints."""

    def log_message(self, format, *args):
        """Suppress default HTTP access logging to keep agent output clean."""
        pass

    def _is_authenticated(self) -> bool:
        """Validates Bearer token in Authorization header or query parameter using constant-time check."""
        expected_token = getattr(self.server, "auth_token", None)
        if not expected_token:
            return True

        # Check Authorization: Bearer <TOKEN>
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):].strip()
            if hmac.compare_digest(token, expected_token):
                return True

        # Check query parameter ?token=<TOKEN>
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        token_param = query.get("token", [None])[0]
        if token_param and hmac.compare_digest(token_param, expected_token):
            return True

        return False

    def _send_unauthorized(self) -> None:
        """Sends HTTP 401 Unauthorized response."""
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b'{"error": "Unauthorized", "message": "Valid bearer token required."}')

    def do_OPTIONS(self) -> None:
        """Handles CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self) -> None:
        """Handles health checks and Server-Sent Events stream initialization."""
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if self._is_authenticated():
                summary = self.server.mcp_server.harness.device.get_device_summary()
                payload = {
                    "status": "healthy",
                    "device_id": summary.device_id,
                    "platform": summary.platform,
                    "model": summary.model,
                }
            else:
                payload = {"status": "healthy"}
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        if parsed.path == "/sse":
            if not self._is_authenticated():
                self._send_unauthorized()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            session_id = str(uuid.uuid4())
            msg_queue = queue.Queue()
            with self.server.clients_lock:
                self.server.active_clients[session_id] = msg_queue

            # Send initial endpoint event per official MCP SSE specification
            init_path = f"/message?sessionId={session_id}"
            if getattr(self.server, "auth_token", None):
                init_path += f"&token={self.server.auth_token}"
            init_event = f"event: endpoint\ndata: {init_path}\n\n"
            self.wfile.write(init_event.encode("utf-8"))
            self.wfile.flush()

            try:
                while self.server.is_running:
                    try:
                        data = msg_queue.get(timeout=1.0)
                        event_payload = f"event: message\ndata: {data}\n\n"
                        self.wfile.write(event_payload.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        # Keep-alive heartbeat ping
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                with self.server.clients_lock:
                    self.server.active_clients.pop(session_id, None)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        """Handles incoming JSON-RPC 2.0 messages from MCP clients."""
        parsed = urlparse(self.path)

        if parsed.path == "/message":
            if not self._is_authenticated():
                self._send_unauthorized()
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                msg = json.loads(body.decode("utf-8"))
            except Exception as exc:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                jsonrpc_err = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(exc)}"},
                }
                self.wfile.write(json.dumps(jsonrpc_err).encode("utf-8"))
                return

            response = self.server.mcp_server.handle_jsonrpc_message(msg)

            self.send_response(200 if response is not None else 202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            if response is not None:
                encoded_resp = json.dumps(response)
                self.wfile.write(encoded_resp.encode("utf-8"))

                # Broadcast to SSE clients if sessionId present
                query = parse_qs(parsed.query)
                session_id = query.get("sessionId", [None])[0]
                if session_id:
                    with self.server.clients_lock:
                        target_queue = self.server.active_clients.get(session_id)
                    if target_queue is not None:
                        target_queue.put(encoded_resp)
            return

        self.send_response(404)
        self.end_headers()


class MCPSSEBridge:
    """Manages the lifecycle of an HTTP/SSE bridge for PhoneHarnessMCPServer."""

    def __init__(
        self,
        mcp_server: PhoneHarnessMCPServer,
        host: str = "127.0.0.1",
        port: int = 8080,
        auth_token: Optional[str] = None,
    ):
        self.mcp_server = mcp_server
        self.host = host
        self.port = port
        self.auth_token = auth_token
        self.http_server: Optional[ThreadingHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None

    @property
    def server_url(self) -> str:
        """Returns the base HTTP URL of the server."""
        return f"http://{self.host}:{self.port}"

    def start(self, background: bool = True) -> None:
        """Starts the HTTP and SSE server."""
        self.http_server = ThreadingHTTPServer((self.host, self.port), MCPSSEHandler)
        self.http_server.mcp_server = self.mcp_server
        self.http_server.auth_token = self.auth_token
        self.http_server.active_clients = {}
        self.http_server.clients_lock = threading.Lock()
        self.http_server.is_running = True

        if background:
            self.server_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
            self.server_thread.start()
        else:
            self.http_server.serve_forever()

    def stop(self) -> None:
        """Shuts down the server gracefully."""
        if self.http_server is not None:
            self.http_server.is_running = False
            self.http_server.shutdown()
            self.http_server.server_close()
            self.http_server = None
        if self.server_thread is not None:
            self.server_thread.join(timeout=2.0)
            self.server_thread = None
