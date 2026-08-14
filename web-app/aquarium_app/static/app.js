const appState = {
  dashboard: null,
  session: { authenticated: false, user: null, csrf_token: null },
  currentRoute: "overview",
  currentDeviceId: null,
  chartMetric: "",
  chartHours: 24,
  chartData: null,
  eventFilter: "all",
  adminTab: "system",
  toastTimer: null,
};

const selectors = {
  toast: document.querySelector("[data-toast]"),
  connection: document.querySelector("[data-connection-state]"),
  loginDialog: document.querySelector("[data-auth-dialog]"),
  controlDialog: document.querySelector("[data-control-dialog]"),
  metricGrid: document.querySelector("[data-metric-grid]"),
  chart: document.querySelector("[data-main-chart]"),
};

const statusLabel = { normal: "正常", warning: "輕度異常", danger: "異常", missing: "資料缺失" };
const metricLabel = {
  temp_c: "水溫", temp_demo_c: "水溫", level_pct: "水位", level_low: "低水位",
  temp_smoothed_c: "平滑水溫", temp_forecast_c: "預測水溫", level_state: "水位狀態",
  ph: "pH", ec_us_cm: "導電度", turbidity_ntu: "濁度", water_quality_score: "水質",
  brightness_pct: "燈光亮度", feed_response_score: "進食反應", dose_ml: "滴定劑量",
  heating_power_pct: "加熱功率", cooling_power_pct: "冷卻功率", do_mg_l: "溶氧",
  oxygen_risk: "缺氧風險", chlorophyll_score: "葉綠素", anomaly_score: "異常分數",
  aeration_on: "曝氣狀態", feeds_today: "今日餵食", pump_flow_ml_s: "幫浦流量",
  adc_raw: "ADC 原始值", adc_voltage_v: "ADC 電壓", adc_noise_std: "ADC 雜訊",
  data_quality_pct: "資料品質", color_clear: "Clear 通道", wifi_rssi: "Wi-Fi 訊號",
  online_nodes: "在線節點", mode: "運作模式",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function formatTime(value, options = {}) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-TW", {
    month: options.short ? undefined : "2-digit", day: options.short ? undefined : "2-digit",
    hour: "2-digit", minute: "2-digit", second: options.seconds ? "2-digit" : undefined,
    hour12: false,
  }).format(date);
}

function formatValue(reading) {
  if (reading.value !== null && reading.value !== undefined) {
    const magnitude = Math.abs(Number(reading.value));
    const digits = magnitude >= 100 ? 0 : magnitude >= 10 ? 1 : 2;
    return Number(reading.value).toLocaleString("zh-TW", { maximumFractionDigits: digits });
  }
  return reading.text_value ?? "—";
}

