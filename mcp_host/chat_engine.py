# Chat engine: LLM connection, session context and tool-use loop.


from __future__ import annotations

import json
import os
from datetime import date

from google import genai

from .interaction_log import InteractionLog
from .mcp_client import MCPClient
from .server_registry import ServerRegistry

#: Model used unless GEMINI_MODEL says otherwise. Available on the free tier.
DEFAULT_MODEL = "gemini-3.7-flash"

#: Upper bound for one answer; it is a cap, not a cost.
MAX_OUTPUT_TOKENS = 8192

#: Safety net so a confused model cannot loop over tools forever.
MAX_TOOL_ROUNDS = 8

#: Tool results are pasted into the context, so keep them bounded.
MAX_RESULT_CHARS = 6000

#: Gemini accepts only a subset of OpenAPI schema. MCP servers publish full
#: JSON Schema, so anything outside this set is dropped before sending.
SCHEMA_KEYS = {"type", "description", "enum", "items", "properties",
               "required", "nullable"}

SYSTEM_PROMPT = (
    "You are the assistant of a console chatbot built for a computer networks "
    "course. You can use tools published by MCP servers: a filesystem server, "
    "a git server and a medical clinic server. Use them when the user asks for "
    "real actions on files, repositories or appointments, and report what you "
    "did. Answer in the language the user writes in, and be clear and brief."
)


def to_gemini_schema(schema: dict) -> dict:
    """Translate an MCP JSON Schema into the subset Gemini accepts.
    """
    if not isinstance(schema, dict):
        return {"type": "string"}

    if "anyOf" in schema:
        branches = [b for b in schema["anyOf"] if b.get("type") != "null"]
        nullable = len(branches) != len(schema["anyOf"])
        collapsed = to_gemini_schema(branches[0]) if branches else {"type": "string"}
        if nullable:
            collapsed["nullable"] = True
        if "description" in schema:
            collapsed.setdefault("description", schema["description"])
        return collapsed

    clean: dict = {}
    for key, value in schema.items():
        if key not in SCHEMA_KEYS:
            continue
        if key == "properties":
            clean[key] = {n: to_gemini_schema(s) for n, s in value.items()}
        elif key == "items":
            clean[key] = to_gemini_schema(value)
        else:
            clean[key] = value

    clean.setdefault("type", "object" if "properties" in clean else "string")
    # An object with no properties is rejected, so describe it as empty.
    if clean["type"] == "object":
        clean.setdefault("properties", {})
    return clean


class ChatEngine:
    """Holds the Gemini client, the running conversation and the tools."""

    def __init__(self, log: InteractionLog, registry: ServerRegistry | None = None,
                 model: str | None = None, system: str = SYSTEM_PROMPT) -> None:
        # The SDK reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the environment.
        self.client = genai.Client()
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        # A model has no clock. Without today's date it reads "21 August" as a
        # date in its training past and books appointments in the wrong year.
        self.system = f"{system}\nToday is {date.today().isoformat()}."
        self.log = log
        self.registry = registry
        self.history: list[dict] = []  # session context

    def send(self, user_text: str, on_tool=None) -> str:
        """Send a turn, running any tools the model asks for, and return the reply.

        ``on_tool(name, arguments)`` is called before each tool runs so the UI
        can show progress.
        """
        self.history.append({
            "type": "user_input",
            "content": [{"type": "text", "text": user_text}],
        })

        for _ in range(MAX_TOOL_ROUNDS):
            interaction = self.client.interactions.create(
                model=self.model,
                system_instruction=self.system,
                store=False,  # we keep the history, not Google
                input=self.history,
                tools=self._tool_declarations(),
                generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS},
            )

            # Store the steps verbatim; they are the assistant's half of the
            # context and must be replayed exactly on the next request.
            calls = []
            for step in interaction.steps:
                self.history.append(step.model_dump())
                if step.type == "function_call":
                    calls.append(step)

            if not calls:
                return interaction.output_text or "(the model returned no text)"

            for call in calls:
                self.history.append(self._run_tool(call, on_tool))

        return f"(stopped after {MAX_TOOL_ROUNDS} tool rounds without a final answer)"

    def _tool_declarations(self) -> list[dict]:
        """Every MCP tool, expressed the way Gemini declares functions."""
        if not self.registry:
            return []
        return [{
            "type": "function",
            "name": spec["name"],
            "description": spec["description"],
            "parameters": to_gemini_schema(spec["schema"]),
        } for spec in self.registry.tool_specs()]

    def _run_tool(self, call, on_tool) -> dict:
        """Run one tool call and build the result entry for the history."""
        arguments = call.arguments or {}
        if on_tool:
            on_tool(call.name, arguments)
        try:
            result = self.registry.call(call.name, arguments)
            text = MCPClient.result_to_text(result)
            if result.get("isError"):
                text = f"The tool reported a problem: {text}"
        except Exception as exc:  # transport failure or unknown tool
            text = f"The tool could not be run: {exc}"
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n... (result truncated)"
        return {
            "type": "function_result",
            "name": call.name,
            "call_id": call.id,
            "result": [{"type": "text", "text": text}],
        }

    def reset(self) -> None:
        """Forget the conversation; the next turn starts a new context."""
        self.history.clear()

    @property
    def turns(self) -> int:
        """Entries currently kept as context."""
        return len(self.history)
