/* =========================================================
   CyT - Análisis de Índices | Lógica principal v2
   ========================================================= */

/* Todo esto son cuestiones de seguridad y demás, de validación del usuario*/
const TOKEN_KEY = "cyt-token";
const RRHH_PORTAL_URL = "https://ersepobservatorio-cyt.github.io/portal-observatorio-ersep/modulos/cumpleanos/";

function getToken()       { return localStorage.getItem(TOKEN_KEY) ?? ""; }
function saveToken(t)     { localStorage.setItem(TOKEN_KEY, t); }
function clearToken()     { localStorage.removeItem(TOKEN_KEY); }

function isLoggedIn() {
  const t = getToken();
  if (!t) return false;
  try {
    const p = JSON.parse(atob(t.split(".")[1]));
    return p.exp * 1000 > Date.now();
  } catch { return false; }
}

let _APP_INITIALIZED = false;
let _WELCOME_TIMER = null;

function hidePortalScreens() {
  for (const id of ["login-screen", "welcome-screen", "menu-screen", "app-screen"]) {
    const element = document.getElementById(id);
    if (element) element.style.display = "none";
  }
}

function showLogin() {
  if (_WELCOME_TIMER) clearTimeout(_WELCOME_TIMER);
  hidePortalScreens();
  document.body.classList.add("portal-active");
  document.getElementById("login-screen").style.display = "flex";
  setTimeout(() => document.getElementById("login-input")?.focus(), 100);
}

function showMenu() {
  if (_WELCOME_TIMER) clearTimeout(_WELCOME_TIMER);
  hidePortalScreens();
  document.getElementById("menu-screen").style.display = "flex";
  document.body.classList.add("portal-active");
}

function showWelcomeThenMenu() {
  hidePortalScreens();
  document.body.classList.add("portal-active");
  const welcome = document.getElementById("welcome-screen");
  welcome.style.display = "flex";
  welcome.classList.remove("welcome-replay");
  void welcome.offsetWidth;
  welcome.classList.add("welcome-replay");
  _WELCOME_TIMER = setTimeout(showMenu, 1750);
}

function showApp() {
  if (_WELCOME_TIMER) clearTimeout(_WELCOME_TIMER);
  hidePortalScreens();
  document.body.classList.remove("portal-active");
  document.getElementById("app-screen").style.display = "block";
  if (!_APP_INITIALIZED) {
    _APP_INITIALIZED = true;
    init();
  }
}

function handleLogout(expired = false) {
  clearToken();
  _APP_INITIALIZED = false;
  showLogin();
  if (expired) {
    const error = document.getElementById("login-error");
    error.textContent = "Tu sesión expiró. Ingresá nuevamente.";
    error.style.display = "block";
  }
}

async function handleLogin() {
  const input = document.getElementById("login-input");
  const errEl = document.getElementById("login-error");
  const btn = document.getElementById("btn-login");
  errEl.style.display = "none";
  btn.disabled = true;
  btn.textContent = "Verificando acceso...";
  try {
    const response = await fetch(apiUrl("/api/login"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({password: input.value.trim()}),
    });
    if (!response.ok) {
      errEl.textContent = "Contraseña incorrecta. Intentá de nuevo.";
      errEl.style.display = "block";
      input.value = "";
      input.focus();
      return;
    }
    const data = await response.json();
    saveToken(data.token);
    input.value = "";
    showWelcomeThenMenu();
  } catch {
    errEl.textContent = "No se pudo contactar al servidor.";
    errEl.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Ingresar";
  }
}
// Agrega esto en tu script.js
const btnCalc = document.getElementById('btn_calc');

if (btnCalc) {
    btnCalc.addEventListener('click', () => {
        window.location.href = './calculo.html';
    });
}

// ── Estado global ──
let _DATES_BY_YM = new Map();  // key "YYYY-MM" -> value "YYYY-MM-DD"
let _YEARS = [];              // [2023, 2024, ...]
let _PICK_TARGET = "desde";   // "desde" | "hasta"
let _PICK_YEAR = null;        // año visible en el modal
let _PICK_SELECTED_YM = null; // "YYYY-MM"
// ── Estado global base ──
let _ALL_SERIES = [];
let _ALL_DATES  = [];

// Preset regulatorio solicitado para análisis de agua.
const WATER_PRESET_RULES = [
  ["icc cordoba", "mano de obra empalme"],
  ["ipc cordoba", "electricidad"],
  ["ipim 24", "productos quimicos"],
  ["ipim ng", "nivel general"],
  ["icc cordoba", "nivel general empalme"],
  ["ipc cordoba servicios"],
  ["ipc cordoba", "bienes"],
  ["ipim 34", "vehiculos automotores"],
  ["ipim 29", "maquinas y equipos"],
  ["ipc cordoba", "otros combustibles"],
  ["ipc cordoba", "regulados"],
  ["ipc cordoba", "alquiler de vivienda"],
  ["jus", "cordoba"],
  ["ipc cordoba", "nivel general"],
  ["ipc cordoba", "seguros y servicios financieros"],
];

// Set de índices elegidos (fuente única de verdad para selector y asistente).
const _SELECTED_INDICES = new Set();

// Buffers TSV (para copiar)
let __TSV__ = "";
let __TSV_VARS__ = "";

// Estado de la evolución integrada dentro del panel principal.
let _INLINE_EVOLUTION_CACHE = null;
let _INLINE_EVOLUTION_MODE = ["values", "base100", "mom"].includes(localStorage.getItem("cyt-evolution-mode"))
  ? localStorage.getItem("cyt-evolution-mode")
  : "values";
let _INLINE_EVOLUTION_REQUEST = 0;
// ════════════════════════════════
// MODO NOCTURNO
// ════════════════════════════════

function initTheme() {
  // Leer preferencia guardada, o usar preferencia del sistema como fallback
  const saved = localStorage.getItem("cyt-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = saved ?? (prefersDark ? "dark" : "light");
  applyTheme(theme);
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const icon = theme === "dark" ? "☀️" : "🌙";
  const btn = document.getElementById("btn_theme");
  const menuBtn = document.getElementById("btn_theme_menu");
  if (btn) btn.textContent = icon;
  if (menuBtn) menuBtn.textContent = icon;
  localStorage.setItem("cyt-theme", theme);

  // Plotly no relee automáticamente las variables CSS al cambiar de tema.
  if (_INLINE_EVOLUTION_CACHE) {
    window.requestAnimationFrame(() => renderInlineEvolutionFromCache());
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") ?? "light";
  applyTheme(current === "dark" ? "light" : "dark");
}

// ════════════════════════════════
// UTILIDADES DE API
// ════════════════════════════════

async function api(path, options = {}) {
  const token = getToken();
  let r;
  try {
    r = await fetch(apiUrl(path), {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers ?? {}),
      },
    });
  } catch (networkError) {
    throw new Error(
      "No se pudo contactar al backend de Costos y Tarifas. Revisá la conexión o el estado del servicio en Render."
    );
  }
  if (r.status === 401) {
    handleLogout(true);
    throw new Error("Sesión expirada.");
  }
  if (!r.ok) {
    const contentType = r.headers.get("content-type") || "";
    let detail = `Error HTTP ${r.status}`;
    if (contentType.includes("application/json")) {
      const payload = await r.json().catch(() => ({}));
      detail = payload.detail || payload.message || detail;
    } else {
      const text = await r.text().catch(() => "");
      if (text.trim()) detail = text.trim();
    }
    throw new Error(detail);
  }
  return r.json();
}

function setUpdateStatus(message, type = "info") {
  const el = document.getElementById("update_status");
  if (!el) return;
  el.style.display = message ? "block" : "none";
  el.className = `update-status ${type}`;
  el.textContent = message || "";
}

function escapeUiHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function reportStatusLabel(status) {
  if (status === "ok") return "Correcto";
  if (status === "partial") return "Con observaciones";
  if (status === "error") return "Con errores";
  return status || "Sin estado";
}

