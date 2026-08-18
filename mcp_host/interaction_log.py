"""Log of every interaction exchanged with the MCP servers.

Each message that crosses a transport is recorded here *before* it is sent and
right after it is received.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

from . import jsonrpc

#Direction of a message as seen from the host (the chatbot).
SENT = "sent"          # host - server
RECEIVED = "received"  # server - host

_ARROWS = {SENT: "-->", RECEIVED: "<--"}


@dataclass
class LogEntry:
    """One JSON-RPC message together with its routing metadata."""

    timestamp: str
    server: str
    direction: str
    kind: str
    method: str
    message_id: Any = None
    payload: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "server": self.server,
            "direction": self.direction,
            "kind": self.kind,
            "method": self.method,
            "id": self.message_id,
            "payload": self.payload,
        }

    def summary(self, width: int = 110) -> str:
        """One-line human readable form used by the CLI."""
        arrow = _ARROWS.get(self.direction, "?")
        head = (f"[{self.timestamp}] {arrow} {self.server:<12} "
                f"{self.kind:<12} {self.method}")
        if self.message_id is not None:
            head += f" (id={self.message_id})"
        body = jsonrpc.encode(self.payload)
        if len(body) > width:
            body = body[:width] + "..."
        return f"{head}\n    {body}"


class InteractionLog:
    """Collects :class:`LogEntry` objects for every connected server."""

    def __init__(self, path: str = "logs/mcp_interactions.log",
                 echo: bool = False) -> None:
        """``echo=True`` mirrors every entry to stdout (verbose mode)."""
        self.path = path
        self.echo = echo
        self._entries: list[LogEntry] = []
        # Maps a request id to its method, so responses (which carry no method)
        # can be labelled with the call they belong to.
        self._pending: dict[Any, str] = {}
        if self.path:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    def record(self, server: str, direction: str, message: dict) -> LogEntry:
        """Register one raw JSON-RPC message and return the stored entry."""
        kind = jsonrpc.classify(message)
        message_id = message.get("id")
        method = message.get("method", "")
        if kind in (jsonrpc.KIND_REQUEST, jsonrpc.KIND_NOTIFICATION):
            if message_id is not None:
                self._pending[message_id] = method
        else:
            # Responses only carry the id,   recover the method that was called.
            method = self._pending.pop(message_id, "(unknown)")

        entry = LogEntry(
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            server=server,
            direction=direction,
            kind=kind,
            method=method,
            message_id=message_id,
            payload=message,
        )
        self._entries.append(entry)
        self._persist(entry)
        if self.echo:
            print(entry.summary())
        return entry

    def _persist(self, entry: LogEntry) -> None:
        """Append the entry as one JSON object per line."""
        if not self.path:
            return
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.as_dict(), ensure_ascii=False) + "\n")

    #reading 
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[LogEntry]:
        return iter(self._entries)

    def entries(self, server: str | None = None,
                limit: int | None = None) -> list[LogEntry]:
        """Return stored entries, optionally filtered by server and trimmed."""
        found = [e for e in self._entries if server in (None, e.server)]
        return found[-limit:] if limit else found

    def render(self, server: str | None = None,
               limit: int | None = None) -> str:
        """Render the log as text for the CLI / web UI."""
        found = self.entries(server=server, limit=limit)
        if not found:
            return "(no MCP interactions recorded yet)"
        header = f"--- MCP interaction log ({len(found)}/{len(self._entries)} messages) ---"
        return "\n".join([header] + [e.summary() for e in found])

    def clear(self) -> None:
        self._entries.clear()
        self._pending.clear()
