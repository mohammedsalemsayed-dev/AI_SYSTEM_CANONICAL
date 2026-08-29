"use strict";
// NEXUS control plane — Direction D "Narrative Console".
// A session is a working folder. Each message runs one orchestrator task
// (local-first, cloud escalation on verify failure); successive messages thread.
// Vanilla JS, no build step. Live updates over /api/stream (EventSource).

const $ = (id) => document.getElementById(id);
let sessionId = null;      // selected session
let sessionWs = null;      // its folder
let es = null;
let submitEnabled = false;
let stickBottom = true;
let runPoll = null;

async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString();
const fmtDur = (s) => (s < 60 ? s.toFixed(1) + "s" : Math.floor(s / 60) + "m " + Math.round(s % 60) + "s");
const ktok = (n) => (n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n));
const baseName = (p) => (p || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p;

const ACTOR = {
  REQUEST: "you", CONTRACT: "interpreter", CLARIFICATION: "interpreter",
  BRAINSTORM: "creative", PLAN: "planner", ROUTE: "router",
  ARTIFACT: "builder", VERIFICATION: "verifier", CRITIC: "critic", ERROR: "system",
};
const PRIMARY = new Set(Object.keys(ACTOR));
const GLYPH_DONE = "⏺", GLYPH_NEST = "⎿";

// ---------------------------------------------------------------- left rail
async function refreshSessions() {
  let sessions = [];
  try { ({ sessions } = await j("/api/sessions")); } catch (_) { return; }
  const el = $("sessionlist");
  el.innerHTML = sessions.length ? "" : `<div class="kv">no sessions yet</div>`;
  for (const s of sessions) {
    const d = document.createElement("div");
    d.className = "sess" + (s.session_id === sessionId ? " sel" : "");
    d.innerHTML =
      `<b>${esc(baseName(s.workspace))}</b>` +
      `<small>${esc(s.last_message || "").slice(0, 60)}</small>` +
      `<small class="meta">${esc(s.last_state || "")} · ${s.tasks} msg</small>`;
    d.onclick = () => selectSession(s.session_id, s.workspace);
    el.appendChild(d);
  }
}

function selectSession(id, ws) {
  sessionId = id;
  sessionWs = ws || sessionWs;
  showAllTurns = false;            // start each session at the recent tail
  refreshSessions();
  refreshTranscript();
}

// ---------------------------------------------------------------- centre
async function refreshTranscript() {
  if (!sessionId) return;
  let tl;
  try { tl = await j("/api/sessions/" + encodeURIComponent(sessionId)); }
  catch (_) { return; }
  sessionWs = tl.workspace || sessionWs;

  $("obj").textContent = baseName(tl.workspace) + "  —  " + (tl.tasks) + " message" + (tl.tasks === 1 ? "" : "s");
  $("obj-sub").textContent = tl.workspace;
  const v = $("verdict");
  const good = tl.verification && tl.verification.overall === "pass";
  const term = tl.state === "COMPLETED" || tl.state === "FAILED";
  v.className = "pill " + (good ? "ok" : term ? "bad" : "");
  v.textContent = good ? "verified" : term ? (tl.state || "").toLowerCase() : (tl.state ? "working" : "—");

  renderStream(tl.events);
  renderNow(tl);
  renderStatus(tl);
  renderPlan(tl.plan);
  renderCalls(tl.runs || []);
  renderCounters(tl.counters);
}

let showAllTurns = false;
const TURN_WINDOW = 80;
window.expandStream = () => { showAllTurns = true; renderStream(window.__allEvents || []); };

function renderStream(events) {
  const el = $("stream");
  el.innerHTML = "";
  if (!events || !events.length) { el.innerHTML = `<div class="empty">Send a message to start.</div>`; return; }
  window.__allEvents = events;

  // long sessions: render only the recent tail unless the user asks for all
  if (!showAllTurns && events.length > TURN_WINDOW) {
    const hidden = events.length - TURN_WINDOW;
    events = events.slice(-TURN_WINDOW);
    el.insertAdjacentHTML("beforeend",
      `<button class="show-earlier" onclick="expandStream()">` +
      `▲ show ${hidden} earlier event${hidden > 1 ? "s" : ""}</button>`);
  }

  let curNest = null;
  let lastWasAnswer = false;
  for (const e of events) {
    if (e.kind === "SYNTHESIS") {
      const d = e.data || {};
      const ans = d.answer || e.detail || "";
      const file = d.written_path
        ? `<div class="ans-file">📄 <b>${esc(d.written_path)}</b> written to your folder${d.format ? ` (${esc(d.format)})` : ""}</div>`
        : "";
      el.insertAdjacentHTML("beforeend",
        `<div class="answer"><div class="ans-h">${d.written_path ? "document" : "answer"}</div>` +
        file + `<div class="ans-b">${esc(ans)}</div></div>`);
      curNest = null; lastWasAnswer = true;
      continue;
    }
    if (e.kind === "MESSAGE") {
      const atts = (e.data && e.data.attachments) || [];
      const attHtml = atts.length
        ? `<span class="mt-att">${atts.map((a) => `📎 ${esc(a)}`).join("  ")}</span>` : "";
      el.insertAdjacentHTML("beforeend",
        `<div class="msgrow"><span class="me">you</span>` +
        `<span class="mt">${esc(e.headline || "")}${attHtml}</span>` +
        `<span class="ts">${fmtTime(e.ts)}</span></div>`);
      curNest = null;
      continue;
    }
    if (e.kind === "ESCALATION") {
      const d = e.data || {};
      const why = d.reason || d.detail || d.tried || "";
      let msg;
      if (d.rung) {                       // recovery-ladder rung, not a cloud handoff
        msg = `recovery: <b>${esc(d.rung)}</b>${why ? ` — ${esc(why)}` : ""}`;
      } else {
        const to = d.to ? `retrying with <b>${esc(d.to)}</b>` : "escalating";
        msg = `local build didn't pass — ${to}${why ? ` <span class="dim">(${esc(why)})</span>` : ""}`;
      }
      el.insertAdjacentHTML("beforeend",
        `<div class="escbar"><span>⚡</span><span>${msg}</span></div>`);
      curNest = null;
      continue;
    }
    if (e.kind === "RESULT") {
      const bad = /^error|fail/i.test(e.detail || "");
      const tail = (bad || !lastWasAnswer) ? `&nbsp;— ${esc(e.detail || "task settled")}` : "";
      el.insertAdjacentHTML("beforeend",
        `<div class="done-line${bad ? " bad" : ""}"><span class="dot"></span>` +
        `<b>${bad ? "Failed" : "Done"}</b>${tail}</div>`);
      curNest = null; lastWasAnswer = false;
      continue;
    }
    if (e.kind === "STATE") continue;

    if (PRIMARY.has(e.kind)) curNest = openTurn(el, e);
    else if (curNest) {
      curNest.insertAdjacentHTML("beforeend",
        `<div class="child">${GLYPH_NEST} ${esc(e.headline)}${e.detail ? " — " + esc(e.detail) : ""}</div>`);
    }
  }
  if (stickBottom) el.scrollTop = el.scrollHeight;
  updateJump();
}

function updateJump() {
  const el = $("stream");
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  stickBottom = atBottom;
  $("jump").hidden = atBottom;
}

function openTurn(el, e) {
  const actor = ACTOR[e.kind] || "system";
  let cls = "turn", sum = e.detail || e.headline;
  if (e.kind === "VERIFICATION") {
    const ok = e.data && e.data.overall === "pass";
    cls += ok ? " good" : " bad";
    sum = `${(e.data && e.data.tier) || "T0"} ${ok ? "PASSED" : "FAILED"}`;
  }
  if (e.kind === "CRITIC" && /reject|revise/i.test(e.detail || "")) cls += " bad";

  const wrap = document.createElement("div");
  wrap.className = cls;
  wrap.innerHTML =
    `<div class="th"><span class="glyph">${GLYPH_DONE}</span>` +
    `<span class="who">${esc(actor)}</span>` +
    `<span class="sum">${esc(sum)}</span>` +
    `<span class="ts">${fmtTime(e.ts)}</span></div>`;
  const body = bodyFor(e);
  if (body) wrap.appendChild(body);
  el.appendChild(wrap);
  return body ? body.querySelector(".body") : null;
}

function bodyFor(e) {
  const nest = document.createElement("div");
  nest.className = "nest folded";
  let inner = "";
  if (e.kind === "ARTIFACT" && e.data && e.data.diff) {
    const paths = (e.data.changed_paths || []).join(", ");
    inner = `<div class="body"><div class="child">${esc(paths)}</div>${diffHtml(e.data.diff)}</div>`;
  } else if (e.kind === "BRAINSTORM" && e.data && e.data.approaches) {
    inner = `<div class="body">` +
      e.data.approaches.map((a) => `<div class="child">• ${esc(a)}</div>`).join("") + `</div>`;
  } else if (e.detail) {
    inner = `<div class="body"><div class="child">${esc(e.detail)}</div></div>`;
  } else { return null; }

  const label = e.kind === "ARTIFACT" ? "diff" : e.kind === "BRAINSTORM" ? "approaches" : "detail";
  nest.innerHTML = `<span class="exp">▸ ${label}</span>` + inner;
  const exp = nest.querySelector(".exp");
  exp.onclick = () => {
    const folded = nest.classList.toggle("folded");
    exp.textContent = (folded ? "▸ " : "▾ ") + label;
  };
  return nest;
}

function diffHtml(diff) {
  const rows = diff.split("\n").map((ln) => {
    const c = ln.startsWith("+") && !ln.startsWith("+++") ? "add"
      : ln.startsWith("-") && !ln.startsWith("---") ? "del" : "ctx";
    return `<div class="${c}">${esc(ln || " ")}</div>`;
  });
  return `<div class="diff">${rows.join("")}</div>`;
}

function renderNow(tl) {
  const term = tl.state === "COMPLETED" || tl.state === "FAILED" || !tl.state;
  $("nowline").hidden = false;
  const wall = tl.spend && tl.spend.wall_clock_s ? " · " + fmtDur(tl.spend.wall_clock_s) : "";
  $("now-text").textContent = term
    ? `idle — send a message to continue`
    : `${(tl.state || "").toLowerCase().replace(/_/g, " ")} …${wall}`;
}

function renderStatus(tl) {
  const bar = $("statusbar");
  bar.hidden = false;
  const c = tl.counters || {};
  const st = tl.state || "—";
  const stCls = st === "COMPLETED" ? "ok" : st === "FAILED" ? "bad"
    : /STALL|RECOVER|WAIT/.test(st) ? "warn" : "";
  // did this run spend cloud credits, and why?
  const runs = tl.runs || [];
  const cloudCalls = runs.filter((r) => r.provider && r.provider !== "local");
  let costLine;
  if (cloudCalls.length) {
    const escEv = (tl.events || []).find((e) => e.kind === "ESCALATION" && (e.data || {}).to);
    const why = escEv ? ((escEv.data.reason || escEv.data.detail || "").slice(0, 70)) : "cloud model used";
    const ctok = cloudCalls.reduce((s, r) => s + (r.in || 0) + (r.out || 0), 0);
    costLine =
      `<span class="warn" title="${esc(why)}">` +
      `☁ ${cloudCalls.length} cloud call${cloudCalls.length > 1 ? "s" : ""}` +
      (ctok ? ` · ~${ktok(ctok)} tok` : "") + `</span>`;
  } else {
    costLine = `<span class="ok">100% local · no cloud spend</span>`;
  }

  bar.innerHTML =
    `<span>${esc(tl.task_class || "session")}</span>` +
    `<span class="${stCls}">${esc(st)}</span>` +
    `<span><b>${fmtDur((tl.spend && tl.spend.wall_clock_s) || 0)}</b></span>` +
    `<span><b>${c.model_runs || 0}</b> model runs</span>` +
    `<span><b>${ktok(c.in_tokens || 0)}</b>↑ <b>${ktok(c.out_tokens || 0)}</b>↓ tok</span>` +
    `<span>verify <b>${c.verify_pass || 0}</b>/<b>${(c.verify_pass || 0) + (c.verify_fail || 0)}</b></span>` +
    (c.escalations ? `<span class="warn"><b>${c.escalations}</b> escalation${c.escalations > 1 ? "s" : ""}</span>` : "") +
    costLine;
}

// ---------------------------------------------------------------- right rail
function renderPlan(steps) {
  const el = $("plan");
  if (!steps || !steps.length) { el.innerHTML = `<div class="kv">no run yet</div>`; return; }
  const g = { done: "✓", now: "⟳", wait: "○" };
  el.innerHTML = steps.map((s) =>
    `<div class="step ${s.state}"><span class="g">${g[s.state] || "○"}</span>` +
    `<span>${esc(s.label)}</span>` +
    (s.meta ? `<span class="meta">${esc(s.meta)}</span>` : "") + `</div>`
  ).join("");
}

// one row per LLM call this task made, in the order they happened.
// left→right is call sequence; the bar length is that call's wall time
// relative to the slowest call; the dot says local (on-device) vs cloud.
function renderCalls(runs) {
  const el = $("calls"), foot = $("calls-foot");
  if (!runs.length) {
    el.innerHTML = `<div class="kv">no model calls yet</div>`;
    foot.hidden = true;
    return;
  }
  const maxLat = Math.max(...runs.map((r) => r.latency_s), 0.001);
  const isLocal = (p) => /^(local|ollama|qwen|llama|mistral|phi|gemma)/i.test(p || "");
  const prettyRole = (x) => String(x || "?").replace(/_t(\d)$/, " · T$1").replace(/_/g, " ");
  el.innerHTML = runs.map((r, i) => {
    const local = isLocal(r.provider);
    const w = Math.max(3, Math.round((r.latency_s / maxLat) * 100));
    const tok = (r.in + r.out);
    const prov = r.provider || (local ? "local" : "cloud");
    return (
      `<div class="call" title="${esc(prov)} · ${r.in.toLocaleString()} in / ${r.out.toLocaleString()} out tokens">` +
        `<div class="call-top">` +
          `<span class="cdot ${local ? "local" : "cloud"}"></span>` +
          `<span class="cn">${i + 1}</span>` +
          `<span class="crole">${esc(prettyRole(r.role))}</span>` +
          `<span class="cprov">${esc(prov)}</span>` +
          `<span class="clat">${r.latency_s.toFixed(1)}s</span>` +
        `</div>` +
        `<div class="cbar"><i class="${local ? "local" : "cloud"}" style="width:${w}%"></i>` +
          `<span class="ctok">${tok >= 1000 ? (tok / 1000).toFixed(1) + "k" : tok} tok</span></div>` +
      `</div>`
    );
  }).join("");
  const total = runs.reduce((s, r) => s + r.latency_s, 0);
  foot.hidden = false;
  foot.innerHTML =
    `bar = wall time vs slowest call (${maxLat.toFixed(1)}s) · ` +
    `<span class="cdot local"></span> local &nbsp; <span class="cdot cloud"></span> cloud &nbsp;· ` +
    `${runs.length} calls, ${total.toFixed(1)}s total`;
}

function renderCounters(c) {
  c = c || {};
  $("counters").innerHTML = [
    ["events", c.events || 0],
    ["model runs", c.model_runs || 0],
    ["escalations", c.escalations || 0],
    ["verify pass / fail", `${c.verify_pass || 0} / ${c.verify_fail || 0}`],
    ["tokens in / out", `${(c.in_tokens || 0).toLocaleString()} / ${(c.out_tokens || 0).toLocaleString()}`],
  ].map(([k, v]) => `<div class="kv">${k} <b>${esc(v)}</b></div>`).join("");
}

async function refreshRoutes() {
  try {
    const r = await j("/api/routes");
    const entries = Object.entries(r.by_class || {});
    $("routes").innerHTML = entries.length
      ? entries.map(([tc, ps]) =>
          `<div class="kv">${esc(tc)} <b>${esc(Object.entries(ps).map(([p, n]) => `${p}×${n}`).join(", "))}</b></div>`
        ).join("")
      : `<div class="kv">no routing yet</div>`;
  } catch (_) {}
}

// ---------------------------------------------------------------- run state
function setHint(kind, text) {
  const el = $("runhint");
  el.className = "runhint" + (kind ? " " + kind : "");
  el.textContent = text || "";
}

function applyRunState(run) {
  const btn = $("send-btn");
  const stop = $("stop-btn");
  if (run && run.running) {
    btn.disabled = true;
    stop.hidden = false;
    stop.disabled = !!run.cancelling;
    const secs = run.started_ts ? Math.round(Date.now() / 1000 - run.started_ts) : 0;
    // first model call after an Ollama (re)start loads the model into VRAM — slow,
    // and looks like a hang. Say so while the calls panel is still empty.
    const warming = secs > 6 && !$("calls").querySelector(".call");
    setHint(run.cancelling ? "" : "go",
      run.cancelling ? "stopping…"
        : warming ? `loading model into memory… ${secs}s`
          : `working… ${secs}s`);
    if (!runPoll) runPoll = setInterval(healthProbe, 2500);
    // follow the session that's actually running
    if (run.session_id && run.session_id !== sessionId) {
      sessionId = run.session_id; sessionWs = run.workspace || sessionWs;
      refreshSessions();
    }
    refreshTranscript();
  } else {
    btn.disabled = !submitEnabled;
    stop.hidden = true;
    if (runPoll) { clearInterval(runPoll); runPoll = null; }
    if (run && run.last_error === "stopped by you") setHint("", "stopped");
    else if (run && run.last_error) setHint("err", "last run failed — " + run.last_error);
    else setHint("", "");
    refreshSessions();
    refreshTranscript();
  }
}

async function healthProbe() {
  let h = {};
  try { h = await j("/api/health"); } catch (_) {}
  submitEnabled = !!h.submit_enabled;
  $("msg").disabled = !submitEnabled;
  $("new-btn").disabled = !submitEnabled;
  $("send-btn").disabled = !submitEnabled || !!(h.run && h.run.running);
  if (!submitEnabled) setHint("err", "server is read-only (started without --allow-submit)");
  applyRunState(h.run);
}

async function loadSettings() {
  try {
    const s = await j("/api/settings");
    if (s.escalation) $("s-esc").value = s.escalation;
    if (typeof s.apply === "boolean") $("s-apply").checked = s.apply;
  } catch (_) {}
}
$("s-esc").onchange = () => {
  fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ escalation: $("s-esc").value }) }).catch(() => {});
};