function renderUpdateReport(data) {
  const box = document.getElementById("update_report_box");
  const report = document.getElementById("update_report");
  const raw = document.getElementById("update_report_raw");
  if (!box || !report) return;
  if (raw) raw.textContent = JSON.stringify(data, null, 2);

  const status = String(data?.status || (data?.ok ? "ok" : "error"));
  let html = `<div class="report-summary-head">
    <span class="report-status ${escapeUiHtml(status)}">${escapeUiHtml(reportStatusLabel(status))}</span>
    <div><strong>${escapeUiHtml(data?.message || "Resultado del proceso")}</strong>`;
  if (data?.checked_at) html += `<small>Diagnóstico realizado: ${escapeUiHtml(String(data.checked_at).replace("T", " "))}</small>`;
  if (data?.finished_at) html += `<small>Finalizado: ${escapeUiHtml(String(data.finished_at).replace("T", " "))}</small>`;
  html += `</div></div>`;

  if (Array.isArray(data?.results)) {
    const okCount = data.results.filter(item => item.ok).length;
    html += `<div class="report-metrics">
      <div><span>Fuentes revisadas</span><strong>${data.total_fuentes ?? data.results.length}</strong></div>
      <div><span>Respondieron bien</span><strong>${okCount}</strong></div>
      <div><span>Con error</span><strong>${data.fallidas ?? (data.results.length - okCount)}</strong></div>
    </div>`;
    html += `<div class="report-explainer">Una fuente en rojo significa que el sistema no pudo obtener sus datos. Una fecha anterior al resto puede ser simplemente rezago de publicación del organismo.</div>`;
    html += `<div class="report-table-wrap"><table class="report-table"><thead><tr><th>Fuente</th><th>Estado</th><th>Último dato</th><th>Filas</th><th>Detalle</th></tr></thead><tbody>`;
    html += data.results.map(item => `<tr>
      <td>${escapeUiHtml(item.fuente)}</td>
      <td><span class="source-state ${item.ok ? "ok" : "error"}">${item.ok ? "OK" : "Error"}</span></td>
      <td>${escapeUiHtml(item.ultima_fecha || "—")}</td>
      <td>${escapeUiHtml(item.filas ?? "—")}</td>
      <td>${escapeUiHtml(item.error || (item.ok ? "Fuente disponible" : "Sin detalle"))}</td>
    </tr>`).join("");
    html += `</tbody></table></div>`;
  } else {
    html += `<div class="report-metrics">
      <div><span>Celdas actualizadas</span><strong>${data?.updated_cells ?? 0}</strong></div>
      <div><span>Pendientes de publicación</span><strong>${data?.pending_count ?? 0}</strong></div>
      <div><span>Incidencias</span><strong>${data?.issue_count ?? 0}</strong></div>
      <div><span>Errores de fuente</span><strong>${data?.error_count ?? 0}</strong></div>
    </div>`;
    if (Array.isArray(data?.months_requested) && data.months_requested.length) {
      html += `<div class="report-explainer"><strong>Meses revisados:</strong> ${data.months_requested.map(escapeUiHtml).join(" · ")}</div>`;
    }
    const problems = [
      ...(Array.isArray(data?.errores) ? data.errores.map(x => ({ type: "error", title: x.modulo || "Fuente", text: x.error || "Error sin detalle" })) : []),
      ...(Array.isArray(data?.incidencias) ? data.incidencias.map(x => ({ type: "warn", title: x.indice || x.modulo || "Incidencia", text: x.motivo || "Revisar configuración" })) : []),
      ...(Array.isArray(data?.pendientes) ? data.pendientes.slice(0, 12).map(x => ({ type: "pending", title: x.indice || x.modulo || "Pendiente", text: `${x.mes || ""} ${x.motivo || "Dato todavía no publicado"}`.trim() })) : []),
    ];
    if (problems.length) {
      html += `<div class="report-issues">${problems.slice(0, 24).map(item => `<div class="report-issue ${item.type}"><strong>${escapeUiHtml(item.title)}</strong><span>${escapeUiHtml(item.text)}</span></div>`).join("")}</div>`;
    } else {
      html += `<div class="report-success-note">No se detectaron incidencias de configuración ni errores de fuente.</div>`;
    }
  }

  report.innerHTML = html;
  box.style.display = "block";
  box.open = true;
}

function setActualizarIndicesLoading(isLoading) {
  const btn = document.getElementById("btn_actualizar_indices");
  const txt = document.getElementById("txt_actualizar_indices");
  const spinner = document.getElementById("spinner_actualizar_indices");
  if (btn) btn.disabled = isLoading;
  if (txt) txt.textContent = isLoading ? "Actualizando..." : "Actualizar Índices Automáticamente 🔄";
  if (spinner) spinner.style.display = isLoading ? "inline-block" : "none";
}