function showToast(message, tone = "info") {
  selectors.toast.textContent = message;
  selectors.toast.dataset.tone = tone;
  selectors.toast.hidden = false;
  clearTimeout(appState.toastTimer);
  appState.toastTimer = setTimeout(() => { selectors.toast.hidden = true; }, 3600);
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.csrf !== false && appState.session.csrf_token && options.method && options.method !== "GET") {
    headers["X-CSRF-Token"] = appState.session.csrf_token;
  }
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    credentials: "same-origin",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 401 && !path.endsWith("/login")) {
    appState.session = { authenticated: false, user: null, csrf_token: null };
    updateSessionUi();
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function setConnection(mode, label) {
  selectors.connection.className = `connection-chip is-${mode}`;
  selectors.connection.querySelector("span").textContent = label;
}

async function refreshDashboard({ quiet = false } = {}) {
  try {
    const dashboard = await api("/api/v1/dashboard", { csrf: false });
    appState.dashboard = dashboard;
    renderDashboard();
    renderDeviceList();
    renderEvents();
    setConnection("online", "服務在線");
    if (!quiet && appState.chartMetric) await loadChart();
  } catch (error) {
    setConnection("error", "連線失敗");
    if (!quiet) showToast(`無法載入 Dashboard：${error.message}`, "danger");
  }
}

function renderDashboard() {
  const data = appState.dashboard;
  if (!data) return;
  document.querySelector("[data-health-title]").textContent = `${data.health.title}。`;
  document.querySelector("[data-health-score]").textContent = data.health.state === "empty" ? "—" : data.health.score;
  document.querySelector(".health-score").dataset.healthState = data.health.state;
  document.querySelector("[data-health-summary]").textContent = data.health.title;
  const count = data.health.counts;
  document.querySelector("[data-health-detail]").textContent = data.health.state === "empty"
    ? "完成裝置 API Key 設定後，ESP32 上傳的數值會顯示在這裡。"
    : `目前 ${count.normal} 項正常、${count.warning} 項輕度異常、${count.danger} 項異常、${count.missing} 項缺失；預測不會直接驅動控制。`;
  const online = data.devices.filter((item) => item.status === "online" && item.enabled).length;
  const enabled = data.devices.filter((item) => item.enabled).length;
  document.querySelector("[data-node-count]").textContent = `${online} / ${enabled} 在線`;
  document.querySelector("[data-updated-at]").textContent = formatTime(data.generated_at, { seconds: true, short: true });
  const demoData = data.readings.length > 0 && data.readings.every((item) => item.metadata?.source === "demo");
  document.querySelector("[data-data-state]").textContent = demoData ? "示範資料" : "即時資料";
  renderMetricCards();
  populateMetricSelect();
  renderDashboardEvents();
}

function cardLayout() {
  try { return JSON.parse(localStorage.getItem("aquarium-card-layout")) || {}; } catch { return {}; }
}

function saveCardLayout() {
  const cards = [...selectors.metricGrid.querySelectorAll(".metric-card")];
  const layout = { order: cards.map((card) => card.dataset.metric), hidden: cards.filter((card) => card.hidden).map((card) => card.dataset.metric) };
  try { localStorage.setItem("aquarium-card-layout", JSON.stringify(layout)); } catch {}
  updateRestoreCards();
}

function renderMetricCards() {
  const readings = appState.dashboard?.readings || [];
  const empty = document.querySelector("[data-metric-empty]");
  if (!readings.length) {
    selectors.metricGrid.replaceChildren(empty);
    empty.hidden = false;
    return;
  }
  const layout = cardLayout();
  const order = new Map((layout.order || []).map((metric, index) => [metric, index]));
  const hidden = new Set(layout.hidden || []);
  const sorted = [...readings].sort((a, b) => (order.get(a.metric) ?? 999) - (order.get(b.metric) ?? 999));
  selectors.metricGrid.replaceChildren();
  sorted.forEach((reading) => {
    const card = document.createElement("article");
    card.className = "metric-card";
    card.dataset.metric = reading.metric;
    card.dataset.status = reading.status;
    card.hidden = hidden.has(reading.metric);
    card.innerHTML = `
      <button class="drag-handle" type="button" aria-label="拖曳或使用方向鍵重新排序">DRAG</button>
      <button class="metric-dismiss" type="button" aria-label="隱藏圖卡">×</button>
      <button class="metric-open" type="button">
        <span class="metric-topline"><span class="metric-name">${escapeHtml(metricLabel[reading.metric] || reading.metric)}</span><span class="metric-state">${statusLabel[reading.status]}</span></span>
        <span class="metric-value"><strong>${escapeHtml(formatValue(reading))}</strong><small>${escapeHtml(reading.unit)}</small></span>
        <span class="metric-foot"><span>${escapeHtml(reading.device_id)}</span><span>${formatTime(reading.recorded_at, { short: true })}</span></span>
      </button>`;
    card.querySelector(".metric-open").addEventListener("click", () => openDevice(reading.device_id, reading.metric));
    card.querySelector(".metric-dismiss").addEventListener("click", () => { card.hidden = true; saveCardLayout(); });
    enableCardReorder(card);
    selectors.metricGrid.append(card);
  });
  updateRestoreCards();
}

function updateRestoreCards() {
  const button = document.querySelector("[data-restore-cards]");
  const hidden = selectors.metricGrid.querySelectorAll(".metric-card[hidden]").length;
  button.hidden = hidden === 0;
  button.querySelector("strong").textContent = hidden;
}

let draggedMetricCard = null;
function enableCardReorder(card) {
  const handle = card.querySelector(".drag-handle");
  let pointerDragging = false;
  card.draggable = false;
  handle.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "touch" || event.pointerType === "pen") {
      event.preventDefault(); pointerDragging = true; card.classList.add("is-dragging"); handle.setPointerCapture(event.pointerId); return;
    }
    card.draggable = true;
  });
  handle.addEventListener("pointermove", (event) => {
    if (!pointerDragging) return;
    event.preventDefault();
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".metric-card");
    document.querySelectorAll(".is-drag-target").forEach((item) => item.classList.remove("is-drag-target"));
    if (!target || target === card || target.hidden) return;
    target.classList.add("is-drag-target");
    const rect = target.getBoundingClientRect();
    selectors.metricGrid.insertBefore(card, event.clientY > rect.top + rect.height / 2 ? target.nextElementSibling : target);
  });
  const finishPointer = (event) => {
    card.draggable = false;
    if (!pointerDragging) return;
    pointerDragging = false; card.classList.remove("is-dragging");
    document.querySelectorAll(".is-drag-target").forEach((item) => item.classList.remove("is-drag-target"));
    if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    saveCardLayout(); showToast("圖卡順序已更新");
  };
  handle.addEventListener("pointerup", finishPointer);
  handle.addEventListener("pointercancel", finishPointer);
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const cards = [...selectors.metricGrid.querySelectorAll(".metric-card:not([hidden])")];
    const index = cards.indexOf(card);
    const backward = event.key === "ArrowLeft" || event.key === "ArrowUp";
    const target = cards[index + (backward ? -1 : 1)];
    if (!target) return;
    selectors.metricGrid.insertBefore(card, backward ? target : target.nextElementSibling);
    saveCardLayout(); handle.focus(); showToast("圖卡順序已更新");
  });
  card.addEventListener("dragstart", (event) => {
    if (!card.draggable) return event.preventDefault();
    draggedMetricCard = card; card.classList.add("is-dragging"); event.dataTransfer.effectAllowed = "move";
  });
  card.addEventListener("dragover", (event) => { if (draggedMetricCard && draggedMetricCard !== card) { event.preventDefault(); card.classList.add("is-drag-target"); } });
  card.addEventListener("dragleave", () => card.classList.remove("is-drag-target"));
  card.addEventListener("drop", (event) => {
    event.preventDefault(); card.classList.remove("is-drag-target");
    if (!draggedMetricCard || draggedMetricCard === card) return;
    const rect = card.getBoundingClientRect();
    selectors.metricGrid.insertBefore(draggedMetricCard, event.clientY > rect.top + rect.height / 2 ? card.nextElementSibling : card);
  });
  card.addEventListener("dragend", () => {
    card.classList.remove("is-dragging"); card.draggable = false; draggedMetricCard = null;
    document.querySelectorAll(".is-drag-target").forEach((item) => item.classList.remove("is-drag-target"));
    saveCardLayout(); showToast("圖卡順序已更新");
  });
}

