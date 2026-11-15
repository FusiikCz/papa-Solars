const app = document.querySelector("#app");
const net = document.querySelector("#net");
const title = document.querySelector("h1");
let state = null;
let selectedId = null;
let hours = 24;
let history = [];
let events = [];
let historyKey = "";
let cellPoints = [];
let cellHistoryKey = "";
let screen = { level: "pack", module: 0, cell: 0 };
let painted = "";
let socketReady = false;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function dash(value, digits) {
  if (value == null || value === "") return "—";
  if (typeof value === "number" && digits != null) return value.toLocaleString("cs-CZ", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  if (typeof value === "number") return value.toLocaleString("cs-CZ");
  return esc(value);
}

function when(iso) {
  if (!iso) return "—";
  const date = new Date(iso.includes("T") ? iso : `${iso.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return esc(iso);
  return date.toLocaleString("cs-CZ", { timeZone: "Europe/Prague" });
}

function kw(watts) {
  if (watts == null) return "—";
  return dash(watts / 1000, 2);
}

function selected() {
  if (!state) return null;
  return state.batteries.find((item) => item.id === selectedId) || state.batteries[0] || null;
}

function pair(label, value) {
  return `<div><span>${esc(label)}</span><strong>${value}</strong></div>`;
}

function render() {
  if (!state) return;
  net.textContent = `jen ${state.subnet}`;
  if (!selectedId && state.batteries[0]) selectedId = state.batteries[0].id;
  const battery = selected();
  const key = battery ? `${battery.id}:${screen.level}:${screen.module}:${screen.cell}` : "empty";
  const same = key === painted;
  const y = window.scrollY;
  title.textContent = heading(battery);
  app.innerHTML = [
    linkNote(),
    configNotes(),
    battery ? viewFor(battery) : emptyView(),
    screen.level === "pack" ? others() : "",
  ].join("");
  bind();
  painted = key;
  if (same) window.scrollTo(0, y);
  else window.scrollTo(0, 0);
  if (battery && screen.level === "pack" && currentHistoryKey() !== historyKey) loadHistory();
  if (battery && screen.level === "cell" && cellKey() !== cellHistoryKey) loadCellHistory();
}

function heading(battery) {
  if (!battery) return "Diagnostika baterie";
  if (screen.level === "module") return `Modul ${screen.module}`;
  if (screen.level === "cell") return `Článek ${screen.cell}`;
  return battery.bms_serial ? `Baterie ${battery.bms_serial}` : battery.name;
}

function linkNote() {
  if (state.on_link) return "";
  return `<div class="banner warn"><strong>Tenhle počítač nemá adresu v ${esc(state.subnet)}</strong>Sběr stejně míří jen tam. Zdrojová adresa je ${esc(state.source_ip || "žádná")}.</div>`;
}

function configNotes() {
  if (!state.config_errors.length) return "";
  return `<div class="banner warn"><strong>Konfigurace</strong>${state.config_errors.map((item) => `<div>${esc(item)}</div>`).join("")}</div>`;
}

function emptyView() {
  return `<section class="card"><h2>V ${esc(state.subnet)} teď neodpovídá žádná Force H2</h2><p class="muted">Hledám loggery na TCP 8899 v rozsahu 192.168.99.1–254.</p></section>`;
}

function viewFor(battery) {
  if (screen.level === "cell") return cellView(battery);
  if (screen.level === "module") return moduleView(battery);
  return packView(battery);
}

function packView(battery) {
  const tabs = state.batteries.length < 2 ? "" : `<div class="tabs">${state.batteries.map((item) =>
    `<button type="button" data-id="${item.id}" class="${item.id === battery.id ? "active" : ""}">${esc(item.name)}</button>`
  ).join("")}</div>`;
  return `<section class="stack">${tabs}${comm(battery)}${basics(battery)}${pack(battery)}${stateCard(battery)}${moduleList(battery)}${charts()}${eventList()}</section>`;
}

function comm(battery) {
  if (!battery.communication_ok) {
    return `<div class="banner bad"><strong>Výpadek komunikace</strong>${esc(battery.error || "baterie neodpovídá")}<div>Naposledy v pořádku: ${when(battery.last_success_at)}. Aktuální napětí tu není.</div></div>`;
  }
  const age = battery.age_seconds == null ? "" : `před ${battery.age_seconds} s`;
  return `<div class="banner ok"><strong>${esc(battery.mode_label || "spojení v pořádku")}</strong>${esc(battery.ip)} · ${age}</div>`;
}

function basics(battery) {
  return `<section class="card"><h2>Základní údaje</h2><div class="pairs">
    ${pair("Sériové číslo", esc(battery.bms_serial || "—"))}
    ${pair("Značka", esc(battery.manufacturer || "—"))}
    ${pair("Název", esc(battery.model || "Force_H2"))}
    ${pair("Firmware", esc(battery.firmware || "—"))}
    ${pair("Počet modulů", dash(battery.module_count))}
    ${pair("Počet článků", dash(battery.cell_count))}
  </div></section>`;
}

function pack(battery) {
  if (!battery.communication_ok) return "";
  return `<section class="card"><h2>Baterie</h2><div class="pairs">
    ${pair("Napětí", `${dash(battery.voltage_v, 1)} V`)}
    ${pair("Proud", `${dash(battery.current_a, 2)} A`)}
    ${pair("SOC", `${dash(battery.soc)} %`)}
    ${pair("SOH", `${dash(battery.soh)} %`)}
    ${pair("Cykly", dash(battery.cycle_count))}
    ${pair("Výkon", `${kw(battery.power_w)} kW`)}
  </div></section>`;
}

function stateCard(battery) {
  if (!battery.communication_ok) return "";
  const alarms = battery.alarms || [];
  const alarmHtml = alarms.length
    ? `<ul class="alarms">${alarms.map((item) => `<li class="level-${esc(item.level)}">${esc(item.text)}</li>`).join("")}</ul>`
    : `<p class="muted">BMS nehlásí ochranu, výstrahu ani poruchu.</p>`;
  const notices = (battery.notices || []).map((item) => `<li>${esc(item)}</li>`).join("");
  return `<section class="card"><h2>Stav</h2><div class="pairs">
    ${pair("Režim", esc(battery.mode_label || "—"))}
    ${pair("Rozdíl článků", `${dash(battery.cell_delta_mv)} mV`)}
    ${pair("Nejvyšší článek", battery.max_cell_mv == null ? "—" : `${dash(battery.max_cell_mv)} mV · č. ${dash(battery.max_cell_index)}`)}
    ${pair("Nejnižší článek", battery.min_cell_mv == null ? "—" : `${dash(battery.min_cell_mv)} mV · č. ${dash(battery.min_cell_index)}`)}
  </div>${alarmHtml}${notices ? `<ul class="notes">${notices}</ul>` : ""}</section>`;
}

function moduleList(battery) {
  const modules = battery.communication_ok ? (battery.modules || []) : [];
  if (!modules.length) return "";
  const buttons = modules.map((item) => `<button type="button" class="module-btn" data-module="${item.index}">
      <span>Modul ${item.index}<br><b>${dash(item.voltage_v, 2)} V</b></span>
      <span>${dash(item.temp_c, 1)} °C <i>články</i></span>
    </button>`).join("");
  return `<section class="card"><h2>Moduly</h2><div class="module-list">${buttons}</div><p class="muted">Teplota je teplota modulu. Do článků se vstupuje odtud.</p></section>`;
}

function moduleView(battery) {
  const module = (battery.modules || []).find((item) => item.index === screen.module);
  const cells = (battery.cells || []).filter((item) => item.module === screen.module);
  const head = module
    ? `${dash(module.voltage_v, 2)} V · ${dash(module.temp_c, 1)} °C`
    : "Modul teď nemá aktuální údaje";
  return `<section class="stack">
    <button type="button" class="back" data-back="pack">← Baterie</button>
    ${comm(battery)}
    <section class="card"><h2>Modul ${screen.module}</h2><p>${esc(head)}</p>${cellGrid(battery, cells)}</section>
  </section>`;
}

function cellGrid(battery, cells) {
  if (!battery.communication_ok || !cells.length) {
    return `<p class="muted">Aktuální napětí článků teď není k dispozici.</p>`;
  }
  const usable = (battery.cells || []).map((item) => item.mv).filter((mv) => mv >= 2000 && mv <= 4500);
  const min = usable.length ? Math.min(...usable) : null;
  const max = usable.length ? Math.max(...usable) : null;
  const boxes = cells.map((item) => {
    const mark = item.index === battery.max_cell_index || item.index === battery.min_cell_index ? " marked" : "";
    return `<button type="button" class="cell${mark}" data-module="${item.module}" data-cell="${item.index}" style="background:${cellColor(item.mv, min, max)}"><small>${item.cell}</small>${item.mv}</button>`;
  }).join("");
  return `<p class="muted">Číslo v rohu je pořadí článku v modulu od nuly, stejně jako v aplikaci baterie. Orámovaný je nejvyšší nebo nejnižší článek podle BMS.</p><div class="cell-grid">${boxes}</div>`;
}

function cellView(battery) {
  const cell = (battery.cells || []).find((item) => item.index === screen.cell);
  const module = (battery.modules || []).find((item) => item.index === screen.module);
  const siblings = (battery.cells || []).filter((item) => item.module === screen.module).map((item) => item.mv);
  const average = siblings.length ? siblings.reduce((sum, value) => sum + value, 0) / siblings.length : null;
  let detail = `<p class="muted">Aktuální hodnota článku teď není k dispozici.</p>`;
  if (battery.communication_ok && cell) {
    const flags = [];
    if (cell.index === battery.max_cell_index) flags.push("Nejvyšší článek podle BMS");
    if (cell.index === battery.min_cell_index) flags.push("Nejnižší článek podle BMS");
    detail = `<p class="cell-title">${dash(cell.mv)} mV</p>
      <div class="pairs">
        ${pair("Modul", String(cell.module))}
        ${pair("Pozice v modulu", String(cell.cell))}
        ${pair("Pořadí v baterii", String(cell.index))}
        ${pair("Oproti nejnižšímu", cell && battery.min_cell_mv != null ? `${dash(cell.mv - battery.min_cell_mv)} mV` : "—")}
        ${pair("Oproti průměru modulu", average == null ? "—" : `${dash(Math.round(cell.mv - average))} mV`)}
        ${pair("Teplota modulu", module ? `${dash(module.temp_c, 1)} °C` : "—")}
      </div>
      ${flags.map((item) => `<p><strong>${esc(item)}</strong></p>`).join("")}
      <p class="muted">Force H2 nemá samostatné čidlo každého článku. Teplota patří celému modulu.</p>`;
  }
  return `<section class="stack">
    <button type="button" class="back" data-back="module">← Modul ${screen.module}</button>
    ${comm(battery)}
    <section class="card"><h2>Článek ${screen.cell}</h2>${detail}</section>
    <section class="card"><h2>Historie článku</h2>${rangeButtons()}<div class="chart-wrap">${drawChart(cellPoints, "mv", "#b64a16", "mV")}</div></section>
  </section>`;
}

function cellColor(mv, min, max) {
  if (min == null || mv < 2000 || mv > 4500) return "#f6f1e8";
  const t = max === min ? 0.5 : (mv - min) / (max - min);
  const from = [226, 232, 226];
  const to = [226, 177, 90];
  const rgb = from.map((channel, index) => Math.round(channel + (to[index] - channel) * t));
  return `rgb(${rgb.join(",")})`;
}

function rangeButtons() {
  return `<div class="ranges">${[6, 24, 168].map((value) =>
    `<button type="button" data-hours="${value}" class="${value === hours ? "active" : ""}">${value === 168 ? "7 dní" : `${value} h`}</button>`
  ).join("")}</div>`;
}

function charts() {
  return `<section class="card"><h2>Historie</h2>${rangeButtons()}<p class="muted">Čára se přeruší, když mezi vzorky chybí víc než minuta a půl.</p><div class="chart-wrap">${drawChart(history, "soc", "#1d6b45", "%")}</div><div class="chart-wrap">${drawChart(history, "voltage_v", "#b64a16", "V")}</div></section>`;
}

function drawChart(points, key, color, unit) {
  const groups = segments(points, key);
  if (!groups.length) return `<p class="muted">Zatím není co kreslit (${esc(unit)}).</p>`;
  const flat = groups.flat();
  const width = 720;
  const height = 160;
  const pad = 28;
  const t0 = flat[0].t;
  const t1 = flat[flat.length - 1].t || t0 + 1;
  let min = Math.min(...flat.map((item) => item.value));
  let max = Math.max(...flat.map((item) => item.value));
  if (min === max) { min -= 1; max += 1; }
  const x = (t) => pad + ((t - t0) / (t1 - t0 || 1)) * (width - pad * 2);
  const y = (value) => height - pad - ((value - min) / (max - min)) * (height - pad * 2);
  const paths = groups.map((group) => {
    const d = group.map((item, index) => `${index ? "L" : "M"}${x(item.t).toFixed(1)},${y(item.value).toFixed(1)}`).join(" ");
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2"/>`;
  }).join("");
  const dots = flat.length < 40
    ? flat.map((item) => `<circle cx="${x(item.t).toFixed(1)}" cy="${y(item.value).toFixed(1)}" r="3" fill="${color}"/>`).join("")
    : "";
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img">
    <text x="${pad}" y="16" font-size="12" fill="#6d6458">${esc(unit)} ${dash(max, 1)}</text>
    <text x="${pad}" y="${height - 8}" font-size="12" fill="#6d6458">${dash(min, 1)}</text>
    ${paths}${dots}
  </svg>`;
}

function segments(points, key) {
  const groups = [];
  let current = null;
  let prev = null;
  for (const point of points) {
    const t = Date.parse(point.t);
    const value = point[key];
    const missing = value == null || Number.isNaN(t);
    if (missing || (prev != null && t - prev > 90000)) current = null;
    if (missing) { prev = null; continue; }
    if (!current) { current = []; groups.push(current); }
    current.push({ t, value });
    prev = t;
  }
  return groups;
}

function eventList() {
  if (!events.length) return "";
  const rows = events.slice(0, 40).map((item) => {
    const text = item.online
      ? (item.alarms || []).map((alarm) => alarm.text).join(", ")
      : item.error;
    return `<tr><td>${when(item.t)}</td><td>${item.online ? "alarm BMS" : "výpadek"}</td><td>${esc(text || "")}</td></tr>`;
  }).join("");
  return `<section class="card"><h2>Výpadky a alarmy</h2><table><thead><tr><th>Čas</th><th></th><th>Co se stalo</th></tr></thead><tbody>${rows}</tbody></table></section>`;
}

function others() {
  if (!state.other_loggers.length) return "";
  const rows = state.other_loggers.map((item) =>
    `<tr><td>${esc(item.ip)}</td><td>${dash(item.serial)}</td><td>${esc(item.model || "")}</td><td>${esc(item.detail || "")}</td></tr>`
  ).join("");
  return `<section class="card"><h2>Ostatní zařízení v 192.168.99.0/24</h2><table><thead><tr><th>IP</th><th>Logger</th><th>Model</th><th>Poznámka</th></tr></thead><tbody>${rows}</tbody></table></section>`;
}

function bind() {
  app.querySelectorAll("[data-id]").forEach((button) => {
    button.onclick = () => {
      selectedId = Number(button.dataset.id);
      screen = { level: "pack", module: 0, cell: 0 };
      historyKey = "";
      render();
    };
  });
  app.querySelectorAll("[data-hours]").forEach((button) => {
    button.onclick = () => {
      hours = Number(button.dataset.hours);
      historyKey = "";
      cellHistoryKey = "";
      render();
    };
  });
  app.querySelectorAll("[data-module]").forEach((button) => {
    if (button.dataset.cell != null) return;
    button.onclick = () => {
      screen = { level: "module", module: Number(button.dataset.module), cell: 0 };
      render();
    };
  });
  app.querySelectorAll("[data-cell]").forEach((button) => {
    button.onclick = () => {
      screen = {
        level: "cell",
        module: Number(button.dataset.module),
        cell: Number(button.dataset.cell),
      };
      cellHistoryKey = "";
      cellPoints = [];
      render();
    };
  });
  app.querySelectorAll("[data-back]").forEach((button) => {
    button.onclick = () => {
      screen = button.dataset.back === "module"
        ? { level: "module", module: screen.module, cell: 0 }
        : { level: "pack", module: 0, cell: 0 };
      render();
    };
  });
}

function currentHistoryKey() {
  const battery = selected();
  if (!battery) return "";
  return `${battery.id}:${hours}:${state.last_poll_at || ""}`;
}

function cellKey() {
  const battery = selected();
  if (!battery) return "";
  return `${battery.id}:${screen.cell}:${hours}:${state.last_poll_at || ""}`;
}

async function loadHistory() {
  const battery = selected();
  if (!battery) return;
  const id = battery.id;
  const wanted = hours;
  historyKey = currentHistoryKey();
  const [hist, ev] = await Promise.all([
    fetch(`/api/batteries/${id}/history?hours=${wanted}`).then((res) => res.json()),
    fetch(`/api/batteries/${id}/events?hours=168`).then((res) => res.json()),
  ]);
  if (!selected() || selected().id !== id || hours !== wanted || screen.level !== "pack") return;
  history = hist.points || [];
  events = ev.events || [];
  render();
}

async function loadCellHistory() {
  const battery = selected();
  if (!battery || screen.level !== "cell") return;
  const id = battery.id;
  const index = screen.cell;
  const wanted = hours;
  cellHistoryKey = cellKey();
  const response = await fetch(`/api/batteries/${id}/cells/${index}/history?hours=${wanted}`);
  if (!response.ok) return;
  const data = await response.json();
  if (!selected() || selected().id !== id || screen.cell !== index || hours !== wanted) return;
  cellPoints = data.points || [];
  render();
}

function applyState(next) {
  const previous = selectedId;
  state = next;
  const battery = selected();
  if (battery && previous != null && battery.id !== previous) {
    screen = { level: "pack", module: 0, cell: 0 };
  }
  if (battery) selectedId = battery.id;
  render();
}

async function refresh() {
  const response = await fetch("/api/live");
  applyState(await response.json());
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.onopen = () => { socketReady = true; };
  socket.onmessage = (event) => applyState(JSON.parse(event.data));
  socket.onclose = () => {
    socketReady = false;
    setTimeout(connect, 2000);
  };
}

connect();
setInterval(() => { if (!socketReady) refresh(); }, 5000);
refresh();
