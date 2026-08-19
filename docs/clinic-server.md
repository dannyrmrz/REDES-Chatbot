# Clinic MCP Server — Specification

Own MCP server for the CC3067 Networks project. It models an industry use case:
**appointment booking for a medical clinic**, the job a receptionist does when a
patient calls to ask who treats their problem and when they can be seen.

The chatbot uses it exactly like the official Anthropic servers, because it speaks
the same protocol — hand-written JSON-RPC 2.0, no MCP SDK.

- Server name: `clinic-mcp-server`
- Version: `1.0.0`
- Protocol version: `2025-06-18`
- Capabilities: `{"tools": {"listChanged": false}}`

## Running it

The same server runs over two transports. The MCP session is identical in both;
only the framing changes.

| Mode | Command | Transport |
| --- | --- | --- |
| Through the chatbot | `python cli.py` (declared in `config/servers.json`) | stdio |
| Standalone, for testing | `python -m clinic_server` | stdio |
| Local HTTP | `python -m clinic_server.http_server` | http |
| Deployed | Render web service | http |

Over stdio it is a subprocess: the host launches it and speaks over the pipes.
Over HTTP it is a network service listening on a port.

## Transport and framing

**stdio.** One JSON-RPC 2.0 message per line, UTF-8, terminated by `\n`:

- `stdin` — requests and notifications from the host
- `stdout` — responses only (nothing else is ever printed here)
- `stderr` — diagnostics, ignored by the protocol

Messages must not contain raw newlines, which is why they are serialised compactly.

## HTTP endpoints

Used by the remote deployment (`clinic_server/http_server.py`).

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/mcp` | Carries one JSON-RPC message in the body |
| `GET` | `/health` | Health check, returns server info as JSON |
| `GET` | `/` | Same as `/health` |

Status codes chosen on purpose, because they map to the JSON-RPC message classes
and are visible in a packet capture:

| Status | Meaning |
| --- | --- |
| `200` | A request was answered; the body is the JSON-RPC response |
| `202` | A notification was accepted; there is no body, because none is expected |
| `400` | The body was not valid JSON-RPC; the body carries a `-32700` error |
| `404` | Unknown path |

Requests carry `Content-Type: application/json`, and the connection is HTTP/1.1
keep-alive, so a whole MCP session travels over one TCP connection.

Call it by hand with `curl.exe` (in PowerShell plain `curl` is an alias of
`Invoke-WebRequest`, which does not take these flags):

```bash
curl.exe -X POST https://your-service.onrender.com/mcp -H "Content-Type: application/json" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}"
```

## Protocol methods

| Method | Type | Purpose |
| --- | --- | --- |
| `initialize` | request → response | Version and capability handshake |
| `notifications/initialized` | notification | Host signals the session is live; no answer |
| `tools/list` | request → response | Returns the six tools and their JSON Schemas |
| `tools/call` | request → response | Runs one tool |
| `ping` | request → response | Liveness check, returns `{}` |
| anything else | request → error | JSON-RPC error `-32601` (method not found) |

### Handshake

```json
--> {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"redes-mcp-host","version":"0.1.0"}}}
<-- {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"clinic-mcp-server","version":"1.0.0"}}}
--> {"jsonrpc":"2.0","method":"notifications/initialized"}
```

## Tools

All tools return their payload as JSON inside a text content block:

```json
{"content": [{"type": "text", "text": "<JSON payload>"}]}
```

A business failure is **not** a JSON-RPC error. The response is successful and carries
`"isError": true` with a message explaining what to do instead, so the model can
correct itself and retry. Protocol failures (malformed JSON, unknown method) do use
JSON-RPC error objects.

### `list_specialties`

Specialties offered by the clinic. Call it first when the patient does not know
which specialty they need.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| *(none)* | | | |

Returns an array of `{id, name, description}`.

### `find_doctors`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `specialty` | string | no | Specialty id (`cardiology`) or display name (`Cardiologia`) |
| `name` | string | no | Part of the name of the doctor, case insensitive |

With no parameters it returns every doctor. Returns an array of
`{id, name, specialty, office, days, hours}`.

Errors: unknown specialty, listing the valid ids.

### `get_availability`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `doctor_id` | string | **yes** | Id obtained from `find_doctors` |
| `date` | string | **yes** | `YYYY-MM-DD` |

Returns `{doctor_id, doctor, date, weekday, available}` where `available` lists the
free `HH:MM` slots — the doctor's working hours minus the confirmed appointments. If
the doctor does not work that weekday, `available` is empty and a `note` explains why.

Errors: unknown doctor, malformed date.

### `book_appointment`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `doctor_id` | string | **yes** | Id obtained from `find_doctors` |
| `date` | string | **yes** | `YYYY-MM-DD` |
| `time` | string | **yes** | `HH:MM`, must appear in `get_availability` |
| `patient_name` | string | **yes** | Full name of the patient |
| `reason` | string | no | Reason for the visit |

Returns the appointment, including the `code` the patient needs afterwards:

```json
{
  "code": "APT-24DBE9",
  "doctor_id": "doc-004",
  "doctor": "Dr. Pablo Estrada",
  "specialty": "pediatrics",
  "office": "C-010",
  "date": "2026-08-20",
  "time": "08:00",
  "patient_name": "Daniela Ramirez",
  "reason": "Control anual",
  "status": "confirmed",
  "created_at": "2026-08-19T09:41:45"
}
```

Errors: unknown doctor, malformed date, slot already taken or outside working hours,
empty patient name.

### `get_appointment`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `code` | string | **yes** | Confirmation code, e.g. `APT-24DBE9` |

Returns the appointment. Errors: unknown code.

### `cancel_appointment`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `code` | string | **yes** | Confirmation code |

Sets `status` to `cancelled`, stamps `cancelled_at` and releases the slot back into
availability. Errors: unknown code, appointment already cancelled.

## Data

No database, two JSON files under `clinic_server/data/`:

| File | Contents | In git |
| --- | --- | --- |
| `clinic.json` | Catalogue: clinic, 4 specialties, 6 doctors with schedules | yes |
| `appointments.json` | Booked appointments, written on first booking | no (runtime state) |

A doctor declares `days` (weekday names) and `hours` (slots). Availability is derived,
never stored, so it can never drift out of sync with the bookings.

## Usage examples

### Through the chatbot

```
You: Necesito una cita con un pediatra el 20 de agosto por la manana

  [tool] clinic__find_doctors {"specialty": "pediatrics"}
  [tool] clinic__get_availability {"doctor_id": "doc-004", "date": "2026-08-20"}