function populateMetricSelect() {
  const select = document.querySelector("[data-chart-metric]");
  const readings = appState.dashboard?.readings || [];
  const current = appState.chartMetric;
  select.replaceChildren();
  if (!readings.length) {
    select.add(new Option("尚無數據", "")); appState.chartMetric = ""; return;
  }
  readings.forEach((item) => select.add(new Option(metricLabel[item.metric] || item.metric, item.metric)));
  appState.chartMetric = readings.some((item) => item.metric === current) ? current : readings[0].metric;
  select.value = appState.chartMetric;
  loadChart();
}

async function loadChart(metric = appState.chartMetric, deviceId = null, canvas = selectors.chart) {
  if (!metric) return;
  try {
    const query = new URLSearchParams({ hours: appState.chartHours, limit: 5000 });
    const forecastQuery = new URLSearchParams({ history_hours: Math.min(appState.chartHours, 168), horizon_minutes: 30 });
    if (deviceId) { query.set("device_id", deviceId); forecastQuery.set("device_id", deviceId); }
    const [history, forecast] = await Promise.all([
      api(`/api/v1/history/${encodeURIComponent(metric)}?${query}`, { csrf: false }),
      api(`/api/v1/forecast/${encodeURIComponent(metric)}?${forecastQuery}`, { csrf: false }),
    ]);
    const chartData = { history: history.points, forecast, metric };
    if (canvas === selectors.chart) appState.chartData = chartData;
    drawChart(canvas, chartData);
    if (canvas === selectors.chart) {
      document.querySelector("[data-chart-empty]").hidden = history.points.length > 0;
      document.querySelector("[data-forecast-caption]").textContent = forecast.available
        ? `30 分鐘預測，信心 ${Math.round(forecast.confidence * 100)}%，斜率 ${forecast.slope_per_hour}/小時。預測不會直接驅動控制。`
        : `${forecast.reason || "資料不足，暫無預測"}。預測不會直接驅動控制。`;
    }
  } catch (error) { showToast(`圖表載入失敗：${error.message}`, "danger"); }
}

function drawChart(canvas, data) {
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
  const width = rect.width, height = rect.height, pad = { left: 52, right: 24, top: 24, bottom: 38 };
  const styles = getComputedStyle(document.body);
  const colors = { text: styles.getPropertyValue("--text").trim(), muted: styles.getPropertyValue("--muted").trim(), rule: styles.getPropertyValue("--rule").trim(), normal: styles.getPropertyValue("--normal").trim(), warning: styles.getPropertyValue("--warning").trim(), danger: styles.getPropertyValue("--danger").trim(), missing: styles.getPropertyValue("--missing").trim(), accent: styles.getPropertyValue("--accent").trim(), accentSoft: styles.getPropertyValue("--accent-soft").trim() };
  ctx.clearRect(0, 0, width, height);
  const history = data.history.filter((item) => item.value !== null && item.value !== undefined);
  const forecast = data.forecast.available ? data.forecast.points : [];
  const all = [...history.map((item) => ({ x: new Date(item.recorded_at).getTime(), y: Number(item.value) })), ...forecast.map((item) => ({ x: new Date(item.at).getTime(), y: item.value }))];
  if (!all.length) return;
  let minX = Math.min(...all.map((item) => item.x)), maxX = Math.max(...all.map((item) => item.x));
  let minY = Math.min(...all.map((item) => item.y)), maxY = Math.max(...all.map((item) => item.y));
  if (minX === maxX) maxX += 1; if (minY === maxY) { minY -= 1; maxY += 1; }
  const yMargin = (maxY - minY) * .12; minY -= yMargin; maxY += yMargin;
  const sx = (value) => pad.left + (value - minX) / (maxX - minX) * (width - pad.left - pad.right);
  const sy = (value) => height - pad.bottom - (value - minY) / (maxY - minY) * (height - pad.top - pad.bottom);
  ctx.font = "12px ui-monospace, monospace"; ctx.fillStyle = colors.muted; ctx.strokeStyle = colors.rule; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (height - pad.top - pad.bottom) * i / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    const value = maxY - (maxY - minY) * i / 4; ctx.fillText(value.toFixed(1), 4, y + 4);
  }
  if (forecast.length) {
    ctx.fillStyle = colors.accentSoft; ctx.beginPath();
    forecast.forEach((point, index) => { const fn = index ? ctx.lineTo.bind(ctx) : ctx.moveTo.bind(ctx); fn(sx(new Date(point.at).getTime()), sy(point.upper)); });
    [...forecast].reverse().forEach((point) => ctx.lineTo(sx(new Date(point.at).getTime()), sy(point.lower)));
    ctx.closePath(); ctx.globalAlpha = .65; ctx.fill(); ctx.globalAlpha = 1;
  }
  const statusColor = (status) => colors[status] || colors.warning;
  ctx.lineWidth = 3; ctx.lineCap = "round"; ctx.lineJoin = "round";
  for (let i = 1; i < history.length; i += 1) {
    const previous = history[i - 1], point = history[i]; ctx.strokeStyle = statusColor(point.status);
    ctx.setLineDash(point.status === "missing" ? [5, 6] : []); ctx.beginPath();
    ctx.moveTo(sx(new Date(previous.recorded_at).getTime()), sy(Number(previous.value)));
    ctx.lineTo(sx(new Date(point.recorded_at).getTime()), sy(Number(point.value))); ctx.stroke();
  }
  if (forecast.length && history.length) {
    ctx.strokeStyle = colors.accent; ctx.setLineDash([7, 6]); ctx.beginPath();
    ctx.moveTo(sx(new Date(history.at(-1).recorded_at).getTime()), sy(Number(history.at(-1).value)));
    forecast.forEach((point) => ctx.lineTo(sx(new Date(point.at).getTime()), sy(point.value))); ctx.stroke(); ctx.setLineDash([]);
  }
  ctx.fillStyle = colors.muted; ctx.fillText(formatTime(new Date(minX).toISOString(), { short: true }), pad.left, height - 12);
  const endLabel = formatTime(new Date(maxX).toISOString(), { short: true }); ctx.fillText(endLabel, width - pad.right - ctx.measureText(endLabel).width, height - 12);
}

