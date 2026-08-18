"""MCP host: a hand-written Model Context Protocol implementation.

Layers, from the wire upwards:

* :mod:`mcp_host.jsonrpc`         -- JSON-RPC 2.0 messages
* :mod:`mcp_host.transport`       -- framing (stdio today, HTTP later)
* :mod:`mcp_host.mcp_client`      -- the MCP handshake and tool calls
* :mod:`mcp_host.interaction_log` -- transcript of everything exchanged
"""

from .interaction_log import RECEIVED, SENT, InteractionLog, LogEntry
from .jsonrpc import JsonRpcError
from .mcp_client import MCPClient
from .transport import StdioTransport, Transport, TransportError

__all__ = [
    "InteractionLog", "LogEntry", "SENT", "RECEIVED",
    "JsonRpcError", "MCPClient",
    "Transport", "StdioTransport", "TransportError",
]
