"""HTTP transport for the clinic MCP server: the remote deployment.

Same protocol, same :class:`~clinic_server.server.ClinicServer`, different
framing. Over stdio a message is one line on a pipe; over HTTP each message is
the body of a POST and the answer is the body of the response.

Built on the standard library on purpose: no web framework hides what travels
on the wire, which matters because this traffic is what we capture with
Wireshark.

Run locally:
    python -m clinic_server.http_server            # http://127.0.0.1:8000/mcp

In the cloud the platform provides the port:
    PORT=10000 python -m clinic_server.http_server
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp_host import jsonrpc

from .server import SERVER_INFO, ClinicServer
from .store import ClinicStore

#: Endpoint that accepts JSON-RPC messages.
MCP_PATH = "/mcp"

#: Shared instance; the store is cheap and thread safe enough for this project.
MCP = ClinicServer(ClinicStore())


class MCPRequestHandler(BaseHTTPRequestHandler):
    """Answers one JSON-RPC message per POST."""

    protocol_version = "HTTP/1.1"  # keep-alive, so one TCP connection is reused
    server_version = "clinic-mcp/1.0"

    def do_POST(self) -> None:
        if self.path.rstrip("/") != MCP_PATH:
            return self._send_json(404, {"error": f"unknown path '{self.path}'"})

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")

        try:
            message = jsonrpc.decode(raw)
        except jsonrpc.JsonRpcError as exc:
            return self._send_json(
                400, jsonrpc.build_error_response(None, exc.code, exc.message))

        response = MCP.handle(message)
        if response is None:
            # A notification expects no answer, so there is no body to send.
            return self._send_empty(202)
        self._send_json(200, response)

    def do_GET(self) -> None:
        """Health check, also what the cloud platform pings to keep us awake."""
        if self.path.rstrip("/") in ("", "/health"):
            return self._send_json(200, {
                "status": "ok",
                "server": SERVER_INFO,
                "transport": "http",
                "endpoint": MCP_PATH,
            })
        self._send_json(404, {"error": f"unknown path '{self.path}'"})

    # -- helpers ---------------------------------------------------------- #
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        """Log to stderr, one line per request, without the noisy default."""
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> int:
    # Cloud platforms hand the port over in an environment variable.
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), MCPRequestHandler)
    print(f"clinic MCP server listening on http://{host}:{port}{MCP_PATH}",
          file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
