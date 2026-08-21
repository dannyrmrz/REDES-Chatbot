"""Runs several MCP servers at once and exposes their tools as one catalogue.

The servers are declared in `config/servers.json`, so adding one (the clinic
server, later) never means touching this code.
"""

from __future__ import annotations

import json
import os

from .interaction_log import InteractionLog
from .mcp_client import MCPClient
from .transport import HttpTransport, StdioTransport

#: Separator between the server name and the tool name.
SEPARATOR = "__"


class ServerRegistry:
    """Owns one :class:`MCPClient` per configured server."""

    def __init__(self, log: InteractionLog) -> None:
        self.log = log
        self.clients: dict[str, MCPClient] = {}
        self._specs: list[dict] = []

    @classmethod
    def from_config(cls, path: str, log: InteractionLog) -> "ServerRegistry":
        """Build the registry from a JSON configuration file."""
        with open(path, encoding="utf-8") as handle:
            config = json.load(handle)
        base = os.path.dirname(os.path.abspath(path))

        registry = cls(log)
        for entry in config["servers"]:
            if not entry.get("enabled", True):
                continue
            registry.clients[entry["name"]] = MCPClient(
                name=entry["name"],
                transport=_build_transport(entry, base),
                log=log,
            )
        return registry

    # -- lifecycle -------------------------------------------------------- #
    def connect(self) -> dict[str, str]:
        """Connect to every server; returns {server: status} for the UI."""
        status: dict[str, str] = {}
        for name, client in list(self.clients.items()):
            try:
                tools = client.connect()
                status[name] = f"{len(tools)} tools"
            except Exception as exc:  # one broken server must not sink the rest
                status[name] = f"unavailable ({exc.__class__.__name__}: {exc})"
                self.clients.pop(name)
        self._specs = self._build_specs()
        return status

    def close(self) -> None:
        for client in self.clients.values():
            client.close()
        self.clients.clear()

    # -- tools ------------------------------------------------------------ #
    def _build_specs(self) -> list[dict]:
        """Collect every tool, named after the server that owns it.

        The shape stays provider neutral on purpose: the chat engine is the
        only place that knows how a given LLM wants tools declared.
        """
        specs = []
        for name, client in self.clients.items():
            for tool in client.tools:
                specs.append({
                    "name": f"{name}{SEPARATOR}{tool['name']}",
                    "description": tool.get("description", ""),
                    "schema": tool.get("inputSchema", {"type": "object"}),
                })
        return specs

    def tool_specs(self) -> list[dict]:
        """Every tool of every connected server, as MCP describes them."""
        return self._specs

    def call(self, qualified_name: str, arguments: dict) -> dict:
        """Route a prefixed tool name back to the server that owns it."""
        server, _, tool = qualified_name.partition(SEPARATOR)
        client = self.clients.get(server)
        if client is None:
            raise KeyError(f"unknown MCP server '{server}'")
        return client.call_tool(tool, arguments)

    def describe(self) -> str:
        """Human readable catalogue for the CLI's /tools command."""
        if not self.clients:
            return "(no MCP servers connected)"
        lines = []
        for name, client in self.clients.items():
            info = client.server_info
            lines.append(f"\n{name} - {info.get('name', '?')} "
                         f"{info.get('version', '')} "
                         f"(protocol {client.protocol_version})")
            for tool in client.tools:
                summary = (tool.get("description") or "").split("\n")[0][:70]
                lines.append(f"  {name}{SEPARATOR}{tool['name']:<26} {summary}")
        return "\n".join(lines)


def _build_transport(entry: dict, base: str):
    """Build the transport a server entry asks for; stdio unless it says http."""
    if entry.get("transport") == "http":
        # ${VARIABLE} in the url lets the deployed address live in .env.
        return HttpTransport(os.path.expandvars(entry["url"]))
    return StdioTransport(
        command=entry["command"],
        # Paths written as "./x" are relative to the config file.
        args=[_resolve(arg, base) for arg in entry.get("args", [])],
        env=entry.get("env"),
        # Needed by servers started as a Python module.
        cwd=_resolve(entry["cwd"], base) if entry.get("cwd") else None,
    )


def _resolve(arg: str, base: str) -> str:
    """Turn a './relative' argument into an absolute path."""
    if arg.startswith("./") or arg.startswith("../"):
        return os.path.normpath(os.path.join(base, arg))
    return arg
