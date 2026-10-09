/* Reel Studio - UI logic (no framework, no build step) */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.text()).slice(0, 200) || r.statusText);
  return r.json();
};
const fmt = (n) => (n === null || n === undefined || n === "") ? "" : Number(n).toLocaleString("en-US");

/* ---------------------------------------------------------------- state */
const state = {
  jobs: {},            // id -> job detail
  active: { reels: null, profiles: null },
  dataJob: null,
  table: { sort: null, dir: -1, filter: "", cols: null },
  settings: { delay_ms: 1000, retries: 1, timeout_s: 60, enrich: true },
  timer: null,
};

const COLS = {
  reels: [
    ["input", "Input"], ["shortcode", "Shortcode"], ["username", "Owner"],
    ["owner_followers_display", "Owner followers"], ["likes", "Likes"], ["comments", "Comments"],
    ["reposts", "Reposts"], ["views", "Views"], ["music_title", "Music"], ["music_artist", "Artist"],
    ["music_type", "Audio type"], ["date", "Date"], ["duration", "Duration (s)"],
    ["location", "Location"], ["caption", "Caption"], ["url", "URL"], ["ok", "OK"], ["error", "Error"],
  ],
  profiles: [
    ["input", "Input"], ["username", "Username"], ["full_name", "Name"],
    ["followers_display", "Followers"], ["following", "Following"], ["posts", "Posts"],
    ["bio", "Bio"], ["profile_pic", "Profile pic"], ["ok", "OK"], ["error", "Error"],
  ],
};
const DEFAULTS_VISIBLE = {
  reels: ["shortcode", "username", "owner_followers_display", "likes", "comments", "reposts",
          "music_title", "music_artist", "date", "ok", "error"],
  profiles: ["username", "followers_display", "following", "posts", "full_name", "ok", "error"],
};
const NUMCOLS = new Set(["likes", "comments", "reposts", "views", "followers", "following",
  "posts", "duration", "owner_followers", "tier"]);

/* ---------------------------------------------------------------- toast */
let toastT;
function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (bad ? " bad" : "");
  clearTimeout(toastT);
  toastT = setTimeout(() => { t.className = "toast"; }, 3200);
}

/* ---------------------------------------------------------------- tabs */
$$("#tabs button").forEach((b) => b.addEventListener("click", () => {
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + b.dataset.tab));
  if (b.dataset.tab === "data") refreshJobs();
  if (b.dataset.tab === "settings") { loadHistory(); checkSession(); }
}));

/* ---------------------------------------------------------------- defaults */
function engCfg(pre) {
  return {
    mode: ($("#" + pre + "-mode") || {}).value || state.settings.mode || "fast",
    workers: +($("#" + pre + "-workers") || {}).value || state.settings.workers || 6,
  };
}
async function loadSettings() {
  try { state.settings = Object.assign(state.settings, await api("/api/settings")); } catch (e) {}
  const s = state.settings;
  for (const pre of ["s", "p", "d"]) {
    const mode = $("#" + pre + "-mode"), wk = $("#" + pre + "-workers");
    if (mode) mode.value = s.mode || "fast";
    if (wk) wk.value = s.workers || 6;
  }
  $("#s-delay").value = s.delay_ms; $("#p-delay").value = s.delay_ms; $("#d-delay").value = s.delay_ms;
  $("#s-retries").value = s.retries; $("#p-retries").value = s.retries; $("#d-retries").value = s.retries;
  $("#s-timeout").value = s.timeout_s; $("#p-timeout").value = s.timeout_s; $("#d-timeout").value = s.timeout_s;
  $("#s-enrich").checked = !!s.enrich; $("#d-enrich").checked = !!s.enrich;
}
async function saveDefaults(src) {
  const s = {
    delay_ms: +$("#" + src + "-delay").value || 0,
    retries: +$("#" + src + "-retries").value || 0,
    timeout_s: +$("#" + src + "-timeout").value || 60,
    mode: ($("#" + src + "-mode") || {}).value || state.settings.mode || "fast",
    workers: +($("#" + src + "-workers") || {}).value || state.settings.workers || 6,
  };
  if (src === "d") s.enrich = $("#d-enrich").checked;
  else s.enrich = state.settings.enrich;
  const saved = await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(s) });
  state.settings = saved; loadSettings();
  toast("Defaults saved");
}
$("#save-defaults").onclick = () => saveDefaults("s");
$("#d-save").onclick = () => saveDefaults("d");
$("#d-reset").onclick = async () => {
  await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delay_ms: 1000, retries: 1, timeout_s: 60, enrich: true, mode: "fast", workers: 6 }) });
  await loadSettings(); toast("Defaults reset");
};