async function handleDiagnosticarFuentes() {
  const btn = document.getElementById("btn_diagnosticar_fuentes");
  if (!btn) return;
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "Diagnosticando fuentes...";
  setUpdateStatus("Comprobando INDEC, BCRA e IPC Córdoba sin modificar Google Sheets.", "info");
  try {
    const result = await api("/api/diagnostico-fuentes");
    renderUpdateReport(result);
    const failed = Number(result?.fallidas || 0);
    if (failed === 0) {
      setUpdateStatus("Todas las fuentes respondieron correctamente. La planilla no fue modificada.", "success");
    } else {
      setUpdateStatus(`Diagnóstico finalizado. Fuentes con error: ${failed}. Revisá el reporte técnico.`, "warn");
    }
  } catch (e) {
    const msg = e?.message ?? "No se pudo completar el diagnóstico.";
    setUpdateStatus("Error al diagnosticar fuentes: " + msg, "error");
    renderUpdateReport({ status: "error", detail: msg });
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function handleActualizarIndices() {
  const btn = document.getElementById("btn_actualizar_indices");
  if (!btn) return;

  setActualizarIndicesLoading(true);
  setUpdateStatus("Actualizando índices. El proceso puede demorar porque consulta INDEC, BCRA, IPC Córdoba y luego escribe en Google Sheets.", "info");

  try {
    const started = await api("/api/actualizar-indices", { method: "POST" });
    if (!started?.job_id) throw new Error("El servidor no devolvió el identificador de la actualización.");
    if (started.created === false) {
      setUpdateStatus("Ya había una actualización en ejecución. Se retomó el seguimiento de su progreso.", "info");
    }
    const result = await waitForIndexUpdate(started.job_id);
    renderUpdateReport(result);

    if (result.status === "ok") {
      const pending = Number(result.pending_count || 0);
      const suffix = pending ? ` Datos aún no publicados: ${pending}; no se modificaron esas celdas.` : "";
      setUpdateStatus(`Actualización completa. Celdas actualizadas: ${result.updated_cells}.${suffix}`, "success");
    } else if (result.status === "partial") {
      setUpdateStatus(`Actualización parcial. Celdas actualizadas: ${result.updated_cells}. Incidencias de configuración: ${result.issue_count || 0}. Errores de fuente: ${result.error_count}. Pendientes de publicación: ${result.pending_count || 0}.`, "warn");
    } else {
      setUpdateStatus("No se pudo completar la actualización. Revisá el reporte técnico.", "error");
    }

    await init();
  } catch (e) {
    const msg = e?.message ?? "Error desconocido al actualizar índices.";
    setUpdateStatus("Error al actualizar índices: " + msg, "error");
    renderUpdateReport({ status: "error", detail: msg });
  } finally {
    setActualizarIndicesLoading(false);
  }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForIndexUpdate(jobId) {
  const deadline = Date.now() + 30 * 60 * 1000;
  let consecutiveNetworkErrors = 0;
  while (Date.now() < deadline) {
    try {
      const job = await api(`/api/actualizar-indices/${encodeURIComponent(jobId)}`);
      consecutiveNetworkErrors = 0;
      if (job.status === "COMPLETED") return job.result || {};
      if (job.status === "ERROR") {
        const terminalError = new Error(job.error || job.message || "La actualización no pudo completarse.");
        terminalError.terminalUpdate = true;
        throw terminalError;
      }
      setUpdateStatus(job.message || "Actualización en ejecución...", "info");
    } catch (error) {
      if (error?.terminalUpdate || !isLoggedIn() || /actualización no encontrada|expirada|sesión expirada/i.test(error?.message || "")) throw error;
      consecutiveNetworkErrors += 1;
      if (consecutiveNetworkErrors >= 5) throw error;
      setUpdateStatus("El servidor demoró en responder. La actualización sigue en curso y se reintentará automáticamente.", "warn");
    }
    await delay(1800);
  }
  throw new Error("La actualización superó los 30 minutos. Volvé a presionar el botón para retomar el seguimiento.");
}

// ════════════════════════════════
// FILTRADO EN TIEMPO REAL
// ════════════════════════════════

function normalizeSeriesUiText(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function seriesGroupName(name) {
  const n = normalizeSeriesUiText(name);
  if (n.includes("ipc cordoba")) return "IPC Córdoba";
  if (n.includes("ipc indec") || n.includes("empalme ipc indec")) return "IPC INDEC";
  if (n.includes("icc cordoba")) return "ICC Córdoba";
  if (n.includes("icc indec")) return "ICC INDEC";
  if (n.includes("ipim")) return "IPIM";
  if (n.includes("salario") || n.includes("ripte")) return "Salarios y RIPTE";
  if (n.includes("dolar") || n.includes("tipo de cambio") || n.includes("badlar") || n.includes("cer") || n.includes("icl") || n.includes("uva")) return "Moneda, tasas y contratos";
  if (n.includes("iop cordoba") || n.includes("obras publicas")) return "Obra Pública Córdoba";
  if (n.includes("vga") || n.includes("agua en bloque") || n.includes("agua cruda") || n.includes("canon precio") || n.includes("rac") || n.includes("fam")) return "Agua, RAC y EPEC";
  if (n.includes("jus") || n.includes("cpce")) return "JUS y CPCE Córdoba";
  return "Otros índices";
}

function renderSeriesCheckboxes() {
  const container = document.getElementById("series_groups");
  if (!container) return;
  const groups = new Map();
  for (const series of _ALL_SERIES) {
    const id = String(series.id ?? series.idx ?? "");
    const name = String(series.name ?? id);
    if (!id) continue;
    const group = seriesGroupName(name);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push({ id, name });
  }

  container.innerHTML = Array.from(groups.entries()).map(([group, items], index) => `
    <details class="series-group" ${index < 2 ? "open" : ""} data-group-name="${escapeUiHtml(group)}">
      <summary><span>${escapeUiHtml(group)}</span><small>${items.length} índices</small></summary>
      <div class="series-check-list">
        ${items.map(item => `<label class="series-check-item" data-search="${escapeUiHtml(normalizeSeriesUiText(item.name))}">
          <input type="checkbox" data-series-id="${escapeUiHtml(item.id)}">
          <span>${escapeUiHtml(item.name)}</span>
        </label>`).join("")}
      </div>
    </details>`).join("");
  sincronizarSelectVisual();
}

function filterSeriesCheckboxes(termRaw) {
  const term = normalizeSeriesUiText(termRaw);
  document.querySelectorAll("#series_groups .series-group").forEach(group => {
    let visibleCount = 0;
    group.querySelectorAll(".series-check-item").forEach(item => {
      const visible = !term || (item.dataset.search || "").includes(term);
      item.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    group.hidden = visibleCount === 0;
    if (term && visibleCount > 0) group.open = true;
  });
}

function setupFilter(inputId) {
  const input = document.getElementById(inputId);
  if (!input || input.dataset.ready === "1") return;
  input.dataset.ready = "1";
  input.addEventListener("input", (e) => filterSeriesCheckboxes(e.target.value));
}

function setStatsTab(name) {
  document.querySelectorAll("[data-stats-tab]").forEach(button => {
    const active = button.dataset.statsTab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-stats-panel]").forEach(panel => {
    panel.classList.toggle("active", panel.dataset.statsPanel === name);
  });
  localStorage.setItem("cyt-stats-tab", name);
}

function setupStatsTabs() {
  document.querySelectorAll("[data-stats-tab]").forEach(button => {
    if (button.dataset.ready === "1") return;
    button.dataset.ready = "1";
    button.addEventListener("click", () => setStatsTab(button.dataset.statsTab));
  });
  const saved = localStorage.getItem("cyt-stats-tab");
  setStatsTab(["consulta", "resultados", "asistente", "actualizacion"].includes(saved) ? saved : "consulta");
}

function findSeriesByPresetRule(rule) {
  return _ALL_SERIES.find(series => {
    const n = normalizeSeriesUiText(series.name ?? series.id ?? "");
    return rule.every(fragment => n.includes(normalizeSeriesUiText(fragment)));
  });
}

function selectWaterPreset() {
  _SELECTED_INDICES.clear();
  const matched = [];
  for (const rule of WATER_PRESET_RULES) {
    const series = findSeriesByPresetRule(rule);
    const id = series ? String(series.id ?? series.idx ?? "") : "";
    if (id && !_SELECTED_INDICES.has(id)) {
      _SELECTED_INDICES.add(id);
      matched.push(series.name);
    }
  }
  sincronizarSelectVisual();
  actualizarPanelIndicesElegidos();
  filterSeriesCheckboxes(document.getElementById("search_series")?.value || "");
  return matched;
}
window.selectWaterPreset = selectWaterPreset;
// ════════════════════════════════
// Panel para ver índices elegidos
// ════════════════════════════════
function actualizarPanelIndicesElegidos() {
  const selected = Array.from(_SELECTED_INDICES);
  syncEvolutionSelectionUI(selected);

  const panel = document.getElementById("panel_indices_elegidos");
  const lista = document.getElementById("lista_indices_elegidos");
  const btnT  = document.getElementById("btn_toggle_panel");

  if (selected.length === 0) {
    panel.style.display = "none";
    lista.innerHTML = "";
    return;
  }

  panel.style.display = "block";

  // Aplicar estado colapsado recordado
  panel.classList.toggle("collapsed", isPanelCollapsed());
  if (btnT) btnT.textContent = isPanelCollapsed() ? "▸" : "▾";

  // Si está colapsado, no hace falta regenerar lista (pero podemos igual)
  lista.innerHTML = selected
    .map(value => {
      const option = document.querySelector(`#sel_col option[value="${CSS.escape(value)}"]`);
      const nombre = option ? option.text.trim() : value;
      return `<div class="panel-indices-item" data-value="${value}">${nombre}</div>`;
    })
    .join("");

  document.querySelectorAll(".panel-indices-item").forEach(el => {
    el.addEventListener("click", () => {
      const value = el.getAttribute("data-value");
      _SELECTED_INDICES.delete(value);
      sincronizarSelectVisual();
      actualizarPanelIndicesElegidos();
    });
  });
}


function sincronizarSelectVisual() {
  const select = document.getElementById("sel_col");
  if (select) {
    for (const option of select.options) option.selected = _SELECTED_INDICES.has(option.value);
  }
  document.querySelectorAll("#series_groups input[data-series-id]").forEach(input => {
    input.checked = _SELECTED_INDICES.has(input.dataset.seriesId);
  });
}
function isPanelCollapsed() {
  return localStorage.getItem("panel_indices_collapsed") === "1";
}

function setPanelCollapsed(v) {
  localStorage.setItem("panel_indices_collapsed", v ? "1" : "0");
}
// ════════════════════════════════
// FORMATEO DE FECHAS
// ════════════════════════════════

function formatDateLabel(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s).trim());
  if (!m) return s;

  const year  = Number(m[1]);
  const month = Number(m[2]);
  const day   = Number(m[3]);

  if (!year || month < 1 || month > 12 || day < 1 || day > 31) return s;

  const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
  return `${meses[month - 1]}-${year}`;
}
// ════════════════════════════════
// Renderizado del monthpicker para dummies
// ════════════════════════════════
function ymKeyFromIso(iso) {
  const m = /^(\d{4})-(\d{2})-\d{2}$/.exec(String(iso).trim());
  return m ? `${m[1]}-${m[2]}` : null;
}

function labelFromYm(ym) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(ym));
  if (!m) return ym;
  const y = Number(m[1]);
  const mm = Number(m[2]);
  const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
  return `${meses[mm-1]}-${y}`;
}

function rebuildDatesIndex() {
  _DATES_BY_YM = new Map();
  const yearsSet = new Set();

  for (const d of (_ALL_DATES || [])) {
    const iso = String(d.value ?? "").trim();
    const ym = ymKeyFromIso(iso);
    if (!ym) continue;
    // Si hubiese repetidos en el mismo mes, me quedo con el primero (suficiente para series mensuales)
    if (!_DATES_BY_YM.has(ym)) _DATES_BY_YM.set(ym, iso);
    yearsSet.add(Number(ym.slice(0,4)));
  }
  _YEARS = Array.from(yearsSet).filter(Number.isFinite).sort((a,b)=>a-b);
}

function setPickValue(target, isoDate) {
  const sel = document.getElementById(target === "desde" ? "sel_desde" : "sel_hasta");
  sel.value = isoDate;

  // Actualizar texto visible (Ene-2025)
  const ym = ymKeyFromIso(isoDate);
  const txt = target === "desde" ? document.getElementById("txt_desde") : document.getElementById("txt_hasta");
  txt.textContent = ym ? labelFromYm(ym) : formatDateLabel(isoDate);

  if (_INLINE_EVOLUTION_CACHE) {
    invalidateInlineEvolution("El período cambió. Actualizá los gráficos para recalcular la evolución.");
  }
}


function normalizeDateRange(changedTarget = null) {
  const desde = document.getElementById("sel_desde").value;
  const hasta = document.getElementById("sel_hasta").value;
  if (!desde || !hasta || desde <= hasta) return;

  // La fecha que el usuario acaba de mover prevalece; la otra se ajusta.
  if (changedTarget === "desde") {
    setPickValue("hasta", desde);
  } else if (changedTarget === "hasta") {
    setPickValue("desde", hasta);
  } else {
    setPickValue("desde", hasta);
    setPickValue("hasta", desde);
  }
}

function shiftPickValue(target, delta) {
  if (!_ALL_DATES.length) return;
  const select = document.getElementById(target === "desde" ? "sel_desde" : "sel_hasta");
  const currentIndex = _ALL_DATES.findIndex(item => String(item.value) === String(select.value));
  const origin = currentIndex >= 0 ? currentIndex : (_ALL_DATES.length - 1);
  const nextIndex = Math.max(0, Math.min(_ALL_DATES.length - 1, origin + Number(delta || 0)));
  setPickValue(target, _ALL_DATES[nextIndex].value);
  normalizeDateRange(target);
}

function openMonthPicker(target) {
  _PICK_TARGET = target;

  // Año inicial: el de la selección actual, si existe, si no el último año disponible
  const currentIso = document.getElementById(target === "desde" ? "sel_desde" : "sel_hasta").value;
  const curYm = ymKeyFromIso(currentIso);
  _PICK_SELECTED_YM = curYm;

  const fallbackYear = _YEARS.length ? _YEARS[_YEARS.length - 1] : (new Date()).getFullYear();
  _PICK_YEAR = curYm ? Number(curYm.slice(0,4)) : fallbackYear;

  renderMonthPicker();
  document.getElementById("monthModal").style.display = "block";
}

function closeMonthPicker() {
  document.getElementById("monthModal").style.display = "none";
}

function renderMonthPicker() {
  const yearLabel = document.getElementById("yearLabel");
  const grid = document.getElementById("monthGrid");
  const help = document.getElementById("monthHelp");
  const prev5 = document.getElementById("yearPrev5");
  const prev = document.getElementById("yearPrev");
  const next = document.getElementById("yearNext");
  const next5 = document.getElementById("yearNext5");

  yearLabel.textContent = String(_PICK_YEAR);

  const minY = _YEARS.length ? _YEARS[0] : _PICK_YEAR;
  const maxY = _YEARS.length ? _YEARS[_YEARS.length - 1] : _PICK_YEAR;

  prev5.disabled = _PICK_YEAR <= minY;
  prev.disabled = _PICK_YEAR <= minY;
  next.disabled = _PICK_YEAR >= maxY;
  next5.disabled = _PICK_YEAR >= maxY;

  const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];

  grid.innerHTML = meses.map((name, i) => {
    const mm = String(i+1).padStart(2,"0");
    const ym = `${_PICK_YEAR}-${mm}`;
    const iso = _DATES_BY_YM.get(ym);
    const isDisabled = !iso;
    const isActive = _PICK_SELECTED_YM === ym;

    return `<div class="month-item ${isDisabled ? "disabled":""} ${isActive ? "active":""}"
                data-ym="${ym}" data-iso="${iso ?? ""}">
              ${name}
            </div>`;
  }).join("");

  help.textContent = _PICK_TARGET === "desde"
    ? "Elegí el mes de inicio"
    : "Elegí el mes final";

  // Click en mes
  grid.querySelectorAll(".month-item").forEach(el => {
    el.addEventListener("click", () => {
      if (el.classList.contains("disabled")) return;
      _PICK_SELECTED_YM = el.getAttribute("data-ym");
      // refresco visual
      renderMonthPicker();
    });
  });
}

