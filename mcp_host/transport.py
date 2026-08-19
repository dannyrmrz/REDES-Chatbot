"""Transports that carry JSON-RPC messages between the host and a server.

MCP defines the framing, not the content: over **stdio** each message is one
UTF-8 JSON object on a single line, terminated by ``\n``, written to the
server's stdin and read back from its stdout (stderr is free for logging).

:class:`Transport` is the abstraction the MCP client talks to, so the HTTP
transport added later for the remote server can be dropped in unchanged.
"""

from __future__ import annotations

import abc
import os
import queue
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from collections import deque

from . import jsonrpc


class TransportError(RuntimeError):
    """The channel to the server broke or timed out."""


class Transport(abc.ABC):
    """Minimal contract: push a message, pull a message, hang up."""

    @abc.abstractmethod
    def start(self) -> None:
        """Open the channel."""

    @abc.abstractmethod
    def send(self, message: dict) -> None:
        """Deliver one JSON-RPC message to the server."""

    @abc.abstractmethod
    def receive(self, timeout: float) -> dict:
        """Return the next message from the server, or raise on timeout."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release the channel and its resources."""


def resolve_command(command: str) -> str:
    """Return the absolute path of ``command``.

    Needed on Windows, where npm installs shims such as ``npx.cmd``: without
    the extension ``CreateProcess`` cannot find the executable.
    """
    return shutil.which(command) or command


class StdioTransport(Transport):
    """Runs an MCP server as a child process and speaks JSON over its pipes."""

    def __init__(self, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None,
                 cwd: str | None = None) -> None:
        self.command = command
        self.args = args or []
        # Servers inherit the environment plus any extra variables they need.
        self.env = {**os.environ, **(env or {})}
        self.cwd = cwd
        self._process: subprocess.Popen | None = None
        self._incoming: queue.Queue[str | None] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=50)

    #lifecycle 
    def start(self) -> None:
        self._process = subprocess.Popen(
            [resolve_command(self.command), *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            cwd=self.cwd,
            text=True,
            encoding="utf-8",
            bufsize=1,  # line buffered: one JSON-RPC message per line
        )
        # Both pipes are drained by daemon threads so a chatty server can never
        # block us, and so `receive` can enforce a timeout.
        threading.Thread(target=self._drain_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stdout(self) -> None:
        assert self._process and self._process.stdout
        for line in self._process.stdout:
            line = line.strip()
            if line:
                self._incoming.put(line)
        self._incoming.put(None)  # sentinel: the server closed the pipe

    def _drain_stderr(self) -> None:
        assert self._process and self._process.stderr
        for line in self._process.stderr:
            self._stderr.append(line.rstrip())

    #messaging
    def send(self, message: dict) -> None:
        if not self._process or self._process.stdin is None:
            raise TransportError("transport is not running")
        try:
            self._process.stdin.write(jsonrpc.encode(message) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise TransportError(f"could not write to the server: {exc}\n"
                                 f"{self.stderr_tail()}") from exc

    def receive(self, timeout: float) -> dict:
        try:
            line = self._incoming.get(timeout=timeout)
        except queue.Empty:
            raise TransportError(
                f"no answer from '{self.command}' after {timeout}s\n"
                f"{self.stderr_tail()}") from None
        if line is None:
            raise TransportError(f"the server '{self.command}' closed the "
                                 f"connection\n{self.stderr_tail()}")
        return jsonrpc.decode(line)

    def stderr_tail(self, lines: int = 10) -> str:
        """Last stderr lines; MCP servers report startup errors there."""
        tail = list(self._stderr)[-lines:]
        return "server stderr:\n  " + "\n  ".join(tail) if tail else ""

    def close(self) -> None:
        if not self._process:
            return
        try:
            if self._process.stdin:
                self._process.stdin.close()  # EOF asks the server to exit
            self._process.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            self._process.kill()
        finally:
            self._process = None


class HttpTransport(Transport):
    """MCP over HTTP: each JSON-RPC message is the body of one POST.

    Used for the clinic server once it is deployed to the cloud. The MCP
    session stays the same (initialize, initialized, tools/list, tools/call);
    only the framing changes, which is exactly what the Wireshark capture is
    meant to show.

    A request gets a JSON body back (HTTP 200). A notification expects no
    answer, so the server replies 202 with no body and nothing is queued.
    """

    def __init__(self, url: str, timeout: float = 60.0) -> None:
        self.url = url
        # Cloud free tiers sleep when idle, so the first call can be slow.
        self.timeout = timeout
        self._incoming: queue.Queue[dict] = queue.Queue()

    def start(self) -> None:
        """Nothing to launch: the server is already running somewhere else."""

    def send(self, message: dict) -> None:
        body = jsonrpc.encode(message).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8").strip()
        except urllib.error.HTTPError as exc:
            # An MCP endpoint answers errors with a JSON-RPC error object;
            # anything else means we are not talking to one (wrong url, proxy,
            # cloud error page), which is worth saying plainly.
            payload = exc.read().decode("utf-8", "replace").strip()
            try:
                self._incoming.put(jsonrpc.decode(payload))
                return
            except jsonrpc.JsonRpcError:
                raise TransportError(
                    f"HTTP {exc.code} from {self.url}: {payload[:120]}") from None
        except urllib.error.URLError as exc:
            raise TransportError(f"could not reach {self.url}: {exc.reason}") from exc

        if payload:
            self._incoming.put(jsonrpc.decode(payload))

    def receive(self, timeout: float) -> dict:
        try:
            return self._incoming.get(timeout=timeout)
        except queue.Empty:
            raise TransportError(f"no answer from {self.url} after {timeout}s") from None

    def close(self) -> None:
        """Stateless: there is no connection of our own to tear down."""
