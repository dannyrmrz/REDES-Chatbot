"""Terminal chatbot: the command line frontend

Usage:
    python cli.py

Type a question to talk to the model, or a slash command (see /help).
"""

from __future__ import annotations

import json
import os
import sys

import anthropic
from dotenv import load_dotenv

from mcp_host import ChatEngine, InteractionLog
from mcp_host.server_registry import ServerRegistry

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config", "servers.json")
WORKSPACE = os.path.join(ROOT, "workspace")

BANNER = """

 MCP Chatbot Host - CC3067 Networks

Type your question, or /help for the commands.
"""

HELP = """
Commands:
  /log     show every interaction with the MCP servers
  /tools   list the connected servers and their tools
  /reset   clear the conversation context
  /help    show this help
  /exit    quit (Ctrl+C also works)
"""

MISSING_KEY = """
ANTHROPIC_API_KEY is not set.

  1. Get a key at https://console.anthropic.com/ - Settings - API keys
  2. Copy .env.example to .env
  3. Paste the key into .env

The .env file is ignored by git, so the key stays out of the repository.
"""


def run_command(command: str, engine: ChatEngine, log: InteractionLog) -> bool:
    """Handle a slash command. Returns False when the user asks to quit."""
    if command in ("/exit", "/quit"):
        return False
    if command == "/help":
        print(HELP)
    elif command == "/log":
        print(log.render())
    elif command == "/tools":
        print(engine.registry.describe() if engine.registry else "(no servers)")
    elif command == "/reset":
        engine.reset()
        print("Context cleared.")
    else:
        print(f"Unknown command: {command}. Type /help.")
    return True


def ask(engine: ChatEngine, question: str) -> None:
    """Send one question and print the answer, reporting API errors clearly."""
    try:
        print(f"\nAssistant: {engine.send(question)}\n")
    except anthropic.AuthenticationError:
        print("\nError: the API key was rejected. Check ANTHROPIC_API_KEY in .env\n")
    except anthropic.RateLimitError:
        print("\nError: rate limited or out of credit. Wait and try again.\n")
    except anthropic.APIStatusError as exc:
        print(f"\nAPI error {exc.status_code}: {exc.message}\n")
    except anthropic.APIConnectionError:
        print("\nError: could not reach the API. Check your connection.\n")


def main() -> int:
    load_dotenv()  # reads .env into the environment
    if not os.getenv("ANTHROPIC_API_KEY"):
        print(MISSING_KEY)
        return 1

    os.makedirs(WORKSPACE, exist_ok=True)  # the filesystem server needs it
    log = InteractionLog()

    print(BANNER)
    registry = ServerRegistry.from_config(CONFIG, log)
    print("Connecting to the MCP servers (the first run downloads them)...")
    for name, status in registry.connect().items():
        print(f"  {name}: {status}")

    engine = ChatEngine(log, registry=registry)
    print(f"\nModel: {engine.model}   Tools available: {len(registry.tool_specs())}\n")

    try:
        while True:
            try:
                entry = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                return 0
            if not entry:
                continue
            if entry.startswith("/"):
                if not run_command(entry, engine, log):
                    print("Bye.")
                    return 0
            else:
                ask(engine, entry)
    finally:
        registry.close()  # stop the server subprocesses


if __name__ == "__main__":
    sys.exit(main())