// ════════════════════════════════
// INICIALIZACIÓN
// ════════════════════════════════

async function init() {
  try {
    const meta = await api("/api/meta");
    _ALL_SERIES = meta.value_columns;
    _ALL_DATES = Array.from(
      new Map((meta.index_values || []).map(item => [String(item.value), item])).values()
    ).sort((a, b) => String(a.value).localeCompare(String(b.value)));

    // Poblar selector nativo oculto (compatibilidad) y el selector visual por checks.
    document.getElementById("sel_col").innerHTML = _ALL_SERIES
      .map((s) => `<option value="${String(s.id ?? s.idx)}">${s.name}</option>`)
      .join("");
    renderSeriesCheckboxes();

    // Poblar selectores de fechas (ocultos, pero se usan igual)
    const dateHtml = _ALL_DATES
      .map((d) => `<option value="${String(d.value)}">${String(d.label)}</option>`)
      .join("");

    document.getElementById("sel_desde").innerHTML = dateHtml;
    document.getElementById("sel_hasta").innerHTML = dateHtml;

    const last = _ALL_DATES[_ALL_DATES.length - 1]?.value ?? "";
    const previous = _ALL_DATES[Math.max(0, _ALL_DATES.length - 2)]?.value ?? last;

    document.getElementById("sel_desde").value = previous;
    document.getElementById("sel_hasta").value = last;

    // Por defecto se muestra el último mes disponible y el inmediatamente anterior.
    rebuildDatesIndex();
    if (previous) setPickValue("desde", previous);
    if (last) setPickValue("hasta", last);

    // Activar filtros en tiempo real y navegación por etapas.
    setupFilter("search_series");
    setupStatsTabs();

    // Status y accesos directos a la base.
    const btnSheet = document.getElementById("btn_abrir_sheet");
    const btnSheetSecondary = document.getElementById("btn_abrir_sheet_secondary");
    if (btnSheet && meta.sheet_url) btnSheet.href = meta.sheet_url;
    if (btnSheetSecondary && meta.sheet_url) btnSheetSecondary.href = meta.sheet_url;

    document.getElementById("status").textContent =
      `Base conectada · pestaña ${meta.worksheet || "configurada"}`;

    if (typeof window.initStatsChatbotCatalog === "function") {
      window.initStatsChatbotCatalog(_ALL_SERIES, _ALL_DATES);
    }

  } catch (e) {
    document.getElementById("status").textContent = "⚠ Error: " + e.message;
  }

  actualizarPanelIndicesElegidos();
}


// ════════════════════════════════
// EXPORTACIÓN TSV
// ════════════════════════════════

function cleanTsvCell(v) {
  return String(v ?? "")
    .replace(/\t/g, " ")
    .replace(/\r?\n/g, " ")
    .replace(/\r/g, " ")
    .trim();
}

