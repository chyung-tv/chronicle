const $ = (sel) => document.querySelector(sel);
const colors = ["#e7d8b8", "#8eb3b0", "#d4a574", "#c97b84"];

let state = null;
let busy = false;

function setBusy(v) {
  busy = v;
  for (const id of ["btn-tick", "btn-day", "btn-reset"]) {
    $(`#${id}`).disabled = v;
  }
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function refresh() {
  state = await api("/api/state");
  render();
}

function render() {
  $("#title").textContent = state.title || "Play Out";
  $("#clock").textContent = `Day ${state.day} · ${state.time_label} · scene ${state.scene + 1}/${state.scenes_per_day} · storm clock: ${state.clock?.note || ""}`;
  $("#weather").textContent = state.weather || "";
  $("#llm-mode").textContent =
    state.llm_mode === "live" ? state.llm_model || "openrouter" : "mock llm";
  renderMap();
  renderTape();
  renderDiaries();
  renderChapters();
  renderIntents();
  renderPeople();
}

function renderMap() {
  const svg = $("#map");
  const loc = Object.fromEntries(state.locations.map((l) => [l.id, l]));
  const edges = state.edges
    .map((e) => {
      const a = loc[e.a];
      const b = loc[e.b];
      if (!a || !b || e.a > e.b) return "";
      return `<line class="edge" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`;
    })
    .join("");
  const nodes = state.locations
    .map((l) => {
      const cls = l.intact ? "node-circle" : "node-ruined";
      const people = l.actors
        .map((a, i) => {
          const c = colors[i % colors.length];
          const ox = (i - (l.actors.length - 1) / 2) * 14;
          const faded = a.alive ? 1 : 0.35;
          return `<circle class="actor-dot" cx="${l.x + ox}" cy="${l.y - 22}" r="6" fill="${c}" opacity="${faded}"><title>${a.name}</title></circle>`;
        })
        .join("");
      return `<g>
        <circle class="${cls}" cx="${l.x}" cy="${l.y}" r="16" />
        <text class="node-label" x="${l.x}" y="${l.y + 32}" text-anchor="middle">${l.name}</text>
        ${people}
      </g>`;
    })
    .join("");
  svg.innerHTML = edges + nodes;
}

function renderTape() {
  const ol = $("#tape");
  ol.innerHTML = (state.events || [])
    .slice()
    .reverse()
    .map(
      (e) => `<li class="kind-${e.kind}">
        <div class="meta">D${e.day} ${e.kind} #${e.id}</div>
        <div>${esc(e.summary)}</div>
      </li>`
    )
    .join("");
}

function renderDiaries() {
  const el = $("#tab-diaries");
  el.innerHTML = state.actors
    .map((a) => {
      const entries = (state.diaries[a.id] || [])
        .map((d) => `<p class="entry">D${d.day}: ${esc(d.text)}</p>`)
        .join("");
      return `<h3>${esc(a.name)}</h3>${entries || "<p class='entry'>(blank)</p>"}`;
    })
    .join("");
}

function renderChapters() {
  const el = $("#tab-chapters");
  if (!state.chapters.length) {
    el.innerHTML = "<p class='entry'>Chapters appear when a day rolls over.</p>";
    return;
  }
  el.innerHTML = state.chapters
    .map(
      (c) => `<h3>Day ${c.day} · ${esc(c.pov)} · ${c.tags.join(", ")}</h3>
      <div class="chapter">${esc(c.text)}</div>`
    )
    .join("");
}

function renderIntents() {
  const el = $("#tab-intents");
  if (!state.intents.length) {
    el.innerHTML = "<p class='entry'>No active steer. Submit a future you want to become likely.</p>";
    return;
  }
  el.innerHTML = state.intents
    .map((i) => {
      const rungs = (i.campaign.rungs || [])
        .map((r) => `${r.id}: ${r.status}`)
        .join(" · ");
      return `<div class="intent">
        <div class="status ${i.status}">${i.status}</div>
        <p>${esc(i.text)}</p>
        <p class="entry">${esc(i.campaign.summary || "")}</p>
        <p class="entry">${esc(rungs)}</p>
      </div>`;
    })
    .join("");
}

function renderPeople() {
  const el = $("#tab-people");
  el.innerHTML = state.actors
    .map(
      (a) => `<h3>${esc(a.name)} ${a.alive ? "" : "(dead)"} ${a.injured ? "· injured" : ""}</h3>
        <p class="entry"><b>At</b> ${esc(a.location_id)} · <b>Mood</b> ${esc(a.mood)}</p>
        <p class="entry"><b>Goal</b> ${esc(a.goal)}</p>
        <p class="entry"><b>Want</b> ${esc(a.want)}</p>
        <p class="entry"><b>Secret</b> ${esc(a.secret)}</p>
        <p class="entry"><b>Carrying</b> ${a.inventory.map((o) => o.name).join(", ") || "nothing"}</p>`
    )
    .join("");
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.remove("on"));
    btn.classList.add("on");
    document.querySelectorAll(".tab-body").forEach((t) => t.classList.add("hidden"));
    $(`#tab-${btn.dataset.tab}`).classList.remove("hidden");
  });
});

$("#btn-tick").addEventListener("click", async () => {
  setBusy(true);
  try {
    await api("/api/tick", { method: "POST" });
    await refresh();
  } finally {
    setBusy(false);
  }
});

$("#btn-day").addEventListener("click", async () => {
  setBusy(true);
  try {
    await api("/api/day", { method: "POST" });
    await refresh();
  } finally {
    setBusy(false);
  }
});

$("#btn-reset").addEventListener("click", async () => {
  if (!confirm("This wipes the tape and starts Harbor's End again.")) return;
  setBusy(true);
  try {
    await api("/api/reset", { method: "POST" });
    await refresh();
  } finally {
    setBusy(false);
  }
});

$("#form-inject").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const input = ev.target.inject;
  const text = input.value.trim();
  if (!text) return;
  setBusy(true);
  try {
    await api("/api/inject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    input.value = "";
    await refresh();
  } finally {
    setBusy(false);
  }
});

$("#form-steer").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const input = ev.target.steer;
  const text = input.value.trim();
  if (!text) return;
  setBusy(true);
  try {
    await api("/api/steer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    input.value = "";
    await refresh();
  } finally {
    setBusy(false);
  }
});

refresh().catch((err) => {
  $("#clock").textContent = "Could not load world: " + err.message;
});
