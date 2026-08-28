"use strict";
// NEXUS desktop shell — a real client of the event-stream API (MILESTONE_H_PLAN.md §2).
// No build step; vanilla JS. Subscribes to /api/stream and re-pulls the panels.

const $ = (id) => document.getElementById(id);
let selected = null;
let es = null;

async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

async function refreshTasks() {
  const { tasks } = await j("/api/tasks");
  const el = $("tasklist");
  el.innerHTML = "";
  for (const t of tasks) {
    const d = document.createElement("div");
    d.className = "task" + (t.task_id === selected ? " sel" : "");
    d.innerHTML = `<b>${t.objective || t.task_id}</b><small>${t.state} · ${t.task_class || "?"}</small>`;
    d.onclick = () => { selected = t.task_id; refreshTimeline(); refreshTasks(); refreshAgents(); };
    el.appendChild(d);
  }
  if (!selected && tasks.length) { selected = tasks[0].task_id; refreshTimeline(); refreshAgents(); }
}

async function refreshTimeline() {
  if (!selected) return;
  const tl = await j("/api/tasks/" + encodeURIComponent(selected));
  $("task-objective").textContent = tl.objective || tl.task_id;
  $("task-class").textContent = `${tl.task_class || ""} · ${tl.state} · ${tl.spend.model_runs} model runs · ${tl.spend.wall_clock_s}s`;
  const el = $("timeline");
  el.innerHTML = "";
  for (const e of tl.events) {
    const r = document.createElement("div");
    r.className = "row" + (e.kind === "STATE" ? " state" : "");
    r.innerHTML = `<span class="k">${fmtTime(e.ts)}</span><span class="h">${e.headline}</span><span class="d">${e.detail || ""}</span>`;
    el.appendChild(r);
  }
  el.scrollTop = el.scrollHeight;
}

async function refreshAgents() {
  if (!selected) return;
  const { roles } = await j("/api/tasks/" + encodeURIComponent(selected) + "/agents");
  const el = $("agents");
  el.innerHTML = "";
  for (const a of roles) {
    const d = document.createElement("div");
    d.className = "agent" + (a.active ? "" : " off");
    const line = a.active ? `${a.intent || ""} — ${(a.claims || []).join("; ")}` : "idle";
    d.innerHTML = `<b>${a.role}</b><small>${line}</small>`;
    el.appendChild(d);
  }
}

async function refreshHealth() {
  const h = await j("/api/system");
  $("health-strip").innerHTML =
    `<span class="m-${h.hardware_mode}">HW ${h.hardware_mode}</span>` +
    `<span class="${h.budget_posture === "ok" ? "ok" : h.budget_posture}">BUDGET ${h.budget_posture}</span>` +
    `<span>${h.canaries_active} canary</span>` +
    `<span class="${h.canaries_rolled_back ? "bad" : ""}">${h.canaries_rolled_back} rollback</span>` +
    `<span class="${h.quarantine_events ? "warn" : ""}">${h.quarantine_events} quarantined</span>`;
}

async function refreshMetrics() {
  const m = await j("/api/metrics");
  const rows = [
    ["tasks", m.tasks],
    ["rework rate", (m.rework_rate * 100).toFixed(0) + "%"],
    ["escalation freq", m.escalation_frequency.toFixed(2)],
    ["budget-exhaust", (m.budget_exhaustion_rate * 100).toFixed(0) + "%"],
    ["quarantines", m.quarantine_events],
  ];
  for (const [k, v] of Object.entries(m.success_rate_by_class || {})) {
    rows.push(["ok · " + k, (v * 100).toFixed(0) + "%"]);
  }
  for (const [k, v] of Object.entries(m.verify_tier_distribution || {})) {
    rows.push(["verify " + k, v]);
  }
  $("metrics").innerHTML = rows.map(([k, v]) => `<div class="kv">${k} <b>${v}</b></div>`).join("");
}

async function refreshRoutes() {
  const r = await j("/api/routes");
  const el = $("routes");
  el.innerHTML = "";
  for (const [tc, providers] of Object.entries(r.by_class || {})) {
    const parts = Object.entries(providers).map(([p, n]) => `${p}×${n}`).join(", ");
    el.innerHTML += `<div class="kv">${tc} <b>${parts}</b></div>`;
  }
  if (!Object.keys(r.by_class || {}).length) el.innerHTML = `<div class="kv">no routing yet</div>`;
}

function refreshAll() {
  refreshTasks().catch(() => {});
  refreshTimeline().catch(() => {});
  refreshAgents().catch(() => {});
  refreshHealth().catch(() => {});
  refreshMetrics().catch(() => {});
  refreshRoutes().catch(() => {});
}

function connect() {
  if (es) es.close();
  es = new EventSource("/api/stream");
  let pending = null;
  es.onmessage = es.onerror = null;
  es.addEventListener("open", () => {});
  const bump = () => { clearTimeout(pending); pending = setTimeout(refreshAll, 150); };
  ["STATE", "RESULT", "AGENT_MESSAGE", "VERIFICATION", "ROUTE", "HARDWARE", "CANARY",
   "PROGRESS", "ESCALATION", "EXPERIENCE_TRANSITION", "BUDGET", "CONTRACT", "PLAN"]
    .forEach((k) => es.addEventListener(k, bump));
  es.onerror = () => { es.close(); setTimeout(connect, 2000); };
}

$("submit-btn").onclick = async () => {
  const request = $("submit-request").value.trim();
  const workspace = $("submit-workspace").value.trim();
  if (!request || !workspace) return;
  try {
    await j("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, workspace }),
    });
    $("submit-request").value = "";
    refreshAll();
  } catch (e) {
    alert("submit failed: " + e.message + "\n(server may be read-only; start with --allow-submit)");
  }
};

refreshAll();
connect();
setInterval(refreshHealth, 5000);
