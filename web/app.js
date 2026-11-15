const app = document.querySelector("#app");
const net = document.querySelector("#net");
let state = null;
let selectedId = null;
let hours = 24;
let history = [];
let events = [];
let historyKey = "";
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

function phaseLabel(phase) {
  if (phase === "discovery") return "prohledávám 192.168.99.0/24";
  if (phase === "ok") return "sběr běží";
  if (phase === "error") return "sběr narazil na chybu, zkouším dál";
  return "startuji";
}

function selected() {
  if (!state) return null;
  return state.batteries.find((item) => item.id === selectedId) || state.batteries[0] || null;
}

function render() {
  if (!state) return;
  net.textContent = `jen ${state.subnet}`;
  if (!selectedId && state.batteries[0]) selectedId = state.batteries[0].id;
  const battery = selected();
  app.innerHTML = [
    linkNote(),
    configNotes(),
    statusLine(),
    battery ? batteryView(battery) : emptyView(),
    others(),
  ].join("");
  bind();
}

function linkNote() {
  if (state.on_link) {
    return `<div class="banner ok"><strong>Server je v síti solárů</strong>Zdrojová adresa ${esc(state.source_ip)}. Čtu jen ${esc(state.subnet)}.</div>`;
  }
  return `<div class="banner warn"><strong>Tenhle počítač nemá adresu v ${esc(state.subnet)}</strong>Sběr stejně míří jen tam. UDP objev loggerů funguje spolehlivě, když je server přímo v této síti. Teď je zdrojová adresa ${esc(state.source_ip || "žádná")}.</div>`;
}

function configNotes() {
  if (!state.config_errors.length) return "";
  return `<div class="banner warn"><strong>Konfigurace</strong>${state.config_errors.map((item) => `<div>${esc(item)}</div>`).join("")}</div>`;
}

function statusLine() {
  return `<p class="muted">${esc(phaseLabel(state.phase))} · otevřený port 8899: ${dash(state.open_8899)} · poslední průchod sítě ${when(state.last_discovery_at)} · poslední čtení ${when(state.last_poll_at)}</p>`;
}

function emptyView() {
  return `<section class="card"><h2>V ${esc(state.subnet)} teď neodpovídá žádná Force H2</h2><p class="muted">Hledám Solarman loggery na UDP 48899 a TCP 8899 v celém rozsahu 192.168.99.1–254. Když logger discovery ignoruje, dopište jeho IP a sériové číslo do config.yaml. Pořád to musí být adresa z této sítě.</p></section>`;
}

function batteryView(battery) {
  const tabs = state.batteries.length < 2 ? "" : `<div class="tabs">${state.batteries.map((item) =>
    `<button type="button" data-id="${item.id}" class="${item.id === battery.id ? "active" : ""}">${esc(item.name)}</button>`
  ).join("")}</div>`;
  return `<section class="stack">${tabs}${head(battery)}${body(battery)}${charts()}${eventList()}</section>`;
}

function head(battery) {
  const idLine = [battery.model, battery.firmware, battery.bms_serial ? `SN ${battery.bms_serial}` : null]
    .filter(Boolean).map(esc).join(" · ");
  if (!battery.communication_ok) {
    return `<div class="banner bad"><strong>Výpadek komunikace · ${esc(battery.name)}</strong>${esc(battery.error || "baterie neodpovídá")}<div>Naposledy v pořádku: ${when(battery.last_success_at)}. Stará čísla tu nejsou, protože nejsou aktuální stav.</div><div class="muted">${esc(battery.ip)} · logger ${dash(battery.logger_serial)}</div></div>`;
  }
  const age = battery.age_seconds == null ? "" : ` · před ${battery.age_seconds} s`;
  return `<div class="banner ok"><strong>Spojení v pořádku · ${esc(battery.name)}</strong>${esc(battery.ip)} · ${esc(battery.mode_label || "neurčeno")}${age}<div>${idLine || "Force H2"}</div></div>`;
}

function body(battery) {
  if (!battery.communication_ok) return "";
  return [metrics(battery), alarms(battery), limits(battery), modules(battery), cells(battery)].join("");
}

function metric(label, value, unit) {
  return `<div class="metric"><span>${esc(label)}</span><strong>${value}</strong>${unit ? `<em>${esc(unit)}</em>` : ""}</div>`;
}

function metrics(battery) {
  return `<div class="metrics">
    ${metric("SOC", dash(battery.soc), "%")}
    ${metric("SOH", dash(battery.soh), "%")}
    ${metric("Napětí", dash(battery.voltage_v, 1), "V")}
    ${metric("Proud", dash(battery.current_a, 2), "A")}
    ${metric("Výkon", dash(battery.power_w, 0), "W")}
    ${metric("Rozdíl článků", dash(battery.cell_delta_mv), "mV")}
    ${metric("Teplota BMS", dash(battery.bms_temp_c, 1), "°C")}
    ${metric("Cykly", dash(battery.cycle_count), "")}
  </div>`;
}

