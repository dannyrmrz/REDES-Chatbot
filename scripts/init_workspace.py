"""Prepare the sandbox the MCP servers operate on.

The official Git MCP server exposes no `git_init` tool (checked across every
released version), so the demo repository has to exist before the chatbot can
add and commit inside it. This script creates it once.

Usage:
    python scripts/init_workspace.py
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.join(ROOT, "workspace")
DEMO_REPO = os.path.join(WORKSPACE, "demo-repo")


def main() -> int:
    os.makedirs(DEMO_REPO, exist_ok=True)
    if os.path.isdir(os.path.join(DEMO_REPO, ".git")):
        print(f"Demo repository already initialised: {DEMO_REPO}")
        return 0

    subprocess.run(["git", "init", "-q", DEMO_REPO], check=True)
    print(f"Demo repository created: {DEMO_REPO}")
    print("The chatbot can now write, add and commit files inside it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