// ---------------------------------------------------------------- attachments
let pendingFiles = [];  // [{name, b64, kind, bytes}]
const ATT_MAX = 12 * 1024 * 1024;

const attKind = (n) => {
  const e = (n.split(".").pop() || "").toLowerCase();
  if (["png","jpg","jpeg","gif","webp","bmp"].includes(e)) return "image";
  if (["txt","md","markdown","rst","csv","tsv","json","pdf","docx"].includes(e)) return "document";
  return "file";
};

function renderChips() {
  const el = $("chips");
  el.hidden = pendingFiles.length === 0;
  el.innerHTML = pendingFiles.map((f, i) =>
    `<span class="chip-att" title="${esc(f.kind)} · ${f.bytes} bytes">` +
    `${f.kind === "image" ? "🖼" : "📄"} ${esc(f.name)}` +
    `<button data-i="${i}" class="chip-x" aria-label="remove">×</button></span>`
  ).join("");
  el.querySelectorAll(".chip-x").forEach((b) =>
    (b.onclick = () => { pendingFiles.splice(+b.dataset.i, 1); renderChips(); }));
}

async function addFiles(fileList) {
  for (const file of fileList) {
    if (pendingFiles.some((p) => p.name === file.name)) continue;
    const total = pendingFiles.reduce((s, p) => s + p.bytes, 0);
    if (total + file.size > ATT_MAX) { setHint("err", "attachments exceed 12 MB"); break; }
    const b64 = await new Promise((res) => {
      const fr = new FileReader();
      fr.onload = () => res(String(fr.result).split(",")[1] || "");
      fr.readAsDataURL(file);
    });
    pendingFiles.push({ name: file.name, b64, kind: attKind(file.name), bytes: file.size });
  }
  renderChips();
}