function toTsvFixed(header, rows) {
  const n   = header.length;
  const out = [header.map(cleanTsvCell).join("\t")];
  for (const row of rows) {
    const fixed = [];
    for (let i = 0; i < n; i++) fixed.push(cleanTsvCell(row?.[i] ?? ""));
    out.push(fixed.join("\t"));
  }
  return out.join("\r\n");
}

function isNumericLike(v) {
  if (v === null || v === undefined) return false;
  const s = String(v).trim();
  if (!s) return false;
  if (/^-?\d{1,3}(\.\d{3})*(,\d+)?$/.test(s)) return true;
  return /^-?\d{1,3}(,\d{3})*(\.\d+)?$/.test(s) || /^-?\d+(\.\d+)?$/.test(s);
}

function toEsNumberString(v, decimals = null) {
  const s0 = String(v).trim();
  let s = s0;

  if (s.includes(",") && !s.includes(".")) return s;

  if (s.includes(",") && s.includes(".")) {
    s = s.indexOf(",") < s.indexOf(".") ? s.replace(/,/g, "") : s; // EN → quitar miles
    if (s === s0) return s; // ya era ES
  }

  const num = Number(s);
  if (!Number.isFinite(num)) return s0;

  const opts = decimals === null
    ? { maximumFractionDigits: 20 }
    : { minimumFractionDigits: decimals, maximumFractionDigits: decimals };

  return num.toLocaleString("es-AR", opts).replace(/\./g, "");
}

function toTsvFromTable(headers, rows) {
  const headerClean = headers.map(cleanTsvCell);
  const outRows = rows.map((row) =>
    headerClean.map((_, i) => {
      if (i === 0) return cleanTsvCell(row?.[i] ?? "");
      const v = row?.[i];
      return isNumericLike(v) ? cleanTsvCell(toEsNumberString(v)) : cleanTsvCell(v ?? "");
    })
  );
  return toTsvFixed(headerClean, outRows);
}

// ════════════════════════════════
// GRÁFICO DE VARIACIONES
// ════════════════════════════════

function renderVariacionesChart(data, desdeRaw, hastaRaw) {
  const cont    = document.getElementById("chart_body");
  const titleEl = document.getElementById("chart_title");

  const items = (data || [])
    .filter((x) => typeof x.variacion === "number" && Number.isFinite(x.variacion))
    .map((x) => ({ serie: String(x.serie ?? ""), variacion: x.variacion }));

  items.sort((a, b) => b.variacion - a.variacion);

  const avg = items.length
    ? items.reduce((acc, x) => acc + x.variacion, 0) / items.length
    : null;

  // Título
  const desdeLbl = formatDateLabel(desdeRaw);
  const hastaLbl = formatDateLabel(hastaRaw);
  titleEl.textContent = `Variación porcentual | ${desdeLbl} → ${hastaLbl}`;

  if (items.length === 0) {
    cont.innerHTML = `<div class="chart-zero">No hay variaciones numéricas para graficar.</div>`;
    return;
  }

  const maxAbs = Math.max(...items.map((x) => Math.abs(x.variacion))) || 1;

  if (avg !== null && Number.isFinite(avg)) {
    // Insertar el promedio en la posición que le corresponde por valor
    const insertAt = items.findIndex((x) => x.variacion < avg);
    const avgItem  = { serie: "Promedio", variacion: avg, isAvg: true };
    if (insertAt === -1) {
      items.push(avgItem);          // es el menor de todos
    } else {
      items.splice(insertAt, 0, avgItem);
    }
  }

  const allHtml = items.map((it, idx) => {
    const widthPct = Math.max(2, (Math.abs(it.variacion) / maxAbs) * 100);
    const isPos    = it.variacion >= 0;
    const barColor = it.isAvg ? "#38bdf8" : (isPos ? "var(--success)" : "var(--danger)");
    const valColor = it.isAvg ? "style=\"color:#38bdf8;\"" : "";
    const rowClass = it.isAvg ? "chart-row avg-row" : "chart-row";
    const vTxt     = toEsNumberString(it.variacion, 2);
    const delay    = `animation-delay:${idx * 30}ms`;

    return `
      <div class="${rowClass}" style="${delay}">
        <div class="chart-label" title="${it.serie}">${it.serie}</div>
        <div class="chart-bar-wrap">
          <div class="chart-bar" style="width:${widthPct}%; background:${barColor};"></div>
        </div>
        <div class="chart-value ${isPos ? "up" : "down"}" ${valColor}>${vTxt}%</div>
      </div>`;
  }).join("");

  cont.innerHTML = allHtml;
  }

// ════════════════════════════════
// EVOLUCIÓN INTEGRADA EN EL PANEL PRINCIPAL
// ════════════════════════════════

function seriesLabelByValue(value) {
  const option = document.querySelector(`#sel_col option[value="${CSS.escape(String(value))}"]`);
  return option?.textContent?.trim() || String(value || "");
}

function formatMetricNumber(value, decimals = 2, suffix = "") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("es-AR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}${suffix}`;
}

function setMetricTone(elementId, value) {
  const element = document.getElementById(elementId);
  if (!element) return;
  element.classList.remove("positive", "negative");
  if (typeof value === "number" && Number.isFinite(value)) {
    element.classList.add(value >= 0 ? "positive" : "negative");
  }
}

function invalidateInlineEvolution(message = "La selección cambió. Actualizá los gráficos para ver los nuevos datos.") {
  if (!_INLINE_EVOLUTION_CACHE) return;
  _INLINE_EVOLUTION_CACHE = null;
  emptyEvolutionChart("inline_line_chart", "Gráficos pendientes de actualización", message);
  emptyEvolutionChart("inline_mom_chart", "Esperando actualización", "La variación mensual se recalculará con el nuevo período o selección.");
  const subtitle = document.getElementById("evol_line_subtitle");
  if (subtitle) subtitle.textContent = "Selección modificada · actualizá los gráficos";
}

function syncEvolutionSelectionUI(selectedValues = Array.from(_SELECTED_INDICES)) {
  const values = selectedValues.filter(Boolean);
  if (_INLINE_EVOLUTION_CACHE) {
    const cached = (_INLINE_EVOLUTION_CACHE.series || []).map(item => String(item.col)).sort();
    const current = values.map(String).sort();
    if (cached.length !== current.length || cached.some((value, index) => value !== current[index])) {
      invalidateInlineEvolution();
    }
  }
  const counter = document.getElementById("selected_series_count");
  const summaryCounter = document.getElementById("evol_metric_series_count");
  if (counter) counter.textContent = String(values.length);
  if (summaryCounter) summaryCounter.textContent = String(values.length);

  const picker = document.getElementById("evol_main_series");
  if (!picker) return;

  const previous = picker.value;
  picker.innerHTML = values.length
    ? values.map(value => `<option value="${String(value).replace(/"/g, "&quot;")}">${seriesLabelByValue(value)}</option>`).join("")
    : `<option value="">Sin series seleccionadas</option>`;

  if (values.includes(previous)) picker.value = previous;
  else if (values.length) picker.value = values[0];

  document.querySelectorAll("[data-evol-mode]").forEach(button => {
    button.classList.toggle("active", button.dataset.evolMode === _INLINE_EVOLUTION_MODE);
  });
}