/* ---------------------------------------------------------------- inputs */
function lines(v) {
  return v.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
}
function countUp(id, ta) { $(id).textContent = lines($(ta).value).length + " items"; }
$("#reel-urls").addEventListener("input", () => countUp("#reel-count", "#reel-urls"));
$("#prof-urls").addEventListener("input", () => countUp("#prof-count", "#prof-urls"));

function wireFile(pickBtn, inputEl, ta) {
  $(pickBtn).onclick = () => $(inputEl).click();
  $(inputEl).onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const text = await f.text();
    const urls = text.match(/https?:\/\/\S+/g) || text.split(/\r?\n/);
    $(ta).value = urls.map((s) => s.trim().replace(/[",;]+$/, "")).filter(Boolean).join("\n");
    countUp(ta === "#reel-urls" ? "#reel-count" : "#prof-count", ta);
    toast(`Loaded ${f.name}`);
    e.target.value = "";
  };
  $(pickBtn).onclick = () => $(inputEl).click();
}
wireFile("#reel-file", "#reel-file-input", "#reel-urls");
wireFile("#prof-file", "#prof-file-input", "#prof-urls");

$("#reel-clear").onclick = () => { $("#reel-urls").value = ""; countUp("#reel-count", "#reel-urls"); };
$("#prof-clear").onclick = () => { $("#prof-urls").value = ""; countUp("#prof-count", "#prof-urls"); };
$("#reel-sample").onclick = () => {
  $("#reel-urls").value = ["https://www.instagram.com/reels/Dd6Pu8KpFJc/",
    "https://www.instagram.com/reel/DeMW459gbXu/", "DanDFR7plbh"].join("\n");
  countUp("#reel-count", "#reel-urls");
};

/* ---------------------------------------------------------------- jobs */
async function startJob(kind) {
  const ta = kind === "reels" ? "#reel-urls" : "#prof-urls";
  const items = lines($(ta).value);
  if (!items.length) return toast("Add at least one input", true);
  const pre = kind === "reels" ? "s" : "p";
  const settings = {
    delay_ms: +$("#" + pre + "-delay").value || 0,
    retries: +$("#" + pre + "-retries").value || 0,
    timeout_s: +$("#" + pre + "-timeout").value || 60,
    enrich: kind === "reels" ? $("#s-enrich").checked : false,
    ...engCfg(pre),
  };
  try {
    const r = await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: kind, items, settings }) });
    state.active[kind] = r.id;
    toast(`Started: ${items.length} item(s)`);
    setBusy(kind, true);
    poll(kind);
  } catch (e) { toast("Start failed: " + e.message, true); }
}

function setBusy(kind, busy) {
  const pre = kind === "reels" ? "reel" : "prof";
  $("#" + pre + "-start").disabled = busy;
  $("#" + pre + "-stop").disabled = !busy;
}

async function stopJob(kind) {
  const id = state.active[kind];
  if (!id) return;
  await api(`/api/jobs/${id}/stop`, { method: "POST" });
  toast("Stop requested");
}

$("#reel-start").onclick = () => startJob("reels");
$("#prof-start").onclick = () => startJob("profiles");
$("#reel-stop").onclick = () => stopJob("reels");
$("#prof-stop").onclick = () => stopJob("profiles");

function poll(kind) {
  clearInterval(state.timer);
  state.timer = setInterval(async () => {
    const id = state.active[kind];
    if (!id) return clearInterval(state.timer);
    let j;
    try { j = await api("/api/jobs/" + id); } catch (e) { return; }
    state.jobs[id] = j;
    renderRun(kind, j);
    if (!["running", "queued"].includes(j.status)) {
      clearInterval(state.timer);
      setBusy(kind, false);
      toast(`${kind} job ${j.status}: ${j.ok_count} ok / ${j.fail_count} failed`);
      refreshJobs();
      if (state.dataJob === id) renderData();
    }
  }, 900);
}