$("attach-btn").onclick = () => $("attach-input").click();
$("attach-input").onchange = (e) => { addFiles(e.target.files); e.target.value = ""; };
["dragover", "dragenter"].forEach((ev) => $("composer").addEventListener(ev, (e) => {
  e.preventDefault(); $("composer").classList.add("drop");
}));
["dragleave", "drop"].forEach((ev) => $("composer").addEventListener(ev, (e) => {
  e.preventDefault(); $("composer").classList.remove("drop");
}));
$("composer").addEventListener("drop", (e) => {
  if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});

// ---------------------------------------------------------------- send
async function send() {
  if (!submitEnabled || $("send-btn").disabled) return;
  const request = $("msg").value.trim();
  const workspace = (sessionWs || $("new-ws").value.trim());
  if (!request) return;
  if (!workspace) { setHint("err", "pick a folder first (top-left)"); return; }

  $("send-btn").disabled = true;
  try {
    let attachments = [];
    if (pendingFiles.length) {
      setHint("go", `uploading ${pendingFiles.length} file(s)…`);
      const ur = await fetch("/api/attachments", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace, files: pendingFiles.map((f) => ({ name: f.name, b64: f.b64 })) }),
      });
      const ub = await ur.json().catch(() => ({}));
      if (!ur.ok) { setHint("err", ub.error || "upload failed"); $("send-btn").disabled = false; return; }
      attachments = ub.saved || [];
    }
    setHint("go", "starting…");
    const r = await fetch("/api/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, workspace, apply: $("s-apply").checked, attachments }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { setHint("err", body.error || ("send failed: " + r.status)); $("send-btn").disabled = false; return; }
    const sub = body.submitted || {};
    if (sub.session_id) { sessionId = sub.session_id; sessionWs = sub.workspace || workspace; }
    try { localStorage.setItem("nexus.ws", workspace); } catch (_) {}
    $("msg").value = ""; autosize();
    pendingFiles = []; renderChips();
    healthProbe();
  } catch (e) {
    setHint("err", "send failed: " + e.message);
    $("send-btn").disabled = false;
  }
}

