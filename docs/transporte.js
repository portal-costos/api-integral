const TOKEN_KEY = "cyt-token";
const THEME_KEY = "cyt-theme";
const API_BASE = "/api/transporte";
const TERMINAL_STATES = new Set(["COMPLETED", "STOPPED", "ERROR", "INTERRUPTED"]);

let currentRunId = null;
let pollingTimer = null;
let monitorItems = [];
let historyPage = 1;
let historyPages = 1;
let selectedPublication = null;
let lastResultSignature = "";

function getToken(){ return localStorage.getItem(TOKEN_KEY) || ""; }
function clearToken(){ localStorage.removeItem(TOKEN_KEY); }
function tokenValid(){
  try {
    const body = JSON.parse(atob(getToken().split(".")[1]));
    return Number(body.exp || 0) * 1000 > Date.now();
  } catch { return false; }
}
function goLogin(){ clearToken(); location.href = "./index.html"; }
function applyTheme(theme){
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  document.getElementById("btn_theme").textContent = theme === "dark" ? "☀️" : "🌙";
}
function initTheme(){
  const saved = localStorage.getItem(THEME_KEY);
  applyTheme(saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
}
function escapeHtml(value){
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}
function formatDate(value){
  if (!value) return "—";
  const text = String(value);
  if (/^\d{2}\/\d{2}\/\d{4}$/.test(text)) return text;
  const date = new Date(text.replace(" ", "T"));
  return Number.isNaN(date.getTime()) ? text : date.toLocaleString("es-AR");
}
function showAlert(message, type=""){
  const element = document.getElementById("global_alert");
  element.className = `tool-alert ${type}`;
  element.textContent = message;
  element.style.display = "block";
  if (type === "success") setTimeout(() => { element.style.display = "none"; }, 4500);
}
function hideAlert(){ document.getElementById("global_alert").style.display = "none"; }

async function api(path, options={}){
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      "Content-Type":"application/json",
      Authorization:`Bearer ${getToken()}`,
      ...(options.headers || {}),
    },
  });
  if (response.status === 401){ goLogin(); throw new Error("Sesión expirada."); }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Error HTTP ${response.status}`);
  return payload;
}

async function fetchDownload(path, fallbackName){
  const response = await fetch(apiUrl(path), {headers:{Authorization:`Bearer ${getToken()}`}});
  if (response.status === 401){ goLogin(); throw new Error("Sesión expirada."); }
  if (!response.ok){
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Error HTTP ${response.status}`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function setTab(name){
  document.querySelectorAll(".boletin-tab").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
  document.querySelectorAll(".boletin-view").forEach(view => view.classList.remove("active"));
  document.getElementById(`view_${name}`).classList.add("active");
  if (name === "history") loadHistory().catch(error => showAlert(error.message, "error"));
}

function initializeYears(){
  const select = document.getElementById("monitor_year");
  const current = new Date().getFullYear();
  const options = [];
  for (let year = current; year >= 2010; year--) options.push(`<option value="${year}">${year}</option>`);
  select.innerHTML = options.join("");
  select.value = String(current);
}

async function loadHealth(){
  const health = await api(`${API_BASE}/health`);
  const status = document.getElementById("status");
  if (!health.pymupdf_available){
    status.textContent = "PyMuPDF no disponible";
    showAlert("Falta PyMuPDF. Instalá la dependencia pymupdf para analizar los boletines.", "error");
  } else {
    status.textContent = `${health.publicaciones} resoluciones guardadas · ${health.ejecuciones} búsquedas`;
  }
}

function monitorPayload(){
  return {
    anio: Number(document.getElementById("monitor_year").value),
    revalidar_pdfs: document.getElementById("monitor_revalidate").checked,
    mostrar_sin_cambios: document.getElementById("monitor_unchanged").checked,
  };
}