function renderRun(kind, j) {
  const pre = kind === "reels" ? "reel" : "prof";
  $("#" + pre + "-done").textContent = j.done;
  $("#" + pre + "-total").textContent = j.total;
  $("#" + pre + "-ok").textContent = j.ok_count;
  $("#" + pre + "-fail").textContent = j.fail_count;
  const scope = (j.status === "running" && j.enrich_total && j.enrich_done < j.enrich_total && j.done === j.total)
    ? { d: j.enrich_done, t: j.enrich_total } : { d: j.done, t: j.total };
  const pct = scope.t ? Math.round((scope.d / scope.t) * 100) : 0;
  $("#" + pre + "-meter").style.width = pct + "%";
  const st = $("#" + pre + "-status");
  st.textContent = j.status === "running" ? "running" : j.status;
  st.className = "pill " + (j.status === "done" ? "ok" :
    (j.status === "running" || j.status === "queued") ? "run" : "bad");
  let eta = "-";
  if (j.status === "running" && j.started_at && scope.d > 0 && scope.d < scope.t) {
    const per = (Date.now() / 1000 - j.started_at) / scope.d;
    eta = Math.round((scope.t - scope.d) * per) + "s";
  }
  $("#" + pre + "-eta").textContent = eta;
  const cur = j.enrich_total && j.done === j.total && j.enrich_done < j.enrich_total
    ? `profiles ${j.enrich_done} / ${j.enrich_total}`
    : (j.current || (j.status === "done" ? "finished" : "idle"));
  $("#" + pre + "-current").textContent = cur;
  const box = $("#" + pre + "-log");
  box.innerHTML = (j.log || []).map((l) =>
    `<div class="l ${l.level}"><span class="t">${l.t}</span> ${esc(l.msg)}</div>`).join("") ||
    '<div class="l info"><span class="t">--:--</span> waiting</div>';
  box.scrollTop = box.scrollHeight;
}

$("#reel-log-open").onclick = () => openData(state.active.reels);
$("#prof-log-open").onclick = () => openData(state.active.profiles);

/* ---------------------------------------------------------------- data */
async function refreshJobs() {
  try {
    const rows = await api("/api/jobs");
    const sel = $("#job-select");
    const cur = state.dataJob || (rows[0] && rows[0].id);
    sel.innerHTML = rows.map((r) =>
      `<option value="${r.id}" ${r.id === cur ? "selected" : ""}>${r.type} · ${r.status} · ${r.done}/${r.total} · ${r.id}</option>`).join("")
      || '<option value="">no jobs yet</option>';
    if (cur) { state.dataJob = cur; renderData(); }
  } catch (e) {}
}

function openData(id) {
  if (!id) return toast("No job yet — run a scrape first", true);
  state.dataJob = id;
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === "data"));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === "page-data"));
  refreshJobs();
}

$("#job-select").onchange = (e) => { state.dataJob = e.target.value; renderData(); };
$("#search").oninput = (e) => { state.table.filter = e.target.value.toLowerCase(); renderData(); };

function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

async function renderData() {
  const id = state.dataJob;
  if (!id) return;
  const j = state.jobs[id] || await api("/api/jobs/" + id).catch(() => null);
  if (!j) return;
  state.jobs[id] = j;
  const kind = j.type;
  const all = COLS[kind].map(([k]) => k);
  const vis = state.table.cols || DEFAULTS_VISIBLE[kind];
  state.table.cols = vis;

  // column picker
  $("#cols-pop").innerHTML = COLS[kind].map(([k, label]) =>
    `<label><input type="checkbox" data-col="${k}" ${vis.includes(k) ? "checked" : ""}/> ${esc(label)}</label>`).join("");
  $$("#cols-pop input").forEach((cb) => cb.onchange = () => {
    const set = new Set($$("#cols-pop input").filter((x) => x.checked).map((x) => x.dataset.col));
    state.table.cols = COLS[kind].map(([k]) => k).filter((k) => set.has(k));
    renderData();
  });

  let rows = (j.results || []).slice();
  if (state.table.filter) {
    rows = rows.filter((r) => all.some((k) => String(r[k] ?? "").toLowerCase().includes(state.table.filter)));
  }
  if (state.table.sort) {
    const k = state.table.sort, d = state.table.dir;
    rows.sort((a, b) => {
      const x = a[k], y = b[k];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * d;
      return String(x).localeCompare(String(y)) * d;
    });
  }
  const cols = state.table.cols;
  $("#data-table thead tr").innerHTML = cols.map((k) => {
    const label = (COLS[kind].find(([c]) => c === k) || [, k])[1];
    const arrow = state.table.sort === k ? (state.table.dir > 0 ? " ▲" : " ▼") : "";
    return `<th data-k="${k}">${esc(label)}${arrow}</th>`;
  }).join("");
  $$("#data-table thead th").forEach((th) => th.onclick = () => {
    const k = th.dataset.k;
    if (state.table.sort === k) state.table.dir *= -1; else { state.table.sort = k; state.table.dir = -1; }
    renderData();
  });
  $("#data-table tbody").innerHTML = rows.map((r) => "<tr>" + cols.map((k) => {
    let v = r[k];
    if (k === "ok") return `<td><span class="pill ${v ? "ok" : "bad"}">${v ? "ok" : "fail"}</span></td>`;
    if (k === "url" && v) return `<td><a href="${esc(v)}" target="_blank" rel="noopener">open</a></td>`;
    if (k === "profile_pic" && v) return `<td><a href="${esc(v)}" target="_blank" rel="noopener">open</a></td>`;
    if (k === "username" && v) return `<td><a href="https://www.instagram.com/${esc(v)}/" target="_blank" rel="noopener">@${esc(v)}</a></td>`;
    const cls = NUMCOLS.has(k) ? "num" : (String(v ?? "").length > 60 ? "wide" : "");
    const txt = typeof v === "number" ? fmt(v) : esc(v);
    return `<td class="${cls}" title="${esc(v)}">${txt ?? ""}</td>`;
  }).join("") + "</tr>").join("");
  $("#data-count").textContent = `${rows.length} row(s)` + (state.table.filter ? " (filtered)" : "");
  $("#data-empty").style.display = rows.length ? "none" : "block";
}
$("#toggle-cols").onclick = () => { const p = $("#cols-pop"); p.hidden = !p.hidden; };
["csv", "xlsx", "json"].forEach((f) => {
  $("#exp-" + f).onclick = () => {
    if (!state.dataJob) return toast("Nothing to export", true);
    window.location = `/api/jobs/${state.dataJob}/export?fmt=${f}`;
  };
});

