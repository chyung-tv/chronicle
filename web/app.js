const $ = (sel) => document.querySelector(sel);
const colors = ["#e7d8b8", "#8eb3b0", "#d4a574", "#c97b84"];

const KIND = {
  wait: "等候",
  move: "前往",
  speak: "對白",
  take: "取物",
  drop: "放下",
  examine: "察看",
  attack: "襲擊",
  kill: "殺死",
  attempted_kill: "欲殺不成",
  world: "世變",
  world_kill: "世變致死",
  steer_motive: "導引·動機",
  steer_means: "導引·手段",
  steer_opportunity: "導引·時機",
  steer_escalation: "導引·加壓",
  failed_move: "未成行",
  failed_speak: "未成言",
  failed_attack: "未成擊",
  write_note: "寫紙",
};

const STATUS = {
  brewing: "醞釀中",
  attempted: "已著手",
  succeeded: "已成",
  failed: "失敗",
  pending: "未發",
  injected: "已注入",
  done: "已畢",
};

const RUNG = {
  motive: "動機",
  means: "手段",
  opportunity: "時機",
  escalation: "加壓",
};

let state = null;
let busy = false;
let selectedActor = null;

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
  if (selectedActor && !state.actors.some((a) => a.id === selectedActor)) {
    selectedActor = null;
  }
  if (!selectedActor && state.actors.length) selectedActor = state.actors[0].id;
  render();
}

function locName(id) {
  const l = (state.locations || []).find((x) => x.id === id);
  return l ? l.name : id;
}

function actorName(id) {
  const a = (state.actors || []).find((x) => x.id === id);
  return a ? a.name : id;
}

function kindLabel(kind) {
  return KIND[kind] || kind;
}

function statusLabel(status) {
  return STATUS[status] || status;
}

function beatClock() {
  const plan = state.day_plan;
  const slots = plan?.slots || [];
  const k = Math.min((plan?.cursor || 0) + 1, slots.length || 1);
  const n = slots.length;
  const beat = n ? `第 ${k}/${n} 次` : "未排今日";
  return `第${state.day}日 · ${beat} · 風期：${state.clock?.note || ""}`;
}

function render() {
  $("#title").textContent = state.title || "演繹";
  $("#clock").textContent = beatClock();
  $("#weather").textContent = state.weather || "";
  $("#llm-mode").textContent =
    state.llm_mode === "live" ? state.llm_model || "openrouter" : "模擬語言模型";
  renderStrip();
  renderMap();
  renderTape();
  renderChapters();
  renderCast();
  renderIntents();
}

function renderStrip() {
  const ol = $("#run-strip");
  const plan = state.day_plan;
  if (!plan || !plan.slots || !plan.slots.length) {
    ol.innerHTML = `<li>尚未開今日之序。按「演一步」即黎明排程。</li>`;
    return;
  }
  const cur = plan.cursor || 0;
  const talking = state.encounter && state.encounter.active;
  ol.innerHTML = plan.slots
    .map((s, i) => {
      const cls = [
        i === cur ? "current" : "",
        s.status === "done" || i < cur ? "done" : "",
        s.kind === "event" ? "event" : "",
        s.encounter || (talking && i === cur) ? "encounter" : "",
      ]
        .filter(Boolean)
        .join(" ");
      let label;
      if (s.kind === "event") {
        label = s.source === "steer" ? `導引·${RUNG[s.rung_id] || s.rung_id || "世變"}` : "世變";
      } else {
        label = actorName(s.actor_id);
      }
      if ((s.encounter || (talking && i === cur)) && s.kind === "actor") label += " · 對話中";
      return `<li class="${cls}">${esc(label)}</li>`;
    })
    .join("");
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
          return `<circle class="actor-dot" data-actor="${a.id}" cx="${l.x + ox}" cy="${l.y - 22}" r="6" fill="${c}" opacity="${faded}"><title>${a.name}</title></circle>`;
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
  svg.querySelectorAll("[data-actor]").forEach((el) => {
    el.addEventListener("click", () => {
      selectedActor = el.getAttribute("data-actor");
      renderCast();
    });
  });
}

