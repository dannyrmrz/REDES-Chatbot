"""Chat engine: LLM connection, session context and tool-use loop.

Covers requirements 1, 2 and 4. Every frontend (CLI, and later the web UI)
drives this class, so the conversation logic exists in exactly one place.

The Messages API is stateless: the whole history is resent on each turn, and
that history *is* the session context which lets follow-up questions such as
"and when was he born?" resolve against the previous answer.

The tool loop is written by hand on purpose. The SDK ships helpers that would
do it (`tool_runner`, the `mcp_servers` connector), but they implement MCP for
you, which the assignment forbids.
"""

from __future__ import annotations

import os

import anthropic

from .interaction_log import InteractionLog
from .mcp_client import MCPClient
from .server_registry import ServerRegistry

#: Model used unless ANTHROPIC_MODEL says otherwise.
DEFAULT_MODEL = "claude-opus-5"

#: Upper bound for the answer; it is a cap, not a cost.
MAX_TOKENS = 16000

#: Safety net so a confused model cannot loop over tools forever.
MAX_TOOL_ROUNDS = 8

#: Tool results are pasted into the context, so keep them bounded.
MAX_RESULT_CHARS = 6000

SYSTEM_PROMPT = (
    "You are the assistant of a console chatbot built for a computer networks "
    "course. You can use tools published by MCP servers: a filesystem server "
    "and a git server. Use them when the user asks for real actions on files "
    "or repositories, and report what you did. Answer in the language the "
    "user writes in, and be clear and brief."
)


class ChatEngine:
    """Holds the Anthropic client, the running conversation and the tools."""

    def __init__(self, log: InteractionLog, registry: ServerRegistry | None = None,
                 model: str | None = None, system: str = SYSTEM_PROMPT) -> None:
        # The SDK reads ANTHROPIC_API_KEY from the environment.
        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.system = system
        self.log = log
        self.registry = registry
        self.messages: list[dict] = []  # session context

    def send(self, user_text: str, on_tool=None) -> str:
        """Send a turn, running any tools the model asks for, and return the reply.

        ``on_tool(name, arguments)`` is called before each tool runs so the UI
        can show progress.
        """
        self.messages.append({"role": "user", "content": user_text})
        tools = self.registry.tool_specs() if self.registry else []

        for _ in range(MAX_TOOL_ROUNDS):
            request = {
                "model": self.model,
                "max_tokens": MAX_TOKENS,
                "system": self.system,
                "messages": self.messages,
            }
            if tools:
                request["tools"] = tools
            response = self.client.messages.create(**request)

            # Store the blocks verbatim: tool_use and thinking blocks must be
            # echoed back unchanged for the next request to be valid.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return self._reply_text(response)

            self.messages.append({
                "role": "user",
                "content": self._run_tools(response, on_tool),
            })

        return f"(stopped after {MAX_TOOL_ROUNDS} tool rounds without a final answer)"

    def _run_tools(self, response, on_tool) -> list[dict]:
        """Execute every tool the model requested and build the result blocks.

        All results travel back in a single user message, as the API requires.
        """
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if on_tool:
                on_tool(block.name, block.input)
            try:
                result = self.registry.call(block.name, block.input)
                text = MCPClient.result_to_text(result)
                failed = bool(result.get("isError"))
            except Exception as exc:  # transport or unknown tool
                text, failed = f"The tool could not be run: {exc}", True
            if len(text) > MAX_RESULT_CHARS:
                text = text[:MAX_RESULT_CHARS] + "\n... (result truncated)"
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": text,
                "is_error": failed,
            })
        return results

    @staticmethod
    def _reply_text(response) -> str:
        """Join the text blocks of a response (thinking blocks are skipped)."""
        if response.stop_reason == "refusal":
            return "(the model declined to answer this request)"
        text = "\n".join(b.text for b in response.content if b.type == "text")
        return text or "(the model returned no text)"

    def reset(self) -> None:
        """Forget the conversation; the next turn starts a new context."""
        self.messages.clear()

    @property
    def turns(self) -> int:
        """Messages currently kept as context."""
        return len(self.messages)
