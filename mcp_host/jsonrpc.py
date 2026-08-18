"""Hand-written JSON-RPC 2.0 message layer.

MCP carries every message as a JSON-RPC 2.0 object. This module builds, serialises, 
parses and classifies each message by hand. 
"""

from __future__ import annotations

import itertools
import json
from typing import Any

#: Every message must carry this exact member (spec section 4).
JSONRPC_VERSION = "2.0"

# Pre-defined error codes (spec section 5.1).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Message classes used by :func:`classify`.  They map one-to-one to the three
# roles a JSON-RPC message can play
KIND_REQUEST = "request"            # has "method" and "id" - expects an answer
KIND_NOTIFICATION = "notification"  # has "method", no "id" - fire and forget
KIND_RESPONSE = "response"          # has "id" and "result"
KIND_ERROR = "error"                # has "id" and "error"


class JsonRpcError(Exception):
    """Raised when a peer answers with an ``error`` member."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class IdGenerator:
    """Hands out request ids; they only need to be unique within a session."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def next(self) -> int:
        return next(self._counter)

# Builders
def build_request(request_id: int | str, method: str,
                  params: dict | None = None) -> dict:
    """Build a request: the peer *must* reply with the same ``id``."""
    message: dict[str, Any] = {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "method": method,
    }
    if params is not None:
        message["params"] = params
    return message


def build_notification(method: str, params: dict | None = None) -> dict:
    """Build a notification: no ``id``, so the peer must not reply."""
    message: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        message["params"] = params
    return message


def build_response(request_id: int | str, result: Any) -> dict:
    """Build a successful response for ``request_id``."""
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def build_error_response(request_id: int | str | None, code: int,
                         message: str, data: Any = None) -> dict:
    """Build an error response.  ``request_id`` is ``None`` if it was unusable."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}

# Wire format
def encode(message: dict) -> str:
    """Serialise to a single compact line (stdio framing forbids newlines)."""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def decode(raw: str) -> dict:
    """Parse one message and validate the envelope required by the spec."""
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsonRpcError(PARSE_ERROR, f"invalid JSON received: {exc}") from exc
    if not isinstance(message, dict):
        # MCP never uses JSON-RPC batches, so anything else is malformed.
        raise JsonRpcError(INVALID_REQUEST, "expected a single JSON object")
    if message.get("jsonrpc") != JSONRPC_VERSION:
        raise JsonRpcError(INVALID_REQUEST,
                           f"missing or wrong 'jsonrpc' member: {message.get('jsonrpc')!r}")
    return message


def classify(message: dict) -> str:
    """Return the ``KIND_*`` this message belongs to."""
    if "method" in message:
        return KIND_REQUEST if "id" in message else KIND_NOTIFICATION
    if "error" in message:
        return KIND_ERROR
    return KIND_RESPONSE


def extract_result(message: dict) -> Any:
    """Return the ``result`` of a response, raising on an ``error`` member."""
    if "error" in message:
        error = message["error"]
        raise JsonRpcError(error.get("code", INTERNAL_ERROR),
                           error.get("message", "unknown error"),
                           error.get("data"))
    return message.get("result")