async function startMonitoring(){
  hideAlert();
  const button = document.getElementById("btn_start_monitor");
  button.disabled = true;
  button.textContent = "Iniciando...";
  try {
    const response = await api(`${API_BASE}/monitorear`, {
      method:"POST",
      body:JSON.stringify(monitorPayload()),
    });
    currentRunId = response.run_id;
    monitorItems = [];
    lastResultSignature = "";
    renderMonitorResults();
    setRunControls(true);
    await pollRun();
  } catch(error){
    showAlert(error.message, "error");
    setRunControls(false);
  } finally {
    button.textContent = "▶ Buscar resoluciones de Transporte";
    if (!currentRunId) button.disabled = false;
  }
}

function setRunControls(running){
  document.getElementById("btn_start_monitor").disabled = running;
  document.getElementById("btn_stop_monitor").disabled = !running;
  const exportEnabled = Boolean(currentRunId);
  document.getElementById("btn_save_txt").disabled = !exportEnabled;
  document.getElementById("btn_copy_txt").disabled = !exportEnabled;
}

async function stopMonitoring(){
  if (!currentRunId) return;
  const button = document.getElementById("btn_stop_monitor");
  button.disabled = true;
  try {
    await api(`${API_BASE}/monitoreo/${currentRunId}/detener`, {method:"POST", body:"{}"});
    document.getElementById("progress_message").textContent = "Solicitando detención segura...";
  } catch(error){ showAlert(error.message, "error"); }
}

async function pollRun(){
  if (!currentRunId) return;
  if (pollingTimer) clearTimeout(pollingTimer);
  try {
    const run = await api(`${API_BASE}/monitoreo/${currentRunId}`);
    renderProgress(run);
    const signature = `${run.relevant_count || 0}|${run.new_count || 0}|${run.changed_count || 0}|${run.unchanged_count || 0}`;
    if (signature !== lastResultSignature){
      lastResultSignature = signature;
      await loadRunResults();
    }
    if (TERMINAL_STATES.has(run.status)){
      setRunControls(false);
      document.getElementById("btn_save_txt").disabled = false;
      document.getElementById("btn_copy_txt").disabled = false;
      await loadRunResults();
      await loadHealth();
      if (run.status === "COMPLETED") showAlert("Búsqueda anual finalizada correctamente.", "success");
      else if (run.status === "STOPPED") showAlert("La búsqueda fue detenida. Lo procesado quedó guardado.");
      else showAlert(run.mensaje || "La ejecución finalizó con errores.", "error");
      return;
    }
  } catch(error){
    showAlert(error.message, "error");
    setRunControls(false);
    return;
  }
  pollingTimer = setTimeout(pollRun, 1300);
}

function renderProgress(run){
  const percentage = Math.max(0, Math.min(100, Number(run.porcentaje || 0)));
  document.getElementById("progress_state").textContent = statusLabel(run.status);
  document.getElementById("progress_message").textContent = run.mensaje || "Procesando...";
  document.getElementById("progress_percent").textContent = `${Math.round(percentage)}%`;
  document.getElementById("progress_bar").style.width = `${percentage}%`;
  document.getElementById("kpi_months").textContent = `${Number(run.meses_procesados || 0)} / 12`;
  document.getElementById("kpi_pdfs").textContent = Number(run.pdfs_analizados || 0).toLocaleString("es-AR");
  document.getElementById("kpi_resolutions").textContent = Number(run.resoluciones_detectadas || 0).toLocaleString("es-AR");
  document.getElementById("kpi_news").textContent = Number(run.novedades || 0).toLocaleString("es-AR");
  document.getElementById("kpi_errors").textContent = Number(run.error_count || 0).toLocaleString("es-AR");
}
function statusLabel(status){
  return ({PENDING:"En cola",RUNNING:"Búsqueda en ejecución",STOPPING:"Deteniendo",COMPLETED:"Finalizada",STOPPED:"Detenida",ERROR:"Finalizada con error",INTERRUPTED:"Interrumpida"})[status] || status || "Sin ejecución";
}

async function loadRunResults(){
  if (!currentRunId) return;
  const payload = await api(`${API_BASE}/monitoreo/${currentRunId}/resultados`);
  monitorItems = payload.items || [];
  renderMonitorResults();
}

function changeClass(value){
  if (value === "NUEVO") return "new";
  if (value === "MODIFICADO") return "changed";
  if (value === "SIN CAMBIOS") return "same";
  return "error";
}

