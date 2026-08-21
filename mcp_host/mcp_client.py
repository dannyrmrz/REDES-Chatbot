"""MCP client: one connection to one MCP server, implemented by hand.
"""

from __future__ import annotations

from typing import Any

from . import jsonrpc
from .interaction_log import RECEIVED, SENT, InteractionLog
from .transport import Transport

#Protocol revision this host implements.  If the server only speaks an older one it answers `initialize` with its own version, which we simply record.
PROTOCOL_VERSION = "2025-06-18"

#Identifies this host to the server (shown in server logs).
CLIENT_INFO = {"name": "redes-mcp-host", "version": "0.1.0"}


class MCPClient:
    """Drives the MCP session with a single server over any transport."""

    def __init__(self, name: str, transport: Transport, log: InteractionLog,
                 timeout: float = 60.0) -> None:
        self.name = name
        self.transport = transport
        self.log = log
        self.timeout = timeout
        self._ids = jsonrpc.IdGenerator()
        self.server_info: dict = {}
        self.capabilities: dict = {}
        self.protocol_version: str | None = None
        self.tools: list[dict] = []

    #session
    def connect(self) -> list[dict]:
        """Run the handshake and return the tools the server exposes."""
        self.transport.start()
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            # We expose no client features (no roots, no sampling), so the
            # server knows it must not call back into us.
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self.protocol_version = result.get("protocolVersion")
        self.server_info = result.get("serverInfo", {})
        self.capabilities = result.get("capabilities", {})
        # Mandatory: the server may not accept other requests until it arrives.
        self.notify("notifications/initialized")
        self.tools = self.list_tools()
        return self.tools

    def close(self) -> None:
        self.transport.close()

    #MCP methods
    def list_tools(self) -> list[dict]:
        """Fetch every tool, following the ``nextCursor`` pagination."""
        tools: list[dict] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self.request("tools/list", params)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, tool_name: str, arguments: dict | None = None) -> dict:
        #Invoke a tool and return the raw MCP result.
        return self.request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })

    @staticmethod
    def result_to_text(result: dict) -> str:
        """Flatten an MCP tool result into text to feed back to the model."""
        chunks = []
        for block in result.get("content", []):
            if block.get("type") == "text":
                chunks.append(block.get("text", ""))
            else:  # images, audio, resource links: describe instead of embed
                chunks.append(f"[{block.get('type', 'unknown')} content]")
        text = "\n".join(c for c in chunks if c) or "(the tool returned no content)"
        return f"ERROR: {text}" if result.get("isError") else text

    #JSON-RPC plumbing
    def request(self, method: str, params: dict | None = None) -> Any:
        """Send a request and block until the response with the same id."""
        request_id = self._ids.next()
        self._send(jsonrpc.build_request(request_id, method, params))
        while True:
            message = self._receive()
            kind = jsonrpc.classify(message)
            if kind in (jsonrpc.KIND_RESPONSE, jsonrpc.KIND_ERROR):
                if message.get("id") == request_id:
                    return jsonrpc.extract_result(message)
                continue  # a stale answer: ignore it and keep waiting
            # Anything else arriving mid-call is server-initiated traffic.
            self._handle_incoming(message, kind)

    def notify(self, method: str, params: dict | None = None) -> None:
        """Send a notification; by definition there is nothing to wait for."""
        self._send(jsonrpc.build_notification(method, params))

    def _handle_incoming(self, message: dict, kind: str) -> None:
        """Answer server-initiated traffic so the server never blocks on us."""
        if kind == jsonrpc.KIND_NOTIFICATION:
            return  # progress / log notifications: recorded, nothing to answer
        if message.get("method") == "ping":
            self._send(jsonrpc.build_response(message["id"], {}))
            return
        # We advertised no capabilities, so any other call is out of contract.
        self._send(jsonrpc.build_error_response(
            message["id"], jsonrpc.METHOD_NOT_FOUND,
            f"method '{message.get('method')}' is not supported by this host"))

    def _send(self, message: dict) -> None:
        self.log.record(self.name, SENT, message)
        self.transport.send(message)

    def _receive(self) -> dict:
        message = self.transport.receive(self.timeout)
        self.log.record(self.name, RECEIVED, message)
        return message