function renderTape() {
  const ol = $("#tape");
  const events = (state.events || []).slice().reverse();
  ol.innerHTML = events
    .map((e, i) => {
      const prev = events[i + 1];
      const held =
        prev &&
        prev.day === e.day &&
        prev.scene === e.scene &&
        (e.kind === "speak" || prev.kind === "speak" || e.kind === "attack" || prev.kind === "attack");
      return `<li class="kind-${e.kind}${held ? " held" : ""}">
        <div class="meta">第${e.day}日 ${kindLabel(e.kind)} #${e.id}</div>
        <div>${esc(e.summary)}</div>
      </li>`;
    })
    .join("");
}

function renderChapters() {
  const el = $("#tab-chapters");
  if (!state.chapters.length) {
    el.innerHTML = "<p class='entry'>章回於一日終了時寫成。</p>";
    return;
  }
  el.innerHTML = state.chapters
    .map(
      (c) => `<h3>第${c.day}日 · ${esc(actorName(c.pov))} · ${c.tags.join("、")}</h3>
      <div class="chapter">${esc(c.text)}</div>`
    )
    .join("");
}

function renderIntents() {
  const el = $("#god-intents");
  if (!state.intents.length) {
    el.innerHTML = "<p class='entry'>尚無導引。寫下一則你希望變得可能的未來。</p>";
    return;
  }
  el.innerHTML = state.intents
    .map((i) => {
      const rungs = (i.campaign.rungs || [])
        .map((r) => `${RUNG[r.id] || r.id}：${statusLabel(r.status)}`)
        .join(" · ");
      return `<div class="intent">
        <div class="status ${i.status}">${statusLabel(i.status)}</div>
        <p>${esc(i.text)}</p>
        <p class="entry">${esc(i.campaign.summary || "")}</p>
        <p class="entry">${esc(rungs)}</p>
      </div>`;
    })
    .join("");
}

function renderCast() {
  const nav = $("#cast-nav");
  nav.innerHTML = state.actors
    .map(
      (a) =>
        `<button type="button" data-actor="${a.id}" class="${a.id === selectedActor ? "on" : ""}">${esc(a.name)}</button>`
    )
    .join("");
  nav.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedActor = btn.dataset.actor;
      renderCast();
    });
  });
  const a = state.actors.find((x) => x.id === selectedActor) || state.actors[0];
  if (!a) {
    $("#cast-sheet").innerHTML = "";
    return;
  }
  const entries = (state.diaries[a.id] || [])
    .map((d) => `<p class="entry">第${d.day}日：${esc(d.text)}</p>`)
    .join("");
  $("#cast-sheet").innerHTML = `
    <h3>${esc(a.name)} ${a.alive ? "" : "（已歿）"} ${a.injured ? "· 帶傷" : ""}</h3>
    <p class="entry"><b>所在</b> ${esc(locName(a.location_id))} · <b>心境</b> ${esc(a.mood)}</p>
    <p class="entry"><b>眼前之願</b> ${esc(a.goal)}</p>
    <p class="entry"><b>深願</b> ${esc(a.want)}</p>
    <p class="entry"><b>秘密</b> ${esc(a.secret)}</p>
    <p class="entry"><b>隨身</b> ${a.inventory.map((o) => o.name).join("、") || "空手"}</p>
    <h2>日記</h2>
    ${entries || "<p class='entry'>（空白）</p>"}
  `;
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

document.querySelectorAll(".chronicle .tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".chronicle .tabs button").forEach((b) => b.classList.remove("on"));
    btn.classList.add("on");
    $("#tape").classList.toggle("hidden", btn.dataset.tab !== "tape");
    $("#tab-chapters").classList.toggle("hidden", btn.dataset.tab !== "chapters");
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
  if (!confirm("這會抹去事件帶，重新開始「港尾」。")) return;
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
  $("#clock").textContent = "無法載入世界：" + err.message;
});