function scrollToEvolution() {
  const section = document.getElementById("evolution-section");
  if (!section) return;
  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

function openStatsEvolution() {
  showApp();
  window.setTimeout(scrollToEvolution, 80);
}

function plotlyTheme() {
  const css = getComputedStyle(document.documentElement);
  return {
    text: css.getPropertyValue("--text").trim() || "#0f172a",
    muted: css.getPropertyValue("--text-muted").trim() || "#64748b",
    grid: css.getPropertyValue("--border").trim() || "#dde1eb",
    accent: css.getPropertyValue("--accent-mid").trim() || "#2563eb",
    success: css.getPropertyValue("--success").trim() || "#059669",
    danger: css.getPropertyValue("--danger").trim() || "#dc2626",
  };
}

function emptyEvolutionChart(containerId, title, text) {
  const element = document.getElementById(containerId);
  if (!element) return;
  if (window.Plotly && element.classList.contains("js-plotly-plot")) {
    window.Plotly.purge(element);
  }
  element.innerHTML = `
    <div class="chart-empty-state${containerId === "inline_mom_chart" ? " small" : ""}">
      <span class="chart-empty-icon">⌁</span>
      <strong>${title}</strong>
      <p>${text}</p>
    </div>`;
}

function selectedEvolutionSeries() {
  return Array.from(_SELECTED_INDICES)
    .filter(value => value && value !== "undefined" && value !== "null");
}

function mainEvolutionSeries(data) {
  const pickerValue = document.getElementById("evol_main_series")?.value;
  return data?.series?.find(item => String(item.col) === String(pickerValue)) || data?.series?.[0] || null;
}

function countValid(values) {
  return (values || []).filter(value => typeof value === "number" && Number.isFinite(value)).length;
}

function renderEvolutionMetrics(data) {
  const main = mainEvolutionSeries(data);
  const desde = document.getElementById("sel_desde")?.value || data?.desde || "";
  const hasta = document.getElementById("sel_hasta")?.value || data?.hasta || "";

  const countEl = document.getElementById("evol_metric_series_count");
  const periodEl = document.getElementById("evol_metric_period");
  const growthEl = document.getElementById("evol_metric_growth");
  const avgEl = document.getElementById("evol_metric_avg");

  if (countEl) countEl.textContent = String(data?.series?.length || 0);
  if (periodEl) periodEl.textContent = desde && hasta
    ? `${formatDateLabel(desde)} → ${formatDateLabel(hasta)}`
    : "—";

  const growth = main?.metrics?.total_growth_pct;
  const avg = main?.metrics?.avg_mom_pct;
  if (growthEl) growthEl.textContent = formatMetricNumber(growth, 2, "%");
  if (avgEl) avgEl.textContent = formatMetricNumber(avg, 2, "%");
  setMetricTone("evol_metric_growth", growth);
  setMetricTone("evol_metric_avg", avg);

  const title = document.getElementById("evol_insight_series");
  const best = document.getElementById("evol_best_month");
  const worst = document.getElementById("evol_worst_month");
  const vol = document.getElementById("evol_volatility");
  const observations = document.getElementById("evol_observations");

  if (title) title.textContent = main ? seriesLabelByValue(main.col) : "Sin serie seleccionada";
  if (best) best.textContent = main?.metrics?.best_month
    ? `${formatDateLabel(main.metrics.best_month.date)} · ${formatMetricNumber(main.metrics.best_month.pct, 2, "%")}`
    : "—";
  if (worst) worst.textContent = main?.metrics?.worst_month
    ? `${formatDateLabel(main.metrics.worst_month.date)} · ${formatMetricNumber(main.metrics.worst_month.pct, 2, "%")}`
    : "—";
  if (vol) vol.textContent = formatMetricNumber(main?.metrics?.vol_mom_pct, 2, "%");
  if (observations) observations.textContent = main ? String(countValid(main.values)) : "—";
}

function renderInlineLineChart(data) {
  const element = document.getElementById("inline_line_chart");
  if (!element || !window.Plotly) {
    emptyEvolutionChart("inline_line_chart", "No se pudo cargar el gráfico", "Revisá la conexión a internet y recargá la página.");
    return;
  }

  const dates = data?.dates || [];
  const main = mainEvolutionSeries(data);
  const theme = plotlyTheme();
  const mode = _INLINE_EVOLUTION_MODE;
  const field = mode === "base100" ? "base100" : (mode === "mom" ? "mom_pct" : "values");

  const traces = (data?.series || []).map(series => {
    const isMain = main && String(series.col) === String(main.col);
    const values = series[field] || [];
    return {
      type: "scatter",
      mode: dates.length <= 24 ? "lines+markers" : "lines",
      name: seriesLabelByValue(series.col),
      x: dates,
      y: values,
      connectgaps: false,
      line: { width: isMain ? 3.5 : 2 },
      marker: { size: isMain ? 6 : 4 },
      opacity: isMain ? 1 : 0.76,
      hovertemplate:
        "<b>%{fullData.name}</b><br>" +
        "%{x|%b-%Y}<br>" +
        (mode === "mom" ? "%{y:.2f}%" : "%{y:,.2f}") +
        "<extra></extra>",
    };
  });

  const titleByMode = {
    values: "Valores originales",
    base100: "Comparación normalizada · Base 100",
    mom: "Variación mensual (%)",
  };
  const subtitle = document.getElementById("evol_line_subtitle");
  if (subtitle) subtitle.textContent = `${titleByMode[mode]} · ${traces.length} serie${traces.length === 1 ? "" : "s"}`;

  const layout = {
    autosize: true,
    height: 430,
    margin: { l: 66, r: 24, t: 22, b: 72 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Open Sans, Arial, sans-serif", color: theme.text, size: 12 },
    hovermode: "x unified",
    legend: { orientation: "h", y: -0.23, x: 0, font: { color: theme.muted } },
    xaxis: {
      type: "date",
      tickformat: "%b-%Y",
      showgrid: false,
      zeroline: false,
      color: theme.muted,
      automargin: true,
      rangeslider: { visible: dates.length > 30, thickness: 0.06 },
    },
    yaxis: {
      title: mode === "mom" ? "Variación mensual (%)" : (mode === "base100" ? "Índice base 100" : "Valor"),
      ticksuffix: mode === "mom" ? "%" : "",
      showgrid: true,
      gridcolor: theme.grid,
      gridwidth: 1,
      zeroline: mode === "mom",
      zerolinecolor: theme.muted,
      color: theme.muted,
      automargin: true,
    },
  };

  window.Plotly.react(element, traces, layout, {
    responsive: true,
    displaylogo: false,
    scrollZoom: false,
    modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d"],
  });
}

function renderInlineMomChart(data) {
  const element = document.getElementById("inline_mom_chart");
  const main = mainEvolutionSeries(data);
  if (!element || !main || !window.Plotly) {
    emptyEvolutionChart("inline_mom_chart", "Esperando datos", "Elegí una serie principal y actualizá los gráficos.");
    return;
  }

  const theme = plotlyTheme();
  const x = [];
  const y = [];
  const markerColors = [];
  (data.dates || []).forEach((dateValue, index) => {
    const value = main.mom_pct?.[index];
    if (typeof value === "number" && Number.isFinite(value)) {
      x.push(dateValue);
      y.push(value);
      markerColors.push(value >= 0 ? theme.success : theme.danger);
    }
  });

  if (!x.length) {
    emptyEvolutionChart("inline_mom_chart", "Sin variaciones calculables", "El período necesita al menos dos observaciones numéricas.");
    return;
  }

  const trace = {
    type: "bar",
    name: seriesLabelByValue(main.col),
    x,
    y,
    marker: { color: markerColors },
    hovertemplate: "<b>%{x|%b-%Y}</b><br>%{y:.2f}%<extra></extra>",
  };
  const layout = {
    autosize: true,
    height: 300,
    margin: { l: 64, r: 24, t: 12, b: 54 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Open Sans, Arial, sans-serif", color: theme.text, size: 12 },
    showlegend: false,
    xaxis: { type: "date", tickformat: "%b-%Y", showgrid: false, color: theme.muted, automargin: true },
    yaxis: {
      title: "Variación mensual (%)",
      ticksuffix: "%",
      showgrid: true,
      gridcolor: theme.grid,
      zeroline: true,
      zerolinecolor: theme.muted,
      color: theme.muted,
      automargin: true,
    },
  };
  window.Plotly.react(element, [trace], layout, {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["select2d", "lasso2d"],
  });
}

function renderInlineEvolutionFromCache() {
  if (!_INLINE_EVOLUTION_CACHE) return;
  renderEvolutionMetrics(_INLINE_EVOLUTION_CACHE);
  renderInlineLineChart(_INLINE_EVOLUTION_CACHE);
  renderInlineMomChart(_INLINE_EVOLUTION_CACHE);
}

async function loadInlineEvolution({ silent = false, scroll = false } = {}) {
  const selected = selectedEvolutionSeries();
  if (!selected.length) {
    if (!silent) alert("Seleccioná al menos un índice para graficar su evolución.");
    emptyEvolutionChart("inline_line_chart", "La evolución aparecerá aquí", "Elegí una o más series en el panel superior.");
    emptyEvolutionChart("inline_mom_chart", "Esperando una serie principal", "La variación mensual se calcula a partir de la selección.");
    return;
  }

  const desde = document.getElementById("sel_desde").value;
  const hasta = document.getElementById("sel_hasta").value;
  if (desde > hasta) {
    if (!silent) alert("La fecha 'Desde' no puede ser posterior a 'Hasta'.");
    return;
  }

  const button = document.getElementById("btn_refresh_evolution");
  const originalText = button?.textContent || "Actualizar gráficos";
  if (button) {
    button.disabled = true;
    button.textContent = "Preparando gráficos...";
  }

  const requestId = ++_INLINE_EVOLUTION_REQUEST;
  try {
    const params =
      `col_idxs=${encodeURIComponent(selected.join(","))}` +
      `&desde=${encodeURIComponent(desde)}` +
      `&hasta=${encodeURIComponent(hasta)}`;
    const data = await api(`/api/series?${params}`);
    if (requestId !== _INLINE_EVOLUTION_REQUEST) return;
    _INLINE_EVOLUTION_CACHE = data;
    syncEvolutionSelectionUI(selected);
    renderInlineEvolutionFromCache();
    if (scroll) scrollToEvolution();
  } catch (error) {
    if (!silent) alert("No se pudo graficar la evolución: " + error.message);
    emptyEvolutionChart("inline_line_chart", "No se pudo construir el gráfico", error.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

// ════════════════════════════════
// ACCIÓN PRINCIPAL
// ════════════════════════════════

async function handleAction(type) {
  const btnId   = type === "tabla" ? "btn_filtrar" : "btn_analizar";
  const btnOrig = type === "tabla" ? "Ver tabla de datos filtrados" : "Calcular variaciones";
  const btn     = document.getElementById(btnId);

  // Validar selección
  const selected = Array.from(_SELECTED_INDICES)
    .filter(v => v && v !== "undefined" && v !== "null");

  if (selected.length === 0) return alert("Seleccioná al menos un índice.");

  const desde = document.getElementById("sel_desde").value;
  const hasta = document.getElementById("sel_hasta").value;

  if (desde > hasta) return alert("La fecha 'Desde' no puede ser posterior a 'Hasta'.");

  const params =
    `col_idxs=${encodeURIComponent(selected.join(","))}` +
    `&desde=${encodeURIComponent(desde)}` +
    `&hasta=${encodeURIComponent(hasta)}`;

  // Estado de carga
  btn.disabled    = true;
  btn.textContent = "Cargando...";

  try {
    if (type === "tabla") {
      document.getElementById("view_tabla").style.display    = "block";
      document.getElementById("view_analisis").style.display = "none";
      document.getElementById("view_grafico").style.display  = "none";
      const variationNotice = document.getElementById("variation_notice");
      if (variationNotice) variationNotice.style.display = "none";

      const data = await api(`/api/data?${params}`);

      document.querySelector("#tbl thead tr").innerHTML = data.headers
        .map((h) => `<th>${h}</th>`)
        .join("");

      document.querySelector("#tbl tbody").innerHTML = data.rows
        .map((row) =>
          `<tr>${row.map((v, i) => `<td class="${i > 0 ? "num" : ""}">${v}</td>`).join("")}</tr>`
        )
        .join("");

      __TSV__ = toTsvFromTable(data.headers, data.rows);

    } else if (type === "analisis") {
      document.getElementById("view_tabla").style.display    = "none";
      document.getElementById("view_analisis").style.display = "block";
      document.getElementById("view_grafico").style.display  = "block";

      const res = await api(`/api/variaciones?${params}`);

      // Labels de fechas (para headers y TSV)
      const desdeLbl = formatDateLabel(desde);
      const hastaLbl = formatDateLabel(hasta);

      // Ordenar por variación (desc), no calculables al final
      const items = Array.isArray(res.data) ? [...res.data] : [];
      items.sort((a, b) => {
        const va = (typeof a.variacion === "number" && Number.isFinite(a.variacion)) ? a.variacion : -Infinity;
        const vb = (typeof b.variacion === "number" && Number.isFinite(b.variacion)) ? b.variacion : -Infinity;
        return vb - va;
      });

      // Actualizar headers de la tabla de variaciones
      const ths = document.querySelectorAll("#tbl_vars thead th");
      if (ths && ths.length >= 4) {
        ths[1].textContent = desdeLbl;
        ths[2].textContent = hastaLbl;
      }

      // Gráfico (si tu función reordena internamente, igual funciona)
      renderVariacionesChart(items, desde, hasta);

      // Render tabla de variaciones + explicación cuando falta alguna punta.
      const noCalculables = items.filter((item) => !(typeof item.variacion === "number" && Number.isFinite(item.variacion)));
      const notice = document.getElementById("variation_notice");
      if (notice) {
        if (noCalculables.length) {
          const detalle = noCalculables.map((item) => {
            const faltan = Array.isArray(item.missing_points) ? item.missing_points : [];
            if (faltan.includes("inicio") && faltan.includes("fin")) return `${item.serie}: faltan ${desdeLbl} y ${hastaLbl}`;
            if (faltan.includes("inicio")) return `${item.serie}: falta ${desdeLbl}`;
            if (faltan.includes("fin")) return `${item.serie}: falta ${hastaLbl}`;
            if (item.reason === "initial_zero") return `${item.serie}: el valor inicial es 0`;
            return `${item.serie}: no hay dos puntas válidas`;
          });
          notice.innerHTML = `<strong>Hay variaciones que no pueden calcularse.</strong><span>${detalle.join(" · ")}</span>`;
          notice.style.display = "flex";
        } else {
          notice.style.display = "none";
          notice.innerHTML = "";
        }
      }

      document.querySelector("#tbl_vars tbody").innerHTML = items.map((item) => {
        const hasVar = typeof item.variacion === "number" && Number.isFinite(item.variacion);
        const faltan = Array.isArray(item.missing_points) ? item.missing_points : [];
        let reasonTxt = "";
        if (!hasVar) {
          if (faltan.includes("inicio") && faltan.includes("fin")) reasonTxt = `Faltan ${desdeLbl} y ${hastaLbl}`;
          else if (faltan.includes("inicio")) reasonTxt = `Falta ${desdeLbl}`;
          else if (faltan.includes("fin")) reasonTxt = `Falta ${hastaLbl}`;
          else if (item.reason === "initial_zero") reasonTxt = "Valor inicial igual a 0";
          else reasonTxt = "Sin dos puntas válidas";
        }
        const varTxt = hasVar
          ? toEsNumberString(item.variacion, 2) + "%"
          : `<span class="missing-point-badge">No calculable</span><small class="missing-point-reason">${reasonTxt}</small>`;
        const varCls = hasVar ? (item.variacion >= 0 ? "up" : "down") : "na";

        const iniTxt = typeof item.inicial === "number" && Number.isFinite(item.inicial)
          ? toEsNumberString(item.inicial, 2) : `<span class="endpoint-missing">Sin dato</span>`;
        const finTxt = typeof item.final === "number" && Number.isFinite(item.final)
          ? toEsNumberString(item.final, 2) : `<span class="endpoint-missing">Sin dato</span>`;

        return `
          <tr>
            <td>${item.serie ?? ""}</td>
            <td class="num">${iniTxt}</td>
            <td class="num">${finTxt}</td>
            <td class="num ${varCls}">${varTxt}</td>
          </tr>`;
      }).join("");

      // TSV exportable (mismo orden que la tabla)
      const header = ["Índice", desdeLbl, hastaLbl, "Variación"];
      const rows = items.map((item) => {
        const fmtNum = (v) => (typeof v === "number" && Number.isFinite(v)) ? toEsNumberString(v, 2) : "";
        const varOut = (typeof item.variacion === "number" && Number.isFinite(item.variacion))
          ? (toEsNumberString(item.variacion, 2) + "%")
          : "No calculable";
        return [item.serie ?? "", fmtNum(item.inicial), fmtNum(item.final), varOut];
      });

      __TSV_VARS__ = toTsvFixed(header, rows);

    } else {
      alert("Acción desconocida: " + type);
      return;
    }

    // Llevar al usuario a la etapa siguiente sin obligarlo a desplazarse por toda la página.
    setStatsTab("resultados");

  } catch (e) {
    alert("Error al procesar la solicitud: " + e.message);
  } finally {
    btn.disabled    = false;
    btn.textContent = btnOrig;
  }
}
// ════════════════════════════════
// EVENT LISTENERS | Son los que te actualizan
// ════════════════════════════════

document.getElementById("btn_sel_all").onclick = () => {
  document.querySelectorAll("#series_groups .series-check-item:not([hidden]) input[data-series-id]").forEach(input => {
    if (!input.closest(".series-group")?.hidden) _SELECTED_INDICES.add(input.dataset.seriesId);
  });
  sincronizarSelectVisual();
  actualizarPanelIndicesElegidos();
};

document.getElementById("btn_desel").onclick = () => {
  _SELECTED_INDICES.clear();
  sincronizarSelectVisual();
  actualizarPanelIndicesElegidos();
};

const btnWaterPreset = document.getElementById("btn_sel_water");
if (btnWaterPreset) btnWaterPreset.onclick = () => {
  const matched = selectWaterPreset();
  btnWaterPreset.textContent = `💧 Datos de agua seleccionados (${matched.length})`;
  window.setTimeout(() => { btnWaterPreset.textContent = "💧 Autoseleccionar datos de agua"; }, 1800);
};

const seriesGroups = document.getElementById("series_groups");
if (seriesGroups) seriesGroups.addEventListener("change", event => {
  const input = event.target.closest("input[data-series-id]");
  if (!input) return;
  if (input.checked) _SELECTED_INDICES.add(input.dataset.seriesId);
  else _SELECTED_INDICES.delete(input.dataset.seriesId);
  sincronizarSelectVisual();
  actualizarPanelIndicesElegidos();
});

const expandGroups = document.getElementById("btn_expand_groups");
if (expandGroups) expandGroups.onclick = () => document.querySelectorAll("#series_groups .series-group:not([hidden])").forEach(group => { group.open = true; });
const collapseGroups = document.getElementById("btn_collapse_groups");
if (collapseGroups) collapseGroups.onclick = () => document.querySelectorAll("#series_groups .series-group").forEach(group => { group.open = false; });


// Navegación del portal y accesos directos.
document.getElementById("btn_menu").onclick = showMenu;
document.getElementById("btn_it").onclick = () => { window.location.href = "./generar-it.html"; };
document.getElementById("btn_incidencia").onclick = () => { window.location.href = "./incidencia.html"; };
document.getElementById("btn_boletin").onclick = () => { window.location.href = "./boletin.html"; };
document.getElementById("btn_cumple").onclick = () => { window.location.href = "./cumpleanos.html"; };
document.getElementById("btn_cumple_rrhh").onclick = () => { window.location.href = RRHH_PORTAL_URL; };

document.getElementById("menu_stats").onclick = showApp;
document.getElementById("menu_arca").onclick = () => { window.location.href = "./calculo.html"; };
document.getElementById("menu_it").onclick = () => { window.location.href = "./generar-it.html"; };
document.getElementById("menu_incidencia").onclick = () => { window.location.href = "./incidencia.html"; };
document.getElementById("menu_boletin").onclick = () => { window.location.href = "./boletin.html"; };
document.getElementById("menu_transporte").onclick = () => { window.location.href = "./transporte.html"; };
document.getElementById("menu_cumple").onclick = () => { window.location.href = "./cumpleanos.html"; };
document.getElementById("menu_cumple_rrhh").onclick = () => { window.location.href = RRHH_PORTAL_URL; };
document.getElementById("btn_filtrar").onclick  = () => handleAction("tabla");
document.getElementById("btn_analizar").onclick = () => handleAction("analisis");
const btnAnalizarResultados = document.getElementById("btn_analizar_resultados");
if (btnAnalizarResultados) btnAnalizarResultados.onclick = () => handleAction("analisis");
const btnActualizarIndices = document.getElementById("btn_actualizar_indices");
if (btnActualizarIndices) btnActualizarIndices.onclick = handleActualizarIndices;
const btnDiagnosticarFuentes = document.getElementById("btn_diagnosticar_fuentes");
if (btnDiagnosticarFuentes) btnDiagnosticarFuentes.onclick = handleDiagnosticarFuentes;

document.getElementById("btn_reload").onclick = async () => {
  const btn = document.getElementById("btn_reload");
  btn.disabled    = true;
  btn.textContent = "Actualizando datos...";
  try {
    await api("/api/reload");
    await init();
    btn.textContent = "¡Actualizado!";
    setTimeout(() => { btn.textContent = "Recargar vista desde Drive"; }, 2000);
  } catch {
    btn.textContent = "Error al actualizar";
  } finally {
    btn.disabled = false;
  }
};

document.getElementById("btn_copiar").onclick = async () => {
  const analisisVisible =
    document.getElementById("view_analisis").style.display !== "none";
  const text = analisisVisible ? __TSV_VARS__ : __TSV__;

  if (!text) return alert("Primero elegí índices y armá la tabla/variaciones.");

  await navigator.clipboard.writeText(text);

  const hint = document.getElementById("hint");
  hint.style.display = "flex";
  setTimeout(() => { hint.style.display = "none"; }, 2200);
};
document.getElementById("btn_theme").onclick = toggleTheme;
document.getElementById("btn_theme_menu").onclick = toggleTheme;
document.getElementById("sel_col").addEventListener("change", () => {
  const select = document.getElementById("sel_col");

  _SELECTED_INDICES.clear();
  for (const opt of select.selectedOptions) {
    if (opt.value && opt.value !== "undefined" && opt.value !== "null") {
      _SELECTED_INDICES.add(opt.value);
    }
  }

  actualizarPanelIndicesElegidos();
});
document.getElementById("btn_pick_desde").onclick = () => openMonthPicker("desde");
document.getElementById("btn_pick_hasta").onclick = () => openMonthPicker("hasta");


document.querySelectorAll(".date-step").forEach(button => {
  button.addEventListener("click", () => {
    shiftPickValue(button.dataset.target, Number(button.dataset.step));
  });
});


document.getElementById("monthBackdrop").onclick = closeMonthPicker;
document.getElementById("monthClose").onclick = closeMonthPicker;

function shiftPickerYear(delta) {
  const minY = _YEARS.length ? _YEARS[0] : _PICK_YEAR;
  const maxY = _YEARS.length ? _YEARS[_YEARS.length - 1] : _PICK_YEAR;
  _PICK_YEAR = Math.max(minY, Math.min(maxY, _PICK_YEAR + delta));
  renderMonthPicker();
}
document.getElementById("yearPrev5").onclick = () => shiftPickerYear(-5);
document.getElementById("yearPrev").onclick = () => shiftPickerYear(-1);
document.getElementById("yearNext").onclick = () => shiftPickerYear(1);
document.getElementById("yearNext5").onclick = () => shiftPickerYear(5);

document.getElementById("monthOk").onclick = () => {
  if (!_PICK_SELECTED_YM) return;

  const iso = _DATES_BY_YM.get(_PICK_SELECTED_YM);
  if (!iso) return;

  setPickValue(_PICK_TARGET, iso);
  normalizeDateRange(_PICK_TARGET);
  closeMonthPicker();
};
const tgl = document.getElementById("btn_toggle_panel");
if (tgl) tgl.onclick = () => {
  setPanelCollapsed(!isPanelCollapsed());
  actualizarPanelIndicesElegidos();
};
// ════════════════════════════════
// ARRANQUE
// ════════════════════════════════
initTheme();
document.getElementById("btn-login").addEventListener("click", handleLogin);
document.getElementById("login-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") handleLogin();
});
document.getElementById("btn_logout").addEventListener("click", () => handleLogout());
document.getElementById("btn_logout_menu").addEventListener("click", () => handleLogout());

if (isLoggedIn()) { showMenu(); } else { showLogin(); }
