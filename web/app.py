from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

from mcp_host import ChatEngine, InteractionLog
from mcp_host.server_registry import ServerRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CONFIG = os.path.join(ROOT, "config", "servers.json")
WORKSPACE = os.path.join(ROOT, "workspace")

MIME = {".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8"}

#: Filled in by main() before the server starts serving.
STATE: dict = {"engine": None, "registry": None, "log": None, "servers": {}}

#: One conversation, one engine: serialise turns so two tabs cannot interleave.
TURN_LOCK = threading.Lock()


class WebHandler(BaseHTTPRequestHandler):
    """Serves the page and a small JSON API on top of the engine."""

    protocol_version = "HTTP/1.1"
    server_version = "mcp-chatbot-web/1.0"

    # -- routing ---------------------------------------------------------- #
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send_file(os.path.join(STATIC, "index.html"))
        if path.startswith("/static/"):
            name = os.path.basename(path)  # basename blocks ../ traversal
            return self._send_file(os.path.join(STATIC, name))
        if path == "/api/state":
            return self._send_json(200, self._state())
        if path == "/api/log":
            # Polled while a turn is in flight, so the page can show MCP
            # traffic as it happens instead of only when the turn ends.
            since = int(self._query().get("since", 0))
            return self._send_json(200, {"log": self._log_since(since),
                                         "total": len(STATE["log"])})
        self._send_json(404, {"error": "not found"})

    def _query(self) -> dict:
        parts = self.path.split("?", 1)
        if len(parts) == 1:
            return {}
        return dict(p.split("=", 1) for p in parts[1].split("&") if "=" in p)

    def do_POST(self) -> None:
        if self.path == "/api/chat":
            return self._chat()
        if self.path == "/api/reset":
            STATE["engine"].reset()
            return self._send_json(200, {"ok": True, "turns": 0})
        self._send_json(404, {"error": "not found"})

    # -- endpoints -------------------------------------------------------- #
    def _chat(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            message = json.loads(self.rfile.read(length))["message"]
        except (ValueError, KeyError):
            return self._send_json(400, {"error": "expected {\"message\": \"...\"}"})

        engine, log = STATE["engine"], STATE["log"]
        calls: list[dict] = []
        before = len(log)

        with TURN_LOCK:
            try:
                reply = engine.send(
                    message,
                    on_tool=lambda name, args: calls.append(
                        {"name": name, "arguments": args}),
                )
            except Exception as exc:  # surface the failure in the page
                return self._send_json(200, {
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "tools": calls,
                    "log": self._log_since(before),
                })

        self._send_json(200, {
            "reply": reply,
            "tools": calls,
            "log": self._log_since(before),
            "turns": engine.turns,
        })

    def _state(self) -> dict:
        registry = STATE["registry"]
        return {
            "servers": STATE["servers"],
            "tools": [{"name": s["name"], "description": s["description"]}
                      for s in registry.tool_specs()],
            "model": STATE["engine"].model,
            "log": self._log_since(0),
        }

    @staticmethod
    def _log_since(start: int) -> list[dict]:
        """Log entries added after `start`, ready for the page to render."""
        return [{
            "time": e.timestamp,
            "server": e.server,
            "direction": e.direction,
            "kind": e.kind,
            "method": e.method,
            "id": e.message_id,
            "payload": e.payload,
        } for e in STATE["log"].entries()[start:]]

    # -- helpers ---------------------------------------------------------- #
    def _send_file(self, path: str) -> None:
        if not os.path.isfile(path):
            return self._send_json(404, {"error": "not found"})
        with open(path, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header("Content-Type",
                         MIME.get(os.path.splitext(path)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    load_dotenv()
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print("GEMINI_API_KEY is not set. See .env.example.", file=sys.stderr)
        return 1

    os.makedirs(WORKSPACE, exist_ok=True)
    log = InteractionLog()
    registry = ServerRegistry.from_config(CONFIG, log)
    print("Connecting to the MCP servers...", file=sys.stderr)
    servers = registry.connect()
    for name, status in servers.items():
        print(f"  {name}: {status}", file=sys.stderr)

    STATE.update(engine=ChatEngine(log, registry=registry), registry=registry,
                 log=log, servers=servers)

    port = int(os.getenv("WEB_PORT", "5000"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), WebHandler)
    print(f"\nOpen http://127.0.0.1:{port}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