$("send-btn").onclick = send;
$("stop-btn").onclick = async () => {
  $("stop-btn").disabled = true;
  setHint("", "stopping…");
  try { await fetch("/api/cancel", { method: "POST" }); } catch (_) {}
  healthProbe();
};
$("msg").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(); }
});
function autosize() {
  const t = $("msg");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 160) + "px";
}
$("msg").addEventListener("input", autosize);

$("new-btn").onclick = () => {
  const ws = $("new-ws").value.trim();
  if (!ws) { $("new-ws").focus(); return; }
  sessionWs = ws; sessionId = null;
  $("obj").textContent = baseName(ws);
  $("obj-sub").textContent = ws;
  $("stream").innerHTML = `<div class="empty">New session in <b>${esc(ws)}</b> — send your first message.</div>`;
  $("statusbar").hidden = true; $("nowline").hidden = true;
  $("msg").focus();
};

$("jump").onclick = () => { const el = $("stream"); el.scrollTop = el.scrollHeight; updateJump(); };
$("stream").addEventListener("scroll", updateJump);

// ---------------------------------------------------------------- hardware
async function refreshSystem() {
  let h;
  try { h = await j("/api/system"); } catch (_) { return; }
  renderSystem(h);
}

function bar(label, pct, warnAt) {
  const v = Math.max(0, Math.min(100, Math.round(pct)));
  const cls = v >= (warnAt || 999) ? "bad" : v >= (warnAt ? warnAt - 20 : 999) ? "warn" : "";
  return `<div class="hw"><span class="hw-k">${label}</span>` +
    `<span class="hw-track"><i class="${cls}" style="width:${v}%"></i></span>` +
    `<span class="hw-v">${v}%</span></div>`;
}

