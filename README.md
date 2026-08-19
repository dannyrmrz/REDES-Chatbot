# MCP Chatbot Host

A console chatbot that acts as a **Model Context Protocol (MCP) host**: it talks to an
LLM through its API and extends it with tools published by several MCP servers.

Course project for **CC3067 Redes**, Universidad del Valle de Guatemala.

## Key constraint

The MCP protocol is **implemented by hand on top of JSON-RPC 2.0**. No MCP library or
SDK (`mcp`, `FastMCP`, ...) is used: every `initialize`, `notifications/initialized`,
`tools/list` and `tools/call` message is built, serialised and parsed by the code in
this repository. The official Anthropic SDK is used only to reach the LLM, which the
assignment allows.

## Architecture

```
                +---------------------------+
   you  <-->    |  chatbot host (this repo)  |  <-->  Claude API (LLM)
                +---------------------------+
                      |          |
             JSON-RPC 2.0 over stdio / HTTP
                      |          |
              +-------+          +--------+
              | MCP servers: filesystem, git,
              | clinic (own, local and remote)
              +-------------------------------+
```

| Module | Responsibility |
| --- | --- |
| `mcp_host/jsonrpc.py` | JSON-RPC 2.0 messages: builders, wire encoding, parsing, classification |
| `mcp_host/transport.py` | Framing. `StdioTransport` runs a server as a child process and exchanges one JSON object per line |
| `mcp_host/mcp_client.py` | The MCP session: handshake, tool discovery, tool invocation |
| `mcp_host/interaction_log.py` | Transcript of **every** message sent to and received from the servers |
| `mcp_host/server_registry.py` | Runs several MCP servers at once and merges their tools into one catalogue |
| `mcp_host/chat_engine.py` | LLM connection, session context and the tool-use loop |
| `cli.py` | Terminal chatbot |

### The MCP handshake, as implemented

| # | Message | Type | Purpose |
| --- | --- | --- | --- |
| 1 | `initialize` | request → | protocol version, capabilities and client identity |
| 2 | `initialize` | ← response | the server answers with its version, capabilities and identity |
| 3 | `notifications/initialized` | notification → | the session is live (no answer expected) |
| 4 | `tools/list` | request → | discover the available tools and their JSON schemas |
| 5 | `tools/call` | request → | run a tool with arguments and read back its content |

## Requirements

- Python 3.11 or newer
- Node.js 18 or newer — only to run the official MCP servers through `npx`
- An Anthropic API key

## Installation

```powershell
git clone <repository-url>
cd REDES-Chatbot

python -m venv .venv
.venv\Scripts\Activate.ps1        # on Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

Copy-Item .env.example .env       # then edit .env and paste your API key

pip install -r requirements-servers.txt   # the official Git MCP server
python scripts/init_workspace.py          # create the demo sandbox
```

`requirements-servers.txt` is kept separate on purpose: those packages are the
official servers we talk to, not part of this implementation. The Filesystem
server needs no install, `npx` downloads it the first time the chatbot starts.

Get the API key at <https://console.anthropic.com/> → *Settings* → *API keys*. New
accounts include free credits and no card is required. `.env` is ignored by git, so the
key never reaches the repository.

## Usage

### Chatbot

```powershell
python cli.py
```

Ask anything, or use a command:

| Command | Effect |
| --- | --- |
| `/log` | show every interaction with the MCP servers |
| `/tools` | list the connected servers and their tools |
| `/reset` | clear the conversation context |
| `/help` | list the commands |
| `/exit` | quit (Ctrl+C also works) |

The context is what makes a conversation work: ask *"Who was Alan Turing?"* and then
*"When was he born?"*, and the second question is answered about Turing, because the
full history travels with every request.

```
You: Who was Alan Turing?
Assistant: Alan Turing was a British mathematician and logician ...

You: When was he born?
Assistant: He was born on 23 June 1912 in London.
```

The model defaults to `claude-opus-5`; set `ANTHROPIC_MODEL` in `.env` to use another one.

### MCP servers

At startup the chatbot connects to every server listed in
[`config/servers.json`](config/servers.json) and offers all their tools to the model.
Tool names are prefixed with their server (`filesystem__write_file`,
`git__git_commit`) so the model knows what it is calling and two servers can expose
the same tool name without clashing. Adding a server is a config entry, not a code
change.

| Server | Runs as | Tools |
| --- | --- | --- |
| Filesystem (official) | `npx -y @modelcontextprotocol/server-filesystem ./workspace` | 14 |
| Git (official) | `python -m mcp_server_git` | 12 |

Both are sandboxed to `workspace/`, which git ignores, so the chatbot can never
touch this repository.

### Demo scenario

Ask the chatbot, in one message:

> Write a README.md in workspace/demo-repo describing this project, then stage it
> and commit it with a sensible message.

It answers by chaining tools across both servers, printing each call as it goes:

```
  [tool] filesystem__write_file {"path": "...\demo-repo\README.md", ...}
  [tool] git__git_add {"repo_path": "...\demo-repo", "files": ["README.md"]}
  [tool] git__git_commit {"repo_path": "...\demo-repo", "message": "Add README"}

Assistant: I created README.md, staged it and committed it as 75a7b4d.
```

`/log` then shows every JSON-RPC message behind those three lines.

**Note on creating repositories.** The official Git MCP server publishes no
`git_init` tool in any released version, so the demo repository is created once by
`scripts/init_workspace.py`. Everything after that — writing files, staging,
committing, reading the log — goes through the MCP servers.

### MCP smoke test

This proves the hand-written client against a real official MCP server:

```powershell
python scripts/smoke_stdio.py
```

It downloads Anthropic's Filesystem MCP server with `npx`, performs the handshake over
stdio, lists the 14 tools it publishes, calls `list_directory`, and prints the full
interaction log. Expected output:

```
Connected to secure-filesystem-server 0.2.0 (protocol 2025-06-18)
Tools exposed: 14 -> read_file, read_text_file, read_media_file, ...

list_directory -> [FILE] hello.txt

--- MCP interaction log (7/7 messages) ---
[19:20:24.421] --> filesystem   request      initialize (id=1)
    {"jsonrpc":"2.0","id":1,"method":"initialize", ...
```

## Project layout

```
cli.py             terminal chatbot
config/            MCP server declarations
mcp_host/          the host library (JSON-RPC, transports, MCP client, log, chat engine)
scripts/           runnable checks and utilities
workspace/         sandbox the MCP servers operate on (ignored by git)
logs/              interaction logs written at runtime (ignored by git)
```