function renderEventItem(event) {
  const when = event.scheduled_for || event.occurred_at;
  return `<article class="event-item" data-severity="${escapeHtml(event.severity)}">
    <time class="event-time">${formatTime(when)}</time><div><strong>${escapeHtml(event.title)}</strong><p>${escapeHtml(event.detail || event.event_type)}</p></div>
    ${event.scheduled_for && !event.completed_at ? '<span class="demo-label">預定</span>' : ""}</article>`;
}
function renderDashboardEvents() {
  const root = document.querySelector("[data-dashboard-events]");
  const events = (appState.dashboard?.events || []).slice(0, 6);
  root.innerHTML = events.length ? events.map(renderEventItem).join("") : '<div class="empty-state"><strong>尚無事件</strong><span>裝置事件與預定排程會顯示在這裡。</span></div>';
}
function renderEvents() {
  const root = document.querySelector("[data-full-events]"); if (!root || !appState.dashboard) return;
  let events = appState.fullEvents || appState.dashboard.events;
  if (appState.eventFilter === "past") events = events.filter((item) => !item.scheduled_for || item.completed_at);
  if (appState.eventFilter === "upcoming") events = events.filter((item) => item.scheduled_for && !item.completed_at);
  root.innerHTML = events.length ? events.map(renderEventItem).join("") : '<div class="empty-state"><strong>沒有符合條件的事件</strong></div>';
}

function readingsForDevice(deviceId) {
  return (appState.dashboard?.readings || []).filter((item) => item.device_id === deviceId);
}

function renderDeviceList() {
  const root = document.querySelector("[data-device-list]");
  if (!root || !appState.dashboard) return;
  const devices = appState.dashboard.devices;
  root.innerHTML = devices.map((device) => {
    const count = readingsForDevice(device.id).length;
    return `<button class="device-list-item ${device.id === appState.currentDeviceId ? "is-active" : ""}" type="button" data-device-id="${escapeHtml(device.id)}">
      <strong>${escapeHtml(device.name)}</strong><small>${escapeHtml(device.status.toUpperCase())}</small>
      <span>${escapeHtml(device.kind)} · ${count} 項數據</span><span>${formatTime(device.last_seen_at, { short: true })}</span>
    </button>`;
  }).join("");
  root.querySelectorAll("[data-device-id]").forEach((button) => button.addEventListener("click", () => openDevice(button.dataset.deviceId)));
}

async function openDevice(deviceId, preferredMetric = null) {
  appState.currentDeviceId = deviceId;
  showRoute("devices");
  renderDeviceList();
  await renderDeviceDetail(deviceId, preferredMetric);
}

