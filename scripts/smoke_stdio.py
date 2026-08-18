"""Verify the hand-written MCP client against a real official server.

Launches Anthropic's Filesystem MCP server over stdio, runs the full handshake,
lists its tools and calls one of them, then prints the interaction log.
"""

from __future__ import annotations

import os
import sys
import tempfile

# Allow running the script directly from the repository root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_host import InteractionLog, MCPClient, StdioTransport

SERVER_PACKAGE = "@modelcontextprotocol/server-filesystem"


def main() -> int:
    # The filesystem server only exposes the directories given as arguments.
    sandbox = tempfile.mkdtemp(prefix="mcp_smoke_")
    with open(os.path.join(sandbox, "hello.txt"), "w", encoding="utf-8") as fh:
        fh.write("MCP smoke test\n")

    log = InteractionLog(path="logs/smoke_stdio.log")
    client = MCPClient(
        name="filesystem",
        transport=StdioTransport("npx", ["-y", SERVER_PACKAGE, sandbox]),
        log=log,
    )

    try:
        tools = client.connect()
        print(f"Connected to {client.server_info.get('name')} "
              f"{client.server_info.get('version')} "
              f"(protocol {client.protocol_version})")
        print(f"Tools exposed: {len(tools)} -> "
              f"{', '.join(t['name'] for t in tools[:6])} ...\n")

        result = client.call_tool("list_directory", {"path": sandbox})
        print("list_directory ->", MCPClient.result_to_text(result), "\n")
    finally:
        client.close()

    print(log.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
