"""Usage:
    # against the local server (plain HTTP, readable in Wireshark directly)
    python -m clinic_server.http_server          # in another terminal
    python scripts/capture_session.py

    # against the deployed server (HTTPS, needs TLS decryption to read)
    python scripts/capture_session.py https://your-service.onrender.com/mcp
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_host import InteractionLog, MCPClient
from mcp_host.transport import HttpTransport

DEFAULT_URL = "http://127.0.0.1:8000/mcp"

#: How each MCP method maps to the three roles requirement 7 asks about.
ROLE = {
    "initialize": "synchronisation (opens the session, negotiates the version)",
    "notifications/initialized": "synchronisation (confirms the session is live)",
    "tools/list": "request (discovery)",
    "tools/call": "request (invocation)",
}


def classify(entry) -> str:
    """Describe one logged message the way the report needs it."""
    if entry.kind == "notification":
        return ROLE.get(entry.method, "notification")
    if entry.kind == "request":
        return ROLE.get(entry.method, "request")
    if entry.kind == "error":
        return "response (error)"
    return f"response to {entry.method}"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    print(f"Target      : {url}")
    print(f"Wireshark   : capture on the interface that reaches {parsed.hostname}")
    print(f"Filter      : tcp.port == {port}"
          + ("" if parsed.scheme == "https" else " && http"))
    print(f"Encryption  : {'TLS, needs SSLKEYLOGFILE to read the bodies' if parsed.scheme == 'https' else 'none, JSON-RPC is readable as text'}")
    print("\nStart the capture, then press Enter to run the session...")
    input()

    log = InteractionLog(path="logs/capture_session.log")
    client = MCPClient("clinic-capture", HttpTransport(url), log)

    # A fixed, meaningful session: handshake, discovery, then a booking that
    # is created, read back and cancelled so the capture tells a whole story.
    client.connect()
    print(f"Connected to {client.server_info.get('name')} "
          f"(protocol {client.protocol_version})")

    doctors = client.call_tool("find_doctors", {"specialty": "pediatrics"})
    doctor_id = "doc-004"
    print("find_doctors      ->", MCPClient.result_to_text(doctors)[:60].replace("\n", " "))

    date = "2026-09-15"
    client.call_tool("get_availability", {"doctor_id": doctor_id, "date": date})
    booking = client.call_tool("book_appointment", {
        "doctor_id": doctor_id, "date": date, "time": "09:00",
        "patient_name": "Captura Wireshark", "reason": "Demostracion de red",
    })
    text = MCPClient.result_to_text(booking)
    code = text.split('"code": "')[1].split('"')[0] if '"code": "' in text else None
    print("book_appointment  -> code", code)

    if code:
        client.call_tool("get_appointment", {"code": code})
        client.call_tool("cancel_appointment", {"code": code})
    client.call_tool("get_appointment", {"code": "APT-DOESNOTEXIST"})  # error path
    client.close()

    print("\nStop the capture now.\n")
    print(f"{'#':>3}  {'direction':<9} {'kind':<13} {'method':<26} role")
    print("-" * 96)
    for index, entry in enumerate(log.entries(), start=1):
        arrow = "host->srv" if entry.direction == "sent" else "srv->host"
        print(f"{index:>3}  {arrow:<9} {entry.kind:<13} {entry.method:<26} {classify(entry)}")

    print(f"\n{len(log)} JSON-RPC messages. Full text in logs/capture_session.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