Assistant: Dr. Pablo Estrada tiene libre 08:00, 09:00 y 10:00. A que hora te sirve?

You: A las 9, a nombre de Daniela Ramirez

  [tool] clinic__book_appointment {"doctor_id": "doc-004", "date": "2026-08-20", ...}

Assistant: Lista. Cita el jueves 20 a las 09:00 con Dr. Pablo Estrada, consultorio
C-010. Tu codigo es APT-24DBE9.
```

### Raw JSON-RPC

Start `python -m clinic_server` and paste these lines one at a time:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_specialties","arguments":{}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_availability","arguments":{"doctor_id":"doc-004","date":"2026-08-20"}}}
```

### A tool error

```json
--> {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"get_availability","arguments":{"doctor_id":"doc-999","date":"2026-08-20"}}}
<-- {"jsonrpc":"2.0","id":5,"result":{"content":[{"type":"text","text":"Unknown doctor 'doc-999'. Use find_doctors to get a valid id."}],"isError":true}}
```

Note the successful response with `isError`, as opposed to a malformed request:

```json
--> {"jsonrpc":"2.0","id":6,"method":"does/not/exist"}
<-- {"jsonrpc":"2.0","id":6,"error":{"code":-32601,"message":"unknown method 'does/not/exist'"}}
```

## Deploying to Render

The repository already contains [`render.yaml`](../render.yaml).

1. Push the repository to GitHub.
2. On <https://render.com>, sign in with GitHub and grant access to the repository.
3. **New > Blueprint**, pick the repository, and Render reads `render.yaml`:
   it builds with `python --version` (the server needs no dependencies) and starts
   `python -m clinic_server.http_server`.
4. Wait for the deploy to finish and copy the service URL,
   `https://<name>.onrender.com`.
5. Check it answers: open `https://<name>.onrender.com/health` in a browser.
6. In `.env`, set `CLINIC_REMOTE_URL=https://<name>.onrender.com/mcp`.
7. In `config/servers.json`, set `"enabled": true` on the `clinic-remote` entry.

Run `python cli.py` again and the chatbot connects to the remote server exactly as
it does to the local one, with the tools prefixed `clinic-remote__`.

Notes about the free plan:

- The service sleeps after about 15 minutes without traffic, and the next request
  wakes it up, which can take close to a minute. `HttpTransport` therefore uses a
  60 second timeout.
- Appointments booked remotely live in the container filesystem and are lost when
  the service restarts. That is acceptable here: the point is the protocol, not
  the persistence.

## Source layout

| File | Responsibility |
| --- | --- |
| `clinic_server/server.py` | Protocol: tool schemas, message dispatch, stdio loop |
| `clinic_server/store.py` | Domain: doctors, availability rules, appointments |
| `clinic_server/__main__.py` | Entry point for `python -m clinic_server` (stdio) |
| `clinic_server/http_server.py` | The same server over HTTP, for the deployment |
| `clinic_server/data/clinic.json` | Catalogue |

The split is deliberate: `store.py` holds the clinic rules and knows nothing about
JSON-RPC, and `server.py` handles messages without knowing how they arrived. That
is why the HTTP deployment reuses both without a single change to either: it only
replaces the framing.