async function renderDeviceDetail(deviceId, preferredMetric = null) {
  const root = document.querySelector("[data-device-detail]");
  const device = appState.dashboard?.devices.find((item) => item.id === deviceId);
  if (!device) return;
  const readings = readingsForDevice(deviceId);
  const canControl = appState.session.authenticated && ["operator", "admin"].includes(appState.session.user.role);
  root.innerHTML = `<header class="device-detail-header"><div><p class="section-number">${escapeHtml(device.id)}</p><h2>${escapeHtml(device.name)}</h2><p>${escapeHtml(device.location)} · ${escapeHtml(device.kind)}</p></div>
    <div class="device-status-stack"><span>${escapeHtml(device.status.toUpperCase())}</span><span>最後回報 ${formatTime(device.last_seen_at)}</span></div></header>
    <div class="detail-readings">${readings.length ? readings.map((reading) => `<div class="detail-reading"><span>${escapeHtml(metricLabel[reading.metric] || reading.metric)}</span><strong>${escapeHtml(formatValue(reading))}</strong><small>${escapeHtml(reading.unit)} · ${statusLabel[reading.status]}</small></div>`).join("") : '<div class="empty-state"><strong>尚無數據</strong></div>'}</div>
    <section><div class="panel-heading"><div><p class="section-number">HISTORY + FORECAST</p><h2>詳細趨勢</h2></div><select data-device-metric>${readings.map((reading) => `<option value="${escapeHtml(reading.metric)}">${escapeHtml(metricLabel[reading.metric] || reading.metric)}</option>`).join("")}</select></div>
      <div class="chart-wrap"><canvas data-device-chart aria-label="裝置歷史與預測圖"></canvas><div class="chart-empty" data-device-chart-empty ${readings.length ? "hidden" : ""}>尚無歷史資料</div></div>
      <p class="chart-caption">狀態色：綠色正常、橘色輕度異常、紅色異常、灰色缺失。預測與控制完全分離。</p></section>
    <section class="command-list"><div class="panel-heading"><div><p class="section-number">CONTROL + SCHEDULE</p><h2>控制與排程</h2></div></div>
      <p>${canControl ? "命令先進入佇列，再由裝置領取並通過本機安全規則。" : "請以 Operator 或 Admin 登入，才能建立控制命令與排程。"}</p>
      <div class="detail-actions"><button class="primary-button" type="button" data-open-control ${canControl ? "" : "disabled"}>建立控制命令</button><button class="secondary-button" type="button" data-open-login-from-device ${canControl ? "hidden" : ""}>登入</button></div>
      ${canControl ? `<form class="schedule-form" data-schedule-form><input name="device_id" type="hidden" value="${escapeHtml(device.id)}"/><label>排程名稱<input name="name" value="每日排程" required /></label><label>命令<select name="command">${device.capabilities.filter((item) => item !== "telemetry" && item !== "gateway").map((item) => `<option>${escapeHtml(item)}</option>`).join("") || "<option>set</option>"}</select></label><label>Cron（分 時 日 月 週）<input name="cron_expression" value="0 8 * * *" required /></label><label>參數 JSON<textarea name="parameters">{}</textarea></label><label>最大運轉秒數<input name="max_runtime_seconds" type="number" min="1" max="86400" value="60" /></label><label>安全說明<input name="safety_note" value="仍由 ESP32 本機安全規則決定是否執行" /></label><button class="secondary-button" type="submit">儲存排程</button></form>` : ""}
      <div data-device-schedules></div><div data-device-commands></div></section>`;
  const metricSelect = root.querySelector("[data-device-metric]");
  const metric = readings.some((item) => item.metric === preferredMetric) ? preferredMetric : readings[0]?.metric;
  if (metric) {
    metricSelect.value = metric;
    await loadChart(metric, deviceId, root.querySelector("[data-device-chart]"));
    metricSelect.addEventListener("change", () => loadChart(metricSelect.value, deviceId, root.querySelector("[data-device-chart]")));
  }
  root.querySelector("[data-open-control]").addEventListener("click", () => openControlDialog(device));
  root.querySelector("[data-open-login-from-device]")?.addEventListener("click", openLogin);
  root.querySelector("[data-schedule-form]")?.addEventListener("submit", saveSchedule);
  if (appState.session.authenticated) await Promise.all([renderDeviceCommands(deviceId), renderDeviceSchedules(deviceId)]);
}

async function renderDeviceCommands(deviceId) {
  const root = document.querySelector("[data-device-commands]");
  if (!root) return;
  try {
    const commands = await api(`/api/v1/manage/commands?device_id=${encodeURIComponent(deviceId)}&limit=20`);
    root.innerHTML = commands.length ? commands.map((command) => `<div class="command-row"><span>${escapeHtml(command.status)}</span><strong>${escapeHtml(command.command)}</strong><time>${formatTime(command.requested_at)}</time></div>`).join("") : '<p class="metric-meta">尚無控制命令。</p>';
  } catch (error) { root.innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`; }
}

async function renderDeviceSchedules(deviceId) {
  const root = document.querySelector("[data-device-schedules]"); if (!root) return;
  try {
    const schedules = await api(`/api/v1/manage/schedules?device_id=${encodeURIComponent(deviceId)}`);
    root.innerHTML = schedules.length ? `<h3>已設定排程</h3>${schedules.map((item) => `<div class="command-row"><span>${item.enabled ? "啟用" : "停用"}</span><strong>${escapeHtml(item.name)} · ${escapeHtml(item.cron_expression)}</strong><span>${escapeHtml(item.command)}</span></div>`).join("")}` : "";
  } catch (error) { root.innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`; }
}

async function saveSchedule(event) {
  event.preventDefault(); const form = event.currentTarget;
  try {
    const body = {
      device_id: form.elements.device_id.value, name: form.elements.name.value, command: form.elements.command.value,
      cron_expression: form.elements.cron_expression.value, parameters: JSON.parse(form.elements.parameters.value || "{}"),
      max_runtime_seconds: Number(form.elements.max_runtime_seconds.value) || null, safety_note: form.elements.safety_note.value,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Taipei", enabled: true,
    };
    await api("/api/v1/manage/schedules", { method: "PUT", body }); showToast("排程已儲存"); await renderDeviceSchedules(body.device_id);
  } catch (error) { showToast(`排程儲存失敗：${error.message}`, "danger"); }
}

function openControlDialog(device) {
  if (!appState.session.authenticated) return openLogin();
  const form = document.querySelector("[data-control-form]");
  form.elements.device_id.value = device.id;
  const select = form.elements.command; select.replaceChildren();
  const capabilities = device.capabilities.filter((item) => item !== "telemetry" && item !== "gateway");
  (capabilities.length ? capabilities : ["set"]).forEach((command) => select.add(new Option(command, command)));
  selectors.controlDialog.showModal();
}