function renderMonitorResults(){
  const container = document.getElementById("monitor_results");
  document.getElementById("result_counter").textContent = `${monitorItems.length} ${monitorItems.length === 1 ? "publicación" : "publicaciones"}`;
  document.getElementById("btn_clear_findings").disabled = monitorItems.length === 0;
  if (!monitorItems.length){
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">⌕</div><strong>Todavía no hay hallazgos</strong><p>Las resoluciones nuevas o modificadas aparecerán aquí durante la búsqueda.</p></div>`;
    return;
  }
  container.innerHTML = monitorItems.map(item => {
    const terms = (item.terminos_encontrados || []).join(", ");
    return `<article class="result-item" data-change="${escapeHtml(item.novedad)}">
      <div class="result-top">
        <span class="result-date">${escapeHtml(item.fecha || "Fecha no detectada")}</span>
        <div class="result-badges">
          <span class="badge ${changeClass(item.novedad)}">${escapeHtml(item.novedad)}</span>
          <span class="badge state">${escapeHtml(item.estado_detectado)}</span>
        </div>
      </div>
      <div>
        <h4>${escapeHtml(item.numero)}</h4>
        <div class="result-provider">${escapeHtml(item.prestadora || "Destinatario o asunto no identificado")}</div>
      </div>
      <p class="result-excerpt">${escapeHtml(item.extracto || "Sin extracto disponible")}</p>
      ${terms ? `<div class="result-alerts">Temas: ${escapeHtml(terms)}</div>` : ""}
      <div class="result-footer">
        <span class="result-file">${escapeHtml(item.archivo)}</span>
        <button class="mini-button" data-detail-id="${Number(item.publication_id)}" type="button">Ver detalle →</button>
      </div>
    </article>`;
  }).join("");
}

function clearMonitorFindings(){
  if (!monitorItems.length) return;
  if (!confirm("¿Limpiar los hallazgos visibles? El historial guardado no se borrará.")) return;
  monitorItems = [];
  renderMonitorResults();
  showAlert("Hallazgos visibles limpiados. El historial quedó intacto.", "success");
}

