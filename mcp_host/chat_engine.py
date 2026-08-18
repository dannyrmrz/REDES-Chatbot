"""Chat engine: LLM connection and session context

Every frontend drives this class, so the
conversation logic exists in exactly one place.

The Messages API is stateless: the whole history is resent on each turn, and
that history *is* the session context which lets follow-up questions such as
"and when was he born?" resolve against the previous answer.
"""

from __future__ import annotations

import os

import anthropic

from .interaction_log import InteractionLog

#: Model used unless ANTHROPIC_MODEL says otherwise.
DEFAULT_MODEL = "claude-opus-5"

#: Upper bound for the answer; it is a cap, not a cost.
MAX_TOKENS = 16000

SYSTEM_PROMPT = (
    "You are the assistant of a console chatbot built for a computer networks "
    "course. Answer in the language the user writes in, and be clear and brief."
)


class ChatEngine:
    """Holds the Anthropic client plus the running conversation."""

    def __init__(self, log: InteractionLog, model: str | None = None,
                 system: str = SYSTEM_PROMPT) -> None:
        # The SDK reads ANTHROPIC_API_KEY from the environment.
        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.system = system
        self.log = log
        self.messages: list[dict] = []  # session context

    def send(self, user_text: str) -> str:
        """Send a turn and return the assistant's reply."""
        self.messages.append({"role": "user", "content": user_text})
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system,
            messages=self.messages,
        )
        reply = self._reply_text(response)
        self.messages.append({"role": "assistant", "content": reply})
        return reply

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
