# MCP Chatbot Host

A console chatbot that acts as a **Model Context Protocol (MCP) host**: it talks to an
LLM through its API and extends it with tools published by several MCP servers.

Course project for **CC3067 Redes**, Universidad del Valle de Guatemala.

## Key constraint

The MCP protocol is **implemented by hand on top of JSON-RPC 2.0**. No MCP library or
SDK (`mcp`, `FastMCP`, ...) is used: every `initialize`, `notifications/initialized`,
`tools/list` and `tools/call` message is built, serialised and parsed by the code in
this repository. Google's SDK is used only to reach the LLM, which the assignment allows: it
implements the Gemini API, not MCP. Swapping the LLM provider touches one module,
`mcp_host/chat_engine.py`, and nothing in the protocol layer.

## Architecture

```
                +---------------------------+
   you  <-->    |  chatbot host (this repo)  |  <-->  Gemini API (LLM)
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
| `mcp_host/transport.py` | Framing. `StdioTransport` runs a server as a child process; `HttpTransport` posts each message to a remote server |
| `mcp_host/mcp_client.py` | The MCP session: handshake, tool discovery, tool invocation |
| `mcp_host/interaction_log.py` | Transcript of **every** message sent to and received from the servers |
| `mcp_host/server_registry.py` | Runs several MCP servers at once and merges their tools into one catalogue |
| `mcp_host/chat_engine.py` | LLM connection, session context, tool-use loop and schema translation |
| `cli.py` | Terminal chatbot |
| `web/` | Web chatbot: a second frontend on the very same engine |
| `clinic_server/` | Our own MCP server: clinic appointments, the server half of the protocol |

### The MCP handshake, as implemented

| # | Message | Type | Purpose |
| --- | --- | --- | --- |
| 1 | `initialize` | request → | protocol version, capabilities and client identity |
| 2 | `initialize` | ← response | the server answers with its version, capabilities and identity |
| 3 | `notifications/initialized` | notification → | the session is live (no answer expected) |
| 4 | `tools/list` | request → | discover the available tools and their JSON schemas |
| 5 | `tools/call` | request → | run a tool with arguments and read back its content |

## Implemented features

| # | Feature | Where |
| --- | --- | --- |
| 1 | Connection to an LLM through its API | [`mcp_host/chat_engine.py`](mcp_host/chat_engine.py) |
| 2 | Session context kept across turns | same file: the history travels with every request |
| 3 | Log of every request and response with the MCP servers | [`mcp_host/interaction_log.py`](mcp_host/interaction_log.py), `/log` in the CLI, right pane on the web |
| 4 | Official Filesystem and Git MCP servers | [`config/servers.json`](config/servers.json) + [`mcp_host/server_registry.py`](mcp_host/server_registry.py) |
| 5 | Own MCP server, local, with its specification | [`clinic_server/`](clinic_server) + [docs/clinic-server.md](docs/clinic-server.md) |
| 6 | The same server, running remotely | [`clinic_server/http_server.py`](clinic_server/http_server.py) + [`render.yaml`](render.yaml) |
| 7 | Wireshark analysis of host ↔ remote server | [`scripts/capture_session.py`](scripts/capture_session.py) + [docs/report.md](docs/report.md) |
| 8–10 | Specification, layer analysis and conclusions | [docs/report.md](docs/report.md) |
| Extra | Web UI applying HCI criteria | [`web/`](web) |

The protocol itself is hand-written: `jsonrpc.py`, `transport.py` and
`mcp_client.py` import nothing but the standard library.

## Requirements

- Python 3.11 or newer
- Node.js 18 or newer
- A Gemini API key (free tier, no card needed)
- Wireshark

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

The model defaults to `gemini-3.6-flash`, which the free tier covers; set
`GEMINI_MODEL` in `.env` to use another one. If a model reports "high demand"
(HTTP 503), `gemini-3.5-flash` is a reliable alternative.

### Web interface

```powershell
python -m web.app          # then open http://127.0.0.1:5000
```

The layout puts the conversation on the left, where reading starts, and the MCP
log on the right, with every JSON-RPC message labelled by class (request, response, notification) as it arrives. Because a turn can take the better part of a minute when the model is busy, the page polls the log while it waits and names the tool being used, instead of showing a silent spinner.

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
| Clinic | `python -m clinic_server` | 6 |
| Clinic remote | Render web service over HTTP | 6 |

The two official ones are sandboxed to `workspace/`, which git ignores, so the
chatbot can never touch this repository.

### Clinic server

An industry use case: booking appointments at a medical clinic. It publishes six
tools — `list_specialties`, `find_doctors`, `get_availability`, `book_appointment`,
`get_appointment` and `cancel_appointment` — over the same stdio transport as the
official servers, because it implements the same hand-written protocol.

```
You: Necesito una cita con un pediatra el 20 de agosto por la mañana

  [tool] clinic__find_doctors {"specialty": "pediatrics"}
  [tool] clinic__get_availability {"doctor_id": "doc-004", "date": "2026-08-20"}

Assistant: Dr. Pablo Estrada tiene libre 08:00, 09:00 y 10:00. A que hora te sirve?
```

Full reference — parameters, return values, errors and raw JSON-RPC examples — in
**[docs/clinic-server.md](docs/clinic-server.md)**. It can also run on its own for
testing:

```powershell
python -m clinic_server
```

### The same server, remote

The clinic server runs over two transports without changing a line of its logic:
stdio when the host launches it as a subprocess, HTTP when it lives in the cloud.
Only the framing differs — a line on a pipe becomes the body of a POST.

```powershell
python -m clinic_server.http_server     # local, http://127.0.0.1:8000/mcp
```

Deployed on Render with the included [`render.yaml`](render.yaml), the chatbot
reaches it by setting `CLINIC_REMOTE_URL` in `.env` and enabling the
`clinic-remote` entry in `config/servers.json`. Its tools then appear as
`clinic-remote__book_appointment` and are used exactly like the local ones.
Step-by-step instructions are in
[docs/clinic-server.md](docs/clinic-server.md#deploying-to-render).

### From MCP tools to LLM functions

The two sides do not agree on how a tool is described, so the chat engine
translates. MCP servers publish full JSON Schema; Gemini accepts only a subset of
OpenAPI. Across the 32 tools we connect, the schemas use `$schema`, `title`,
`default`, `minItems` and `anyOf`, none of which Gemini takes.

`to_gemini_schema()` drops the unsupported keywords and collapses `anyOf`, which
is how MCP servers spell an optional parameter:

```jsonc
// git__git_log, as the MCP server publishes it
{"anyOf": [{"type": "string"}, {"type": "null"}], "default": null,
 "title": "Start Timestamp", "description": "Start timestamp for filtering..."}

// the same parameter, as Gemini accepts it
{"type": "string", "nullable": true,
 "description": "Start timestamp for filtering..."}
```

The registry stays provider neutral — it hands over tools exactly as MCP
describes them — and only the chat engine knows the provider's dialect. That is
why changing the LLM is a one-module change.

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


## Project layout

```
cli.py             terminal chatbot
web/               web chatbot
docs/              server specification and the final report
clinic_server/     our own MCP server (clinic appointments, stdio and http)
config/            MCP server declarations
render.yaml        blueprint that deploys the clinic server to Render
docs/              specifications of the servers we wrote
mcp_host/          the host library (JSON-RPC, transports, MCP client, log, chat engine)
scripts/           runnable checks and utilities
workspace/         sandbox the MCP servers operate on (ignored by git)
logs/              interaction logs written at runtime (ignored by git)
```