function showRoute(route) {
  appState.currentRoute = route;
  document.querySelectorAll("[data-view]").forEach((view) => {
    const active = view.dataset.view === route; view.hidden = !active; view.classList.toggle("is-active", active);
  });
  document.querySelectorAll(".nav-item[data-route]").forEach((button) => button.classList.toggle("is-active", button.dataset.route === route));
  window.scrollTo({ top: 0, behavior: "auto" });
  if (route === "admin") loadAdmin();
  if (route === "events") loadFullEvents();
}

async function loadFullEvents() {
  try { appState.fullEvents = await api("/api/v1/events?limit=500", { csrf: false }); renderEvents(); }
  catch (error) { showToast(`事件載入失敗：${error.message}`, "danger"); }
}

function openLogin() {
  document.querySelector("[data-login-error]").hidden = true;
  selectors.loginDialog.showModal();
}

function updateSessionUi() {
  const action = document.querySelector("[data-session-action]");
  const compactHeader = window.matchMedia("(max-width: 600px)").matches;
  action.textContent = appState.session.authenticated ? (compactHeader ? "登出" : `${appState.session.user.username} / 登出`) : "登入";
  const gate = document.querySelector("[data-admin-gate]");
  const shell = document.querySelector("[data-admin-shell]");
  const adminAuthorized = appState.session.authenticated && appState.session.user.role === "admin";
  gate.hidden = adminAuthorized; shell.hidden = !adminAuthorized;
  gate.querySelector("strong").textContent = appState.session.authenticated ? "需要 Admin 權限" : "後台需要登入";
  gate.querySelector("span").textContent = appState.session.authenticated ? "Operator 可從設備頁控制與排程；完整後台只提供 Admin。" : "Dashboard 保持公開；後台不會暴露 API Key 或控制功能。";
  gate.querySelector("button").hidden = appState.session.authenticated;
  document.querySelector("[data-admin-session]").textContent = appState.session.authenticated
    ? `${appState.session.user.username} / ${appState.session.user.role}`
    : "登入後可管理裝置、權限、資料保留、備份與通知整合。";
}

async function loadSession() {
  try { appState.session = await api("/api/v1/auth/me", { csrf: false }); }
  catch { appState.session = { authenticated: false, user: null, csrf_token: null }; }
  updateSessionUi();
}

async function loadAdmin() {
  updateSessionUi();
  if (!appState.session.authenticated || appState.session.user.role !== "admin") return;
  try {
    if (appState.adminTab === "system") await loadAdminSystem();
    if (appState.adminTab === "devices") await loadAdminDevices();
    if (appState.adminTab === "users") await loadAdminUsers();
    if (appState.adminTab === "audit") await loadAudit();
  } catch (error) { showToast(`後台載入失敗：${error.message}`, "danger"); }
}

