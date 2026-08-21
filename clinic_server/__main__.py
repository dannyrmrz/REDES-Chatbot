from __future__ import annotations

import sys

from .server import ClinicServer
from .store import ClinicStore


def main() -> int:
    # MCP messages are UTF-8; Windows consoles otherwise default to cp1252.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    ClinicServer(ClinicStore()).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
