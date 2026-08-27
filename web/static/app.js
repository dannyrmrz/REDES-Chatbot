/* Page logic: talk to the small JSON API in web/app.py and render the result.
 * All the conversation and MCP work happens on the server, in the same engine
 * the terminal frontend uses; this file only draws it.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const messages = $("messages"), logBox = $("log"), input = $("input");

let busy = false;

/* ---------- rendering ---------- */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scroll(box) { box.scrollTop = box.scrollHeight; }

function addMessage(text, variant) {
  messages.appendChild(el("div", `msg msg--${variant}`, text));
  scroll(messages);
}

function addToolCalls(calls) {
  if (!calls.length) return;
  const wrap = el("div", "tools");
  for (const call of calls) {
    const line = el("div", "tool");
    line.appendChild(el("b", null, call.name));
    line.appendChild(document.createTextNode(" " + JSON.stringify(call.arguments)));
    wrap.appendChild(line);
  }
  messages.appendChild(wrap);
  scroll(messages);
}

/** Placeholder shown while the turn is in flight, so the user is never
 *  left wondering whether the click registered. */
function addThinking() {
  const node = el("div", "thinking");
  node.appendChild(el("i"));
  node.appendChild(el("span", null, "Pensando…"));
  messages.appendChild(node);
  scroll(messages);
  return node;
}

function addLogEntries(entries) {
  for (const entry of entries) {
    const node = el("div", `entry entry--${entry.direction}`);
    const head = el("div", "entry__head");
    head.appendChild(el("span", "arrow", entry.direction === "sent" ? "-->" : "<--"));
    head.appendChild(el("span", "entry__time", entry.time));
    head.appendChild(el("span", "entry__server", entry.server));
    head.appendChild(el("span", `kind kind--${entry.kind}`, entry.kind));
    head.appendChild(el("span", "entry__method", entry.method || ""));
    node.appendChild(head);

    const payload = JSON.stringify(entry.payload);
    node.appendChild(el("pre", "entry__payload",
      payload.length > 260 ? payload.slice(0, 260) + "…" : payload));
    logBox.appendChild(node);
  }
  if (entries.length) {
    const total = logBox.querySelectorAll(".entry").length;
    $("log-count").textContent = `${total} mensaje${total === 1 ? "" : "s"}`;
    scroll(logBox);
  }
}

/* ---------- API ---------- */

async function loadState() {
  try {
    const state = await (await fetch("/api/state")).json();
    const chips = $("servers");
    chips.textContent = "";

    let healthy = 0;
    for (const [name, status] of Object.entries(state.servers)) {
      const ok = /tools$/.test(status);
      if (ok) healthy++;
      // Never colour alone: the chip always spells the status out.
      chips.appendChild(el("span", `chip ${ok ? "" : "chip--error"}`,
        `${name}: ${status}`));
    }
    chips.appendChild(el("span", "chip chip--muted", state.model));
    $("health").className = "dot " + (healthy ? "dot--ok" : "dot--error");

    logBox.textContent = "";
    if (state.log.length) addLogEntries(state.log);
    else logBox.appendChild(el("div", "log--empty",
      "Aún no hay mensajes. Aparecerán aquí en cuanto el modelo use una herramienta."));

    messages.textContent = "";
    addMessage(
      "Hola. Puedo responder preguntas y también usar los servidores MCP conectados " +
      "para trabajar con archivos, con git y con las citas de la clínica.",
      "empty");
  } catch (err) {
    $("health").className = "dot dot--error";
    $("servers").textContent = "";
    $("servers").appendChild(el("span", "chip chip--error", "sin conexión con el servidor"));
  }
}

function logCount() { return logBox.querySelectorAll(".entry").length; }

/** Draw whatever MCP traffic the server has beyond `since`, and report how far
 *  we got. Shared by the live poll and the final catch-up so neither of them
 *  has to reason about duplicates. */
async function drainLog(since, label) {
  const data = await (await fetch(`/api/log?since=${since}`)).json();
  if (data.log.length) {
    addLogEntries(data.log);
    const call = data.log.filter((e) => e.direction === "sent" &&
                                        e.method === "tools/call").pop();
    if (call && label) {
      const name = call.payload?.params?.name;
      label.textContent = name ? `Usando ${name}…` : "Trabajando…";
    }
  }
  return data.total;
}

/** A turn can take the better part of a minute when the model is busy. Rather
 *  than leave the page silent, show each MCP call as it happens — the same
 *  information the terminal frontend prints live. */
function followProgress(thinking) {
  const label = thinking.querySelector("span");
  let seen = logCount();
  const timer = setInterval(async () => {
    try { seen = await drainLog(seen, label); }
    catch (err) { /* the turn itself will report the real failure */ }
  }, 1500);
  return () => { clearInterval(timer); return seen; };
}

async function send(text) {
  if (busy || !text.trim()) return;
  busy = true;
  $("send").disabled = true;
  input.value = "";
  input.style.height = "auto";
  addMessage(text, "user");
  const thinking = addThinking();
  const stopFollowing = followProgress(thinking);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await response.json();
    const seen = stopFollowing();
    thinking.remove();
    addToolCalls(data.tools || []);
    await drainLog(seen, null);  // catch up on anything the poll missed
    // Errors are recoverable: say what failed and leave the input usable.
    addMessage(data.error ? `No pude completar la petición. ${data.error}` : data.reply,
               data.error ? "error" : "bot");
  } catch (err) {
    thinking.remove();
    addMessage("No pude contactar al servidor local. ¿Sigue corriendo?", "error");
  } finally {
    busy = false;
    $("send").disabled = false;
    input.focus();
  }
}

/* ---------- events ---------- */

$("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  send(input.value);
});

// Enter sends, Shift+Enter makes a new line: the convention users expect.
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send(input.value);
  }
});

// Grow the box with the text instead of hiding it behind a scrollbar.
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
});

$("suggestions").addEventListener("click", (event) => {
  const button = event.target.closest(".suggestion");
  if (button) send(button.textContent);
});

$("reset").addEventListener("click", async () => {
  await fetch("/api/reset", { method: "POST" });
  messages.textContent = "";
  addMessage("Contexto reiniciado. La conversación empieza de nuevo.", "empty");
  input.focus();
});

loadState();