async function loadAdminSystem() {
  const [settings, stats] = await Promise.all([api("/api/v1/manage/settings"), api("/api/v1/manage/database")]);
  const root = document.querySelector("[data-database-stats]");
  root.innerHTML = [
    ["目前空間", `${stats.physical_megabytes} MB`], ["原始數據", stats.counts.sensor_readings.toLocaleString("zh-TW")],
    ["事件", stats.counts.events.toLocaleString("zh-TW")], ["資料起點", formatTime(stats.first_recorded_at)], ["保存範圍", `${stats.retention_days} 天`],
  ].map(([term, value]) => `<div><dt>${term}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  document.querySelector("[data-retention-summary]").textContent = `${settings.retention_days} 天`;
  const form = document.querySelector("[data-settings-form]");
  for (const name of ["retention_days", "dashboard_refresh_seconds", "device_offline_seconds"]) form.elements[name].value = settings[name];
}

async function loadAdminDevices() {
  const [devices, keys] = await Promise.all([api("/api/v1/manage/devices"), api("/api/v1/manage/device-keys")]);
  const devicesRoot = document.querySelector("[data-admin-devices]");
  devicesRoot.innerHTML = devices.map((device) => `<details class="admin-list-row"><summary><strong>${escapeHtml(device.name)}</strong><span>${escapeHtml(device.id)} · ${escapeHtml(device.kind)}</span></summary>
    <form data-device-settings="${escapeHtml(device.id)}"><label>名稱<input name="name" value="${escapeHtml(device.name)}" required /></label><label>位置<input name="location" value="${escapeHtml(device.location)}" required /></label><label>裝置設定 JSON<textarea name="settings">${escapeHtml(JSON.stringify(device.settings, null, 2))}</textarea></label><label>圖表設定 JSON<textarea name="chart_config">${escapeHtml(JSON.stringify(device.chart_config, null, 2))}</textarea></label><button class="secondary-button" type="submit">儲存設備設定</button><button class="primary-button" type="button" data-create-key="${escapeHtml(device.id)}">建立 API Key</button></form></details>`).join("");
  devicesRoot.querySelectorAll("[data-device-settings]").forEach((form) => form.addEventListener("submit", (event) => saveDeviceSettings(event, devices.find((item) => item.id === form.dataset.deviceSettings))));
  devicesRoot.querySelectorAll("[data-create-key]").forEach((button) => button.addEventListener("click", () => createDeviceKey(button.dataset.createKey)));
  const keysRoot = document.querySelector("[data-device-keys]");
  keysRoot.innerHTML = keys.length ? keys.map((key) => `<div class="admin-list-row"><div><strong>${escapeHtml(key.label)}</strong><span>${escapeHtml(key.device_id)} · ${escapeHtml(key.key_id)}</span><small>${key.revoked_at ? "已撤銷" : `最後使用 ${formatTime(key.last_used_at)}`}</small></div>${key.revoked_at ? "" : `<button type="button" data-revoke-key="${escapeHtml(key.key_id)}">撤銷</button>`}</div>`).join("") : '<p>尚未建立 API Key。</p>';
  keysRoot.querySelectorAll("[data-revoke-key]").forEach((button) => button.addEventListener("click", async () => {
    if (!confirm("確定撤銷這組 API Key？裝置會立即無法上傳資料。")) return;
    await api(`/api/v1/manage/device-keys/${button.dataset.revokeKey}`, { method: "DELETE" }); showToast("API Key 已撤銷"); loadAdminDevices();
  }));
}

async function saveDeviceSettings(event, device) {
  event.preventDefault(); const form = event.currentTarget;
  try {
    const body = { ...device, name: form.elements.name.value, location: form.elements.location.value, settings: JSON.parse(form.elements.settings.value || "{}"), chart_config: JSON.parse(form.elements.chart_config.value || "{}") };
    await api(`/api/v1/manage/devices/${encodeURIComponent(device.id)}`, { method: "PUT", body });
    showToast("設備設定已儲存"); await refreshDashboard({ quiet: true });
  } catch (error) { showToast(`設備設定失敗：${error.message}`, "danger"); }
}

async function createDeviceKey(deviceId) {
  try {
    const result = await api(`/api/v1/manage/devices/${encodeURIComponent(deviceId)}/keys`, { method: "POST", body: { label: `generated-${new Date().toISOString().slice(0, 10)}` } });
    document.querySelector("[data-device-keys]").insertAdjacentHTML("afterbegin", `<div class="key-secret"><strong>請立即複製，離開後無法再次顯示：</strong><br>${escapeHtml(result.api_key)}</div>`);
    showToast("新的 API Key 已建立");
  } catch (error) { showToast(`API Key 建立失敗：${error.message}`, "danger"); }
}

async function loadAdminUsers() {
  const users = await api("/api/v1/manage/users");
  const root = document.querySelector("[data-user-list]");
  root.innerHTML = users.map((user) => `<div class="admin-list-row"><div><strong>${escapeHtml(user.username)}</strong><span>${escapeHtml(user.role)} · ${user.active ? "啟用" : "停用"}</span></div><select data-user-role="${user.id}" ${user.id === appState.session.user.id ? "disabled" : ""}><option value="viewer">viewer</option><option value="operator">operator</option><option value="admin">admin</option></select></div>`).join("");
  root.querySelectorAll("[data-user-role]").forEach((select) => {
    select.value = users.find((user) => user.id === Number(select.dataset.userRole)).role;
    select.addEventListener("change", async () => { await api(`/api/v1/manage/users/${select.dataset.userRole}`, { method: "PATCH", body: { role: select.value } }); showToast("角色已更新"); });
  });
}

async function loadAudit() {
  const rows = await api("/api/v1/manage/audit?limit=300");
  document.querySelector("[data-audit-list]").innerHTML = rows.map((row) => `<tr><td>${formatTime(row.created_at)}</td><td>${escapeHtml(`${row.actor_type}:${row.actor_id || "—"}`)}</td><td>${escapeHtml(row.action)}</td><td>${escapeHtml(`${row.target_type || ""}:${row.target_id || ""}`)}</td></tr>`).join("");
}

document.querySelectorAll("[data-route]").forEach((button) => {
  button.addEventListener("click", () => showRoute(button.dataset.route));
});

document.querySelector("[data-theme-toggle]").addEventListener("click", (event) => {
  const dark = document.body.dataset.theme !== "dark";
  document.body.dataset.theme = dark ? "dark" : "light";
  event.currentTarget.textContent = dark ? "淺色" : "深色";
  try { localStorage.setItem("aquarium-theme", dark ? "dark" : "light"); } catch {}
  if (appState.chartData) drawChart(selectors.chart, appState.chartData);
});

document.querySelector("[data-session-action]").addEventListener("click", async () => {
  if (!appState.session.authenticated) return openLogin();
  try {
    await api("/api/v1/auth/logout", { method: "POST", body: {} });
    appState.session = { authenticated: false, user: null, csrf_token: null };
    updateSessionUi(); showToast("已登出");
    if (appState.currentDeviceId) renderDeviceDetail(appState.currentDeviceId);
  } catch (error) { showToast(`登出失敗：${error.message}`, "danger"); }
});

document.querySelectorAll("[data-open-login]").forEach((button) => button.addEventListener("click", openLogin));
document.querySelector("[data-close-dialog]").addEventListener("click", () => selectors.loginDialog.close());
document.querySelector("[data-close-control]").addEventListener("click", () => selectors.controlDialog.close());
[selectors.loginDialog, selectors.controlDialog].forEach((dialog) => dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }));

document.querySelector("[data-login-form]").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget; const errorRoot = document.querySelector("[data-login-error]");
  try {
    const result = await api("/api/v1/auth/login", { method: "POST", csrf: false, body: { username: form.elements.username.value, password: form.elements.password.value } });
    appState.session = { authenticated: true, user: result.user, csrf_token: result.csrf_token };
    form.reset(); selectors.loginDialog.close(); updateSessionUi(); showToast(`歡迎，${result.user.username}`);
    if (appState.currentRoute === "admin") loadAdmin();
    if (appState.currentDeviceId) renderDeviceDetail(appState.currentDeviceId);
  } catch (error) { errorRoot.textContent = error.message; errorRoot.hidden = false; }
});

document.querySelector("[data-control-form]").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget;
  try {
    const deviceId = form.elements.device_id.value;
    await api(`/api/v1/manage/devices/${encodeURIComponent(deviceId)}/commands`, { method: "POST", body: { command: form.elements.command.value, parameters: JSON.parse(form.elements.parameters.value || "{}"), expires_in_seconds: Number(form.elements.expires_in_seconds.value) } });
    selectors.controlDialog.close(); showToast("控制命令已加入佇列"); await renderDeviceCommands(deviceId);
  } catch (error) { showToast(`命令建立失敗：${error.message}`, "danger"); }
});

document.querySelector("[data-restore-cards]").addEventListener("click", () => {
  selectors.metricGrid.querySelectorAll(".metric-card").forEach((card) => { card.hidden = false; }); saveCardLayout(); showToast("已顯示全部圖卡");
});

document.querySelector("[data-chart-metric]").addEventListener("change", (event) => { appState.chartMetric = event.target.value; loadChart(); });
document.querySelectorAll("[data-hours]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("[data-hours]").forEach((item) => item.classList.toggle("is-active", item === button));
  appState.chartHours = Number(button.dataset.hours); loadChart();
}));

document.querySelectorAll("[data-event-filter]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("[data-event-filter]").forEach((item) => item.classList.toggle("is-active", item === button));
  appState.eventFilter = button.dataset.eventFilter; renderEvents();
}));

document.querySelectorAll("[data-admin-tab]").forEach((button) => button.addEventListener("click", () => {
  appState.adminTab = button.dataset.adminTab;
  document.querySelectorAll("[data-admin-tab]").forEach((item) => item.classList.toggle("is-active", item === button));
  document.querySelectorAll("[data-admin-panel]").forEach((panel) => { const active = panel.dataset.adminPanel === appState.adminTab; panel.hidden = !active; panel.classList.toggle("is-active", active); });
  loadAdmin();
}));

document.querySelector("[data-settings-form]").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget;
  try {
    const body = { retention_days: Number(form.elements.retention_days.value), dashboard_refresh_seconds: Number(form.elements.dashboard_refresh_seconds.value), device_offline_seconds: Number(form.elements.device_offline_seconds.value) };
    await api("/api/v1/manage/settings", { method: "PATCH", body }); showToast("系統設定已儲存"); await loadAdminSystem();
  } catch (error) { showToast(`設定儲存失敗：${error.message}`, "danger"); }
});

document.querySelector("[data-cleanup]").addEventListener("click", async () => {
  if (!confirm("確定依目前保存期限清理舊資料？建議先下載備份。")) return;
  try { const result = await api("/api/v1/manage/database/cleanup", { method: "POST", body: { vacuum: false } }); showToast(`清理完成：移除 ${result.deleted.sensor_readings} 筆原始數據`); await loadAdminSystem(); }
  catch (error) { showToast(`資料清理失敗：${error.message}`, "danger"); }
});

document.querySelector("[data-user-form]").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget;
  try { await api("/api/v1/manage/users", { method: "POST", body: { username: form.elements.username.value, password: form.elements.password.value, role: form.elements.role.value } }); form.reset(); showToast("帳號已建立"); await loadAdminUsers(); }
  catch (error) { showToast(`帳號建立失敗：${error.message}`, "danger"); }
});

document.querySelector("[data-alarm-form]").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget;
  try { await api("/api/v1/manage/alarms", { method: "POST", body: { alarm_type: "manual.test", severity: form.elements.severity.value, title: form.elements.title.value, message: form.elements.message.value, payload: { source: "admin-ui" } } }); showToast("測試警報已加入 outbox"); }
  catch (error) { showToast(`警報建立失敗：${error.message}`, "danger"); }
});

document.querySelector("[data-claim-alarms]").addEventListener("click", async () => {
  try { const alarms = await api("/api/v1/manage/alarms/claim?limit=20", { method: "POST", body: {} }); document.querySelector("[data-alarm-output]").textContent = JSON.stringify(alarms, null, 2); showToast(`已領取 ${alarms.length} 筆警報`); }
  catch (error) { showToast(`警報領取失敗：${error.message}`, "danger"); }
});

const chartResizeObserver = new ResizeObserver(() => { if (appState.chartData) drawChart(selectors.chart, appState.chartData); });
chartResizeObserver.observe(selectors.chart);

async function startApp() {
  try {
    const savedTheme = localStorage.getItem("aquarium-theme");
    if (savedTheme === "dark") { document.body.dataset.theme = "dark"; document.querySelector("[data-theme-toggle]").textContent = "淺色"; }
  } catch {}
  await Promise.all([loadSession(), refreshDashboard()]);
  const seconds = appState.dashboard?.refresh_seconds || 15;
  setInterval(() => refreshDashboard({ quiet: true }), seconds * 1000);
}

startApp();