async function saveRunTxt(){
  if (!currentRunId) return;
  try {
    await fetchDownload(`${API_BASE}/exportar?scope=run&run_id=${currentRunId}&formato=txt`, `transporte_run_${currentRunId}.txt`);
  } catch(error){ showAlert(error.message, "error"); }
}
async function copyRunTxt(){
  if (!currentRunId) return;
  try {
    const response = await fetch(apiUrl(`${API_BASE}/exportar?scope=run&run_id=${currentRunId}&formato=txt`), {headers:{Authorization:`Bearer ${getToken()}`}});
    if (response.status === 401){ goLogin(); return; }
    if (!response.ok){
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Error HTTP ${response.status}`);
    }
    await navigator.clipboard.writeText(await response.text());
    showAlert("TXT completo copiado al portapapeles.", "success");
  } catch(error){ showAlert(error.message, "error"); }
}

async function openDetail(publicationId){
  try {
    selectedPublication = await api(`${API_BASE}/publicaciones/${publicationId}`);
    document.getElementById("detail_title").textContent = selectedPublication.resolution_number || "Detalle de resolución";
    document.getElementById("detail_badge").textContent = selectedPublication.last_change_type || "Resolución de Transporte";
    document.getElementById("detail_meta").innerHTML = [
      ["Publicación", selectedPublication.publication_date || "—"],
      ["Destinatario / asunto", selectedPublication.provider || "—"],
      ["Clasificación", selectedPublication.detected_state || "—"],
      ["Archivo", selectedPublication.source_pdf || "—"],
      ["Primera detección", formatDate(selectedPublication.first_seen_at)],
      ["Última verificación", formatDate(selectedPublication.last_seen_at)],
      ["Verificaciones", selectedPublication.verification_count || 1],
    ].map(([label,value]) => `<div class="detail-meta-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
    document.getElementById("detail_resuelve").textContent = selectedPublication.text_resuelve || "(bloque RESUELVE no detectado automáticamente)";
    document.getElementById("detail_full").textContent = selectedPublication.text_full || "(texto completo no disponible)";
    const warning = document.getElementById("detail_warning");
    warning.style.display = selectedPublication.warning ? "block" : "none";
    warning.textContent = selectedPublication.warning || "";
    openModal("detail_modal");
  } catch(error){ showAlert(error.message, "error"); }
}

async function downloadSelectedPdf(){
  if (!selectedPublication) return;
  try {
    await fetchDownload(`${API_BASE}/publicaciones/${selectedPublication.id}/pdf`, selectedPublication.source_pdf || "boletin.pdf");
  } catch(error){ showAlert(error.message, "error"); }
}
async function copySelected(field, label){
  if (!selectedPublication) return;
  const text = selectedPublication[field] || "";
  if (!text) return showAlert(`No hay contenido disponible para ${label}.`, "error");
  await navigator.clipboard.writeText(text);
  showAlert(`${label} copiado al portapapeles.`, "success");
}

function historyParams(page=historyPage){
  const params = new URLSearchParams({page:String(page), page_size:"25"});
  const mapping = {
    texto: document.getElementById("history_text").value.trim(),
    anio: document.getElementById("history_year").value,
    estado: document.getElementById("history_state").value,
    destinatario: document.getElementById("history_provider").value.trim(),
  };
  Object.entries(mapping).forEach(([key,value]) => { if (value) params.set(key,value); });
  if (document.getElementById("history_news_only").checked) params.set("solo_novedades","true");
  return params;
}

async function loadHistoryFilterOptions(){
  const payload = await api(`${API_BASE}/historial/filtros`);
  const yearSelect = document.getElementById("history_year");
  const stateSelect = document.getElementById("history_state");
  const currentYear = yearSelect.value;
  const currentState = stateSelect.value;
  yearSelect.innerHTML = `<option value="">Todos</option>` + (payload.years || []).map(year => `<option value="${Number(year)}">${Number(year)}</option>`).join("");
  stateSelect.innerHTML = `<option value="">Todas</option>` + (payload.states || []).map(state => `<option value="${escapeHtml(state)}">${escapeHtml(state)}</option>`).join("");
  yearSelect.value = currentYear;
  stateSelect.value = currentState;
}

async function loadHistory(page=historyPage){
  historyPage = page;
  const payload = await api(`${API_BASE}/historial?${historyParams(page)}`);
  historyPages = payload.pages || 1;
  renderHistory(payload.items || [], payload.total || 0);
}

function renderHistory(items, total){
  const body = document.getElementById("history_table");
  if (!items.length){
    body.innerHTML = `<tr><td colspan="9">No hay publicaciones que coincidan con los filtros.</td></tr>`;
  } else {
    body.innerHTML = items.map(item => `<tr>
      <td>${escapeHtml(item.publication_date || "—")}</td>
      <td><strong>${escapeHtml(item.resolution_number)}</strong></td>
      <td>${escapeHtml(item.provider || "—")}</td>
      <td><span class="badge state">${escapeHtml(item.detected_state || "—")}</span></td>
      <td>${escapeHtml(formatDate(item.first_seen_at))}</td>
      <td>${escapeHtml(formatDate(item.last_seen_at))}</td>
      <td class="num">${Number(item.verification_count || 1)}</td>
      <td><span class="badge ${changeClass(item.last_change_type)}">${escapeHtml(item.last_change_type)}</span><div class="hash-indicator" title="${escapeHtml(item.content_hash)}">${escapeHtml(item.content_hash || "")}</div></td>
      <td><button class="mini-button" data-detail-id="${item.id}" type="button">Abrir</button></td>
    </tr>`).join("");
  }
  document.getElementById("history_page_label").textContent = `Página ${historyPage} de ${historyPages} · ${total} registros`;
  document.getElementById("history_prev").disabled = historyPage <= 1;
  document.getElementById("history_next").disabled = historyPage >= historyPages;
}

function clearHistoryFilters(){
  ["history_text","history_provider"].forEach(id => document.getElementById(id).value = "");
  ["history_year","history_state"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("history_news_only").checked = false;
  loadHistory(1).catch(error => showAlert(error.message, "error"));
}

async function exportHistory(format){
  const params = historyParams(1);
  params.delete("page");
  params.delete("page_size");
  params.set("scope","historial");
  params.set("formato",format);
  const buttonId = format === "xlsx" ? "btn_export_excel" : "btn_export_json";
  const button = document.getElementById(buttonId);
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Preparando archivo...";
  try {
    await fetchDownload(`${API_BASE}/exportar?${params.toString()}`, `historial_transporte.${format === "xlsx" ? "xlsx" : "json"}`);
    showAlert(`Exportación ${format === "xlsx" ? "Excel" : "JSON"} generada correctamente.`, "success");
  } catch(error){
    showAlert(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function openModal(id){
  const modal = document.getElementById(id);
  modal.classList.add("open");
  modal.setAttribute("aria-hidden","false");
  document.body.style.overflow = "hidden";
}
function closeModal(id){
  const modal = document.getElementById(id);
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden","true");
  if (!document.querySelector(".modal-shell.open")) document.body.style.overflow = "";
}

function bindEvents(){
  document.querySelectorAll(".boletin-tab").forEach(button => button.addEventListener("click", () => setTab(button.dataset.tab)));
  document.getElementById("btn_start_monitor").onclick = startMonitoring;
  document.getElementById("btn_stop_monitor").onclick = stopMonitoring;
  document.getElementById("btn_save_txt").onclick = saveRunTxt;
  document.getElementById("btn_copy_txt").onclick = copyRunTxt;
  document.getElementById("btn_clear_findings").onclick = clearMonitorFindings;
  document.getElementById("btn_tutorial").onclick = () => openModal("tutorial_modal");
  document.getElementById("btn_history_filter").onclick = () => loadHistory(1).catch(error => showAlert(error.message, "error"));
  document.getElementById("btn_history_clear").onclick = clearHistoryFilters;
  document.getElementById("history_prev").onclick = () => loadHistory(Math.max(1, historyPage - 1)).catch(error => showAlert(error.message, "error"));
  document.getElementById("history_next").onclick = () => loadHistory(Math.min(historyPages, historyPage + 1)).catch(error => showAlert(error.message, "error"));
  document.getElementById("btn_export_json").onclick = () => exportHistory("json");
  document.getElementById("btn_export_excel").onclick = () => exportHistory("xlsx");
  document.getElementById("history_text").addEventListener("keydown", event => { if (event.key === "Enter") loadHistory(1).catch(error => showAlert(error.message, "error")); });

  document.body.addEventListener("click", event => {
    const detailButton = event.target.closest("[data-detail-id]");
    if (detailButton) return openDetail(Number(detailButton.dataset.detailId));
    const closeButton = event.target.closest("[data-close]");
    if (closeButton){
      const modalByName = {detail:"detail_modal", tutorial:"tutorial_modal"};
      closeModal(modalByName[closeButton.dataset.close] || "tutorial_modal");
    }
  });

  document.getElementById("detail_open_pdf").onclick = () => {
    if (selectedPublication?.source_url) window.open(selectedPublication.source_url, "_blank", "noopener");
  };
  document.getElementById("detail_download_pdf").onclick = downloadSelectedPdf;
  document.getElementById("detail_copy_full").onclick = () => copySelected("text_full", "Resolución completa");
  document.getElementById("detail_copy_resuelve").onclick = () => copySelected("text_resuelve", "Bloque RESUELVE");
  document.getElementById("btn_theme").onclick = () => applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  document.getElementById("btn_home").onclick = () => location.href = "./index.html";
  document.getElementById("btn_logout").onclick = goLogin;
  document.addEventListener("keydown", event => {
    if (event.key === "Escape"){
      closeModal("detail_modal");
      closeModal("tutorial_modal");
    }
  });
}

async function initialize(){
  if (!tokenValid()) return goLogin();
  initTheme();
  initializeYears();
  bindEvents();
  try {
    await Promise.all([loadHealth(), loadHistoryFilterOptions(), loadHistory(1)]);
  } catch(error){
    document.getElementById("status").textContent = "Error de conexión";
    showAlert(error.message, "error");
  }
}

initialize();