function renderSystem(h) {
  const el = $("hardware");
  if (!el) return;
  const live = h.hardware_live || {};
  const mode = (h.hardware_mode || "NORMAL").toUpperCase();
  const modeCls = mode === "NORMAL" ? "ok"
    : /EFFICIENT/.test(mode) ? "" : /EMERGENCY|PROTECTIVE/.test(mode) ? "bad" : "warn";
  const bits = [
    `<div class="hw-mode"><span class="chip ${modeCls}">${esc(mode)}</span>` +
      `<span class="chip ${h.budget_posture === "ok" ? "ok" : "warn"}">budget ${esc(h.budget_posture || "ok")}</span></div>`,
  ];
  const has = (k) => typeof live[k] === "number";
  if (has("cpu_percent")) bits.push(bar("cpu", live.cpu_percent, 90));
  if (has("ram_percent")) bits.push(bar("ram", live.ram_percent, 90));
  const gpu = typeof live.gpu_temp_c === "number";  // a real GPU probe succeeded
  if (gpu && has("vram_percent")) bits.push(bar("vram", live.vram_percent, 92));
  if (gpu && has("gpu_percent")) bits.push(bar("gpu", live.gpu_percent, 98));
  if (gpu) {
    const t = Math.round(live.gpu_temp_c);
    const cls = t >= 84 ? "bad" : t >= 75 ? "warn" : "";
    bits.push(`<div class="hw"><span class="hw-k">gpu °C</span>` +
      `<span class="hw-track"><i class="${cls}" style="width:${Math.min(100, t)}%"></i></span>` +
      `<span class="hw-v">${t}°</span></div>`);
  }
  const stab = [];
  if (h.canaries_rolled_back) stab.push(`<span class="bad">${h.canaries_rolled_back} rollback</span>`);
  if (h.quarantine_events) stab.push(`<span class="warn">${h.quarantine_events} quarantined</span>`);
  if (h.canaries_active) stab.push(`${h.canaries_active} canary`);
  const liveMsg = has("cpu_percent")
    ? (live.source === "live-degraded" ? "cpu/ram only" : "live")
    : "mode only — no telemetry";
  bits.push(`<div class="hw-foot">${stab.length ? stab.join(" · ") : "stable"} · <span class="src">${esc(liveMsg)}</span></div>`);
  el.innerHTML = bits.join("");
}

// ---------------------------------------------------------------- wiring
function refreshAll() {
  refreshSessions().catch(() => {});
  refreshTranscript().catch(() => {});
  refreshRoutes().catch(() => {});
  refreshSystem().catch(() => {});
}

function connect() {
  if (es) es.close();
  es = new EventSource("/api/stream");
  let pending = null;
  const bump = () => { clearTimeout(pending); pending = setTimeout(refreshAll, 200); };
  ["STATE", "RESULT", "AGENT_MESSAGE", "VERIFICATION", "ROUTE", "HARDWARE", "TELEMETRY",
   "PROGRESS", "ESCALATION", "BUDGET", "CONTRACT", "PLAN", "ARTIFACT", "CRITIC", "BRAINSTORM",
   "REQUEST", "MODEL_RUN", "SYNTHESIS", "AUTHORING"]
    .forEach((k) => es.addEventListener(k, bump));
  es.onerror = () => { es.close(); setTimeout(connect, 2000); };
}

(function init() {
  try { $("new-ws").value = localStorage.getItem("nexus.ws") || ""; } catch (_) {}
  loadSettings();
  healthProbe();
  refreshAll();
  connect();
  setInterval(refreshSystem, 3000);  // hardware keeps ticking even when idle
})();