/* ---------------------------------------------------------------- session + history */
async function checkSession() {
  const chip = $("#session-chip"), text = $("#session-text"), s = $("#sess-chip"), st = $("#sess-text");
  for (const [c, t] of [[chip, text], [s, st]]) { c.className = "chip"; t.textContent = "checking…"; }
  try {
    const r = await api("/api/status");
    const ok = r.ok;
    [[chip, text], [s, st]].forEach(([c, t]) => {
      c.className = "chip " + (ok ? "ok" : "bad");
      t.textContent = ok ? "Instagram connected" : `session: ${r.class || "not connected"}`;
    });
    if (!ok) toast("Instagram session not active — refresh it in Settings", true);
  } catch (e) {
    [[chip, text], [s, st]].forEach(([c, t]) => { c.className = "chip bad"; t.textContent = "backend offline"; });
  }
}
$("#recheck-session").onclick = checkSession;
$("#refresh-session").onclick = async () => {
  try {
    const r = await api("/api/session/refresh", { method: "POST" });
    toast(r.msg || "Login window opened");
  } catch (e) { toast("Could not open login window: " + e.message, true); }
};

async function loadHistory() {
  try {
    const rows = await api("/api/jobs");
    $("#history").innerHTML = rows.length ? rows.map((r) =>
      `<div class="hist-row">
        <span class="pill ${r.status === "done" ? "ok" : (r.status === "running" ? "run" : "bad")}">${r.status}</span>
        <span class="mono">${r.type}</span>
        <span class="small">${r.done} of ${r.total}, ${r.ok} ok, ${r.failed} failed</span>
        <span class="sp"></span>
        <button class="btn btn-sm" data-open="${r.id}">Open</button>
        <button class="btn btn-sm btn-danger" data-del="${r.id}">Delete</button>
      </div>`).join("") : "no runs yet";
    $$("#history [data-open]").forEach((b) => b.onclick = () => openData(b.dataset.open));
    $$("#history [data-del]").forEach((b) => b.onclick = async () => {
      await fetch("/api/jobs/" + b.dataset.del, { method: "DELETE" });
      loadHistory(); refreshJobs(); toast("Job deleted");
    });
  } catch (e) { $("#history").textContent = "could not load"; }
}
$("#hist-refresh").onclick = loadHistory;

/* ---------------------------------------------------------------- theme */
function setTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  const lbl = $("#theme-label");
  if (lbl) lbl.textContent = t === "dark" ? "Dark" : "Light";
  try { localStorage.setItem("rs-theme", t); } catch (e) {}
}
$("#theme-toggle").onclick = () =>
  setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");

/* ---------------------------------------------------------------- keys */
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
  const map = { "1": "reels", "2": "profiles", "3": "data", "4": "settings" };
  const tab = map[e.key];
  if (!tab) return;
  const b = document.querySelector(`#tabs button[data-tab="${tab}"]`);
  if (b) b.click();
});

/* ---------------------------------------------------------------- boot */
(async function boot() {
  setTheme(document.documentElement.getAttribute("data-theme") || "dark");
  await loadSettings();
  countUp("#reel-count", "#reel-urls");
  countUp("#prof-count", "#prof-urls");
  checkSession();
  refreshJobs();
})();