function alarms(battery) {
  const items = battery.alarms || [];
  const notes = battery.quality_notes || [];
  const notices = battery.notices || [];
  const alarmHtml = items.length
    ? `<ul class="alarms">${items.map((item) => `<li class="level-${esc(item.level)}">${esc(item.text)}</li>`).join("")}</ul>`
    : `<p class="muted">BMS teď nehlásí ochranu, výstrahu ani poruchu.</p>`;
  const noticeHtml = notices.length ? `<ul class="notes">${notices.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : "";
  const noteHtml = notes.length ? `<ul class="notes">${notes.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : "";
  return `<section class="card"><h2>Hlášení BMS</h2>${alarmHtml}${noticeHtml}${noteHtml}<p class="muted">Meze nevymýšlím. Červeně a oranžově jsou jen bity, které nastavila samotná BMS.</p></section>`;
}

function limits(battery) {
  return `<section class="card"><h2>Meze hlášené BMS</h2><div class="metrics">
    ${metric("Konec nabíjení", dash(battery.charge_cutoff_v, 1), "V")}
    ${metric("Konec vybíjení", dash(battery.discharge_cutoff_v, 1), "V")}
    ${metric("Limit nabíjení", dash(battery.charge_limit_a, 2), "A")}
    ${metric("Limit vybíjení", dash(battery.discharge_limit_a, 2), "A")}
    ${metric("Zbývá", battery.remaining_wh == null ? "—" : dash(battery.remaining_wh / 1000, 2), "kWh")}
    ${metric("Dnes nabito", battery.charged_today_wh == null ? "—" : dash(battery.charged_today_wh / 1000, 2), "kWh")}
    ${metric("Dnes vybito", battery.discharged_today_wh == null ? "—" : dash(battery.discharged_today_wh / 1000, 2), "kWh")}
  </div><p class="muted">Dnešní energie se řídí hodinami BMS, ne hodinami serveru.</p></section>`;
}

function modules(battery) {
  const modules = battery.modules || [];
  if (!modules.length) return "";
  const cards = modules.map((item) => `<div class="card"><div class="module-head"><strong>Modul ${item.index + 1}</strong><span>${dash(item.voltage_v, 2)} V · ${dash(item.temp_c, 1)} °C</span></div></div>`).join("");
  return `<section><h2>Moduly</h2><div class="modules">${cards}</div><p class="muted">Teplota je teplota modulu. Mapa Force H2 nemá samostatné čidlo každého článku.</p></section>`;
}

function cells(battery) {
  const cells = battery.cells || [];
  if (!cells.length) return "";
  const usable = cells.map((item) => item.mv).filter((mv) => mv >= 2000 && mv <= 4500);
  const min = usable.length ? Math.min(...usable) : null;
  const max = usable.length ? Math.max(...usable) : null;
  const groups = new Map();
  cells.forEach((item) => {
    if (!groups.has(item.module)) groups.set(item.module, []);
    groups.get(item.module).push(item);
  });
  const html = [...groups.entries()].map(([module, group]) => {
    const boxes = group.map((item) => {
      const bg = cellColor(item.mv, min, max);
      return `<div class="cell" style="background:${bg}" title="článek ${item.index}"><small>${item.cell + 1}</small>${item.mv}</div>`;
    }).join("");
    return `<div><strong>Modul ${module + 1}</strong><div class="cell-grid">${boxes}</div></div>`;
  }).join("");
  return `<section class="card"><h2>Napětí článků</h2><p class="muted">Odstín jen ukazuje rozdíl uvnitř aktuálního čtení. Není to práh ochrany.</p>${html}</section>`;
}

function cellColor(mv, min, max) {
  if (min == null || mv < 2000 || mv > 4500) return "#f6f1e8";
  const t = max === min ? 0.5 : (mv - min) / (max - min);
  const from = [226, 232, 226];
  const to = [226, 177, 90];
  const rgb = from.map((channel, index) => Math.round(channel + (to[index] - channel) * t));
  return `rgb(${rgb.join(",")})`;
}

function charts() {
  const ranges = [6, 24, 168].map((value) =>
    `<button type="button" data-hours="${value}" class="${value === hours ? "active" : ""}">${value === 168 ? "7 dní" : `${value} h`}</button>`
  ).join("");
  return `<section class="card"><h2>Historie</h2><div class="ranges">${ranges}</div><p class="muted">Čára se přeruší, když mezi vzorky chybí víc než minuta a půl. Výpadek v grafu není doplněný poslední hodnotou.</p><div class="chart-wrap">${drawChart(history, "soc", "#1d6b45", "%")}</div><div class="chart-wrap">${drawChart(history, "voltage_v", "#b64a16", "V")}</div><div class="chart-wrap">${drawChart(history, "cell_delta_mv", "#1d1a16", "mV")}</div></section>`;
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
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img">
    <text x="${pad}" y="16" font-size="12" fill="#6d6458">${esc(unit)} ${dash(max, 1)}</text>
    <text x="${pad}" y="${height - 8}" font-size="12" fill="#6d6458">${dash(min, 1)}</text>
    ${paths}
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
  if (!events.length) {
    return `<section class="card"><h2>Výpadky a alarmy</h2><p class="muted">Zatím nic takového není uložené.</p></section>`;
  }
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
      loadHistory();
    };
  });
  app.querySelectorAll("[data-hours]").forEach((button) => {
    button.onclick = () => {
      hours = Number(button.dataset.hours);
      loadHistory();
    };
  });
}

async function loadHistory() {
  const battery = selected();
  if (!battery) {
    history = [];
    events = [];
    historyKey = "";
    render();
    return;
  }
  const id = battery.id;
  const wanted = hours;
  historyKey = currentHistoryKey();
  const [hist, ev] = await Promise.all([
    fetch(`/api/batteries/${id}/history?hours=${wanted}`).then((res) => res.json()),
    fetch(`/api/batteries/${id}/events?hours=168`).then((res) => res.json()),
  ]);
  if (!selected() || selected().id !== id || hours !== wanted) return;
  history = hist.points || [];
  events = ev.events || [];
  render();
}

function currentHistoryKey() {
  const battery = selected();
  if (!battery) return "";
  return `${battery.id}:${hours}:${state.last_poll_at || ""}`;
}

function applyState(next) {
  state = next;
  const battery = selected();
  if (battery) selectedId = battery.id;
  const key = currentHistoryKey();
  render();
  if (key !== historyKey) loadHistory();
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
