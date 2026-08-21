"""MCP server for the clinic: the server half of the protocol, written by hand.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from mcp_host import jsonrpc

from .store import ClinicError, ClinicStore

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "clinic-mcp-server", "version": "1.0.0"}

#: Tool catalogue advertised by `tools/list`.
TOOLS: list[dict] = [
    {
        "name": "list_specialties",
        "description": "List the medical specialties the clinic offers. "
                       "Call this first when the patient does not know which "
                       "specialty they need.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "find_doctors",
        "description": "Find doctors, optionally filtered by specialty id "
                       "(for example 'cardiology') or by part of their name. "
                       "Returns the doctor ids needed to check availability.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "specialty": {"type": "string",
                              "description": "Specialty id or display name."},
                "name": {"type": "string",
                         "description": "Part of the name of the doctor."},
            },
        },
    },
    {
        "name": "get_availability",
        "description": "Free appointment slots of one doctor on one date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string", "description": "Id from find_doctors."},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD."},
            },
            "required": ["doctor_id", "date"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Book a free slot. Returns the appointment with the "
                       "confirmation code the patient needs to look it up or "
                       "cancel it later.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string", "description": "Id from find_doctors."},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD."},
                "time": {"type": "string",
                         "description": "Slot as HH:MM, from get_availability."},
                "patient_name": {"type": "string",
                                 "description": "Full name of the patient."},
                "reason": {"type": "string", "description": "Reason for the visit."},
            },
            "required": ["doctor_id", "date", "time", "patient_name"],
        },
    },
    {
        "name": "get_appointment",
        "description": "Look up an appointment by its confirmation code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code such as APT-1A2B3C."},
            },
            "required": ["code"],
        },
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel an appointment by its confirmation code and "
                       "free the slot for other patients.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code such as APT-1A2B3C."},
            },
            "required": ["code"],
        },
    },
]


class ClinicServer:
    """Turns incoming JSON-RPC messages into calls on the store."""

    def __init__(self, store: ClinicStore) -> None:
        self.store = store
        self.handlers = {
            "list_specialties": lambda a: self.store.list_specialties(),
            "find_doctors": lambda a: self.store.find_doctors(
                a.get("specialty"), a.get("name")),
            "get_availability": lambda a: self.store.get_availability(
                a["doctor_id"], a["date"]),
            "book_appointment": lambda a: self.store.book_appointment(
                a["doctor_id"], a["date"], a["time"], a["patient_name"],
                a.get("reason", "")),
            "get_appointment": lambda a: self.store.get_appointment(a["code"]),
            "cancel_appointment": lambda a: self.store.cancel_appointment(a["code"]),
        }

    # -- protocol --------------------------------------------------------- #
    def handle(self, message: dict) -> dict | None:
        """Answer one message, or return None when no answer is expected."""
        kind = jsonrpc.classify(message)
        if kind == jsonrpc.KIND_NOTIFICATION:
            return None  # notifications/initialized and friends
        if kind != jsonrpc.KIND_REQUEST:
            return None  # we never send requests, so responses are unexpected

        request_id, method = message["id"], message["method"]
        params = message.get("params", {})
        try:
            if method == "initialize":
                return jsonrpc.build_response(request_id, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                })
            if method == "tools/list":
                return jsonrpc.build_response(request_id, {"tools": TOOLS})
            if method == "tools/call":
                return jsonrpc.build_response(request_id, self._call_tool(params))
            if method == "ping":
                return jsonrpc.build_response(request_id, {})
            return jsonrpc.build_error_response(
                request_id, jsonrpc.METHOD_NOT_FOUND, f"unknown method '{method}'")
        except Exception as exc:  # never let one bad request kill the server
            return jsonrpc.build_error_response(
                request_id, jsonrpc.INTERNAL_ERROR, str(exc))

    def _call_tool(self, params: dict) -> dict:
        """Run a tool and wrap its output in an MCP result.

        A failing tool is not a JSON-RPC error: the result carries isError so
        the model can read what went wrong and correct itself.
        """
        name = params.get("name", "")
        handler = self.handlers.get(name)
        if handler is None:
            return _result(f"Unknown tool '{name}'.", is_error=True)
        try:
            return _result(handler(params.get("arguments") or {}))
        except ClinicError as exc:
            return _result(str(exc), is_error=True)
        except KeyError as exc:  # a required argument was missing
            return _result(f"Missing required argument: {exc}.", is_error=True)

    # -- stdio loop ------------------------------------------------------- #
    def run(self, stdin=None, stdout=None) -> None:
        """Read one JSON message per line until the host closes the pipe."""
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        print(f"{SERVER_INFO['name']} ready on stdio", file=sys.stderr, flush=True)

        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = jsonrpc.decode(line)
            except jsonrpc.JsonRpcError as exc:
                self._write(stdout,
                            jsonrpc.build_error_response(None, exc.code, exc.message))
                continue
            response = self.handle(message)
            if response is not None:
                self._write(stdout, response)

    @staticmethod
    def _write(stdout, message: dict) -> None:
        stdout.write(jsonrpc.encode(message) + "\n")
        stdout.flush()


def _result(payload: Any, is_error: bool = False) -> dict:
    """Build an MCP tool result; structured payloads travel as JSON text."""
    text = payload if isinstance(payload, str) else json.dumps(
        payload, indent=2, ensure_ascii=False)
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result
