const TOKEN_KEY = "cyt-token";
const THEME_KEY = "cyt-theme";
const TERMINAL_STATES = new Set(["COMPLETED", "STOPPED", "ERROR", "INTERRUPTED"]);

let currentRunId = null;
let pollingTimer = null;
let monitorItems = [];
let alerts = [];
let historyPage = 1;
let historyPages = 1;
let selectedPublication = null;
let lastResultSignature = "";
let importPreviewRows = [];
let extractionProgressTimer = null;

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

function expedienteLabel(value){ return String(value || "").trim() || "Expediente no identificado"; }
function identifiedLabel(value){ return String(value || "").trim() || "No identificado"; }
function splitSearchTerms(value){
  return String(value || "").split(/\s*(?:\||;|\n)\s*/).map(item => item.trim()).filter(Boolean);
}
function orTermsHtml(value){
  const terms = Array.isArray(value) ? value : splitSearchTerms(value);
  if (!terms.length) return `<span class="or-term-chip">Sin términos</span>`;
  return terms.map((term, index) => `${index ? '<span class="or-word">O</span>' : ''}<span class="or-term-chip">${escapeHtml(term)}</span>`).join("");
}

async function copyToClipboard(text){
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

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

async function apiForm(path, formData){
  const response = await fetch(apiUrl(path), {
    method:"POST",
    headers:{Authorization:`Bearer ${getToken()}`},
    body:formData,
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
  return blob;
}

function setTab(name){
  document.querySelectorAll(".boletin-tab").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
  document.querySelectorAll(".boletin-view").forEach(view => view.classList.remove("active"));
  document.getElementById(`view_${name}`).classList.add("active");
  if (name === "alerts") loadAlerts().catch(error => showAlert(error.message, "error"));
  if (name === "history") loadHistory().catch(error => showAlert(error.message, "error"));
}

function initializeYears(){
  const select = document.getElementById("monitor_year");
  const current = new Date().getFullYear();
  const options = [];
  for (let year = current; year >= 2018; year--) options.push(`<option value="${year}">${year}</option>`);
  select.innerHTML = options.join("");
  select.value = String(current);
}

async function loadHealth(){
  const health = await api("/api/boletin/health");
  const status = document.getElementById("status");
  if (!health.pymupdf_available){
    status.textContent = "PyMuPDF no disponible";
    showAlert("El módulo está instalado, pero falta PyMuPDF. Ejecutá PROBAR_AQUI.bat para instalar pymupdf.", "error");
  } else {
    status.textContent = `${health.publicaciones} publicaciones · ${health.alertas_activas} alertas activas`;
  }
}

function monitorPayload(){
  const terms = document.getElementById("monitor_terms").value
    .split(/\s+(?:O|OR)\s+|[,;|\n]+/i)
    .map(value => value.trim())
    .filter(Boolean);
  const processAll = document.getElementById("monitor_process_all").checked;
  return {
    anio: Number(document.getElementById("monitor_year").value),
    terminos: terms,
    revalidar_pdfs: processAll,
    incluir_todas_ersep: document.getElementById("monitor_all").checked,
    mostrar_sin_cambios: processAll || document.getElementById("monitor_unchanged").checked,
    procesar_todos: processAll,
  };
}

async function startMonitoring(){
  hideAlert();
  const button = document.getElementById("btn_start_monitor");
  button.disabled = true;
  button.textContent = "Iniciando...";
  try {
    const response = await api("/api/boletin/monitorear", {
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
    button.textContent = "▶ Iniciar monitoreo de alertas";
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
    await api(`/api/boletin/monitoreo/${currentRunId}/detener`, {method:"POST", body:"{}"});
    document.getElementById("progress_message").textContent = "Solicitando detención segura...";
  } catch(error){ showAlert(error.message, "error"); }
}

async function pollRun(){
  if (!currentRunId) return;
  if (pollingTimer) clearTimeout(pollingTimer);
  try {
    const run = await api(`/api/boletin/monitoreo/${currentRunId}`);
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
      if (run.status === "COMPLETED") showAlert("Monitoreo anual finalizado correctamente.", "success");
      else if (run.status === "STOPPED") showAlert("El monitoreo fue detenido. Los resultados ya procesados quedaron guardados.");
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
  return ({PENDING:"En cola",RUNNING:"Monitoreo en ejecución",STOPPING:"Deteniendo",COMPLETED:"Finalizado",STOPPED:"Detenido",ERROR:"Finalizado con error",INTERRUPTED:"Interrumpido"})[status] || status || "Sin ejecución";
}

async function loadRunResults(){
  if (!currentRunId) return;
  const payload = await api(`/api/boletin/monitoreo/${currentRunId}/resultados`);
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
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">⌕</div><strong>Todavía no hay hallazgos</strong><p>Las resoluciones que coincidan con la configuración aparecerán aquí durante el monitoreo.</p></div>`;
    return;
  }
  container.innerHTML = monitorItems.map(item => {
    const alertsText = (item.alertas || []).join(", ");
    const terms = (item.terminos_encontrados || []).join(", ");
    return `<article class="result-item" data-change="${escapeHtml(item.novedad)}">
      <div class="result-top">
        <span class="result-date">Fecha del Boletín: ${escapeHtml(item.fecha || "No identificada")}</span>
        <div class="result-badges">
          <span class="badge ${changeClass(item.novedad)}">${escapeHtml(item.novedad)}</span>
          <span class="badge state">${escapeHtml(item.estado_detectado)}</span>
        </div>
      </div>
      <div>
        <h4>${escapeHtml(item.numero)}</h4>
        <div class="result-expediente">${escapeHtml(expedienteLabel(item.expediente))}</div>
        <div class="result-provider">${escapeHtml(item.prestadora || "Prestadora no identificada")}</div>
        ${alertsText ? `<div class="result-alerts">Alerta: ${escapeHtml(alertsText)}</div>` : ""}
      </div>
      <p class="result-excerpt" title="Vista previa del párrafo inicial">${escapeHtml(item.extracto || "Vista previa no disponible")}</p>
      ${terms ? `<div class="result-alerts">Términos: ${escapeHtml(terms)}</div>` : ""}
      <div class="result-footer">
        <span class="result-file">${escapeHtml(item.archivo)}</span>
        <div class="result-card-actions">
          <button class="mini-button" data-copy-id="${Number(item.publication_id)}" type="button">Copiar datos</button>
          <button class="mini-button" data-detail-id="${Number(item.publication_id)}" type="button">Ver detalle →</button>
        </div>
      </div>
    </article>`;
  }).join("");
}

function clearMonitorFindings(){
  if (!monitorItems.length) return;
  const message = currentRunId
    ? "¿Limpiar los hallazgos visibles? El historial guardado y la ejecución no se borrarán."
    : "¿Limpiar los hallazgos visibles?";
  if (!confirm(message)) return;
  monitorItems = [];
  renderMonitorResults();
  showAlert("Hallazgos visibles limpiados. El historial quedó intacto.", "success");
}

async function saveRunTxt(){
  if (!currentRunId) return;
  try {
    await fetchDownload(`/api/boletin/exportar?scope=run&run_id=${currentRunId}&formato=txt`, `boletin_run_${currentRunId}.txt`);
  } catch(error){ showAlert(error.message, "error"); }
}
async function copyRunTxt(){
  if (!currentRunId) return;
  try {
    const response = await fetch(apiUrl(`/api/boletin/exportar?scope=run&run_id=${currentRunId}&formato=txt`), {headers:{Authorization:`Bearer ${getToken()}`}});
    if (response.status === 401){ goLogin(); return; }
    if (!response.ok){ const payload = await response.json().catch(() => ({})); throw new Error(payload.detail || `Error HTTP ${response.status}`); }
    await copyToClipboard(await response.text());
    showAlert("TXT completo copiado al portapapeles.", "success");
  } catch(error){ showAlert(error.message, "error"); }
}

async function openDetail(publicationId){
  try {
    selectedPublication = await api(`/api/boletin/publicaciones/${publicationId}`);
    renderSelectedPublication();
    openModal("detail_modal");
  } catch(error){ showAlert(error.message, "error"); }
}

function renderSelectedPublication(){
  if (!selectedPublication) return;
  document.getElementById("detail_title").textContent = selectedPublication.resolution_number || "Resolución no identificada";
  document.getElementById("detail_badge").textContent = selectedPublication.last_change_type || "Publicación ERSeP";
  const alertNames = (selectedPublication.matched_alerts || []).map(item => typeof item === "string" ? item : item.nombre).filter(Boolean);
  document.getElementById("detail_meta").innerHTML = [
    ["Resolución", identifiedLabel(selectedPublication.resolution_number)],
    ["Expediente", expedienteLabel(selectedPublication.expediente_number)],
    ["Fecha del Boletín", identifiedLabel(selectedPublication.publication_date)],
    ["Fecha de emisión", identifiedLabel(selectedPublication.emission_date)],
    ["Prestadora", identifiedLabel(selectedPublication.provider)],
    ["Organismo emisor", identifiedLabel(selectedPublication.issuing_body)],
    ["Estado detectado", identifiedLabel(selectedPublication.detected_state)],
    ["Alertas", alertNames.join(" O ") || "Sin coincidencias"],
    ["Términos tarifarios", (selectedPublication.regulatory_terms || []).join(" O ") || "No identificado"],
    ["Archivo", identifiedLabel(selectedPublication.source_pdf)],
    ["Última verificación", formatDate(selectedPublication.last_seen_at)],
    ["Verificaciones", selectedPublication.verification_count || 1],
  ].map(([label,value]) => `<div class="detail-meta-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  document.getElementById("detail_resuelve").textContent = selectedPublication.text_resuelve || "(bloque RESUELVE no identificado)";
  document.getElementById("detail_full").textContent = selectedPublication.text_full || "(texto completo no identificado)";
  const warning = document.getElementById("detail_warning");
  warning.style.display = selectedPublication.warning ? "block" : "none";
  warning.textContent = selectedPublication.warning || "";
  renderAnnexes(selectedPublication.annexes || [], Boolean(selectedPublication.complete_extracted_at));
}

function renderAnnexes(annexes, extractionDone=false){
  const container = document.getElementById("detail_annexes");
  const count = document.getElementById("detail_annex_count");
  if (!extractionDone && !annexes.length){
    count.textContent = "Sin extracción";
    container.innerHTML = `<p class="annex-empty">Usá “Extraer documento completo” para buscar anexos integrados y PDF vinculados.</p>`;
    return;
  }
  if (!annexes.length){
    count.textContent = "0 detectados";
    container.innerHTML = `<p class="annex-empty">No se detectaron anexos</p>`;
    return;
  }
  count.textContent = `${annexes.length} ${annexes.length === 1 ? "detectado" : "detectados"}`;
  container.innerHTML = annexes.map((annex, index) => `<article class="annex-item">
    <div><strong>${escapeHtml(annex.nombre || `Anexo ${index + 1}`)}</strong><span>${escapeHtml(annex.tipo === "vinculado" ? "PDF vinculado" : "Integrado en la resolución")}${annex.advertencia ? ` · ${escapeHtml(annex.advertencia)}` : ""}</span></div>
    <div class="annex-item-actions">
      <button class="mini-button" data-annex-open="${index}" type="button">Abrir</button>
      <button class="mini-button" data-annex-download="${index}" type="button">Descargar</button>
      <button class="mini-button" data-annex-copy="${index}" type="button" ${annex.texto ? "" : "disabled"}>Copiar texto</button>
    </div>
  </article>`).join("");
}

async function downloadSelectedPdf(){
  if (!selectedPublication) return;
  try {
    await fetchDownload(`/api/boletin/publicaciones/${selectedPublication.id}/pdf`, selectedPublication.source_pdf || "boletin.pdf");
  } catch(error){ showAlert(error.message, "error"); }
}
async function copySelected(field, label){
  if (!selectedPublication) return;
  const text = selectedPublication[field] || "";
  if (!text) return showAlert(`No hay contenido disponible para ${label}.`, "error");
  await copyToClipboard(text);
  showAlert(`${label} copiado al portapapeles.`, "success");
}

function publicationCopyText(publication){
  return [
    `Expediente: ${expedienteLabel(publication.expediente_number || publication.expediente)}`,
    `Resolución: ${identifiedLabel(publication.resolution_number || publication.numero)}`,
    `Fecha del Boletín: ${identifiedLabel(publication.publication_date || publication.fecha)}`,
    `Enlace: ${identifiedLabel(publication.source_url || publication.url)}`,
    `Prestadora: ${identifiedLabel(publication.provider || publication.prestadora)}`,
  ].join("\n");
}

async function copyPublicationData(publicationId=null){
  try {
    let publication = selectedPublication;
    if (publicationId && Number(publication?.id) !== Number(publicationId)){
      publication = await api(`/api/boletin/publicaciones/${publicationId}`);
    }
    if (!publication) return;
    await copyToClipboard(publicationCopyText(publication));
    showAlert("Datos copiados al portapapeles", "success");
  } catch(error){ showAlert(error.message, "error"); }
}

function setExtractionProgress(active, percent=0, label="Extrayendo información…"){
  const panel = document.getElementById("detail_extraction_progress");
  panel.hidden = !active;
  document.getElementById("detail_extraction_label").textContent = label;
  document.getElementById("detail_extraction_percent").textContent = `${percent}%`;
  document.getElementById("detail_extraction_bar").style.width = `${percent}%`;
  ["detail_extract_full","detail_get_all"].forEach(id => { document.getElementById(id).disabled = active; });
}

async function extractSelectedInformation(mode="complete"){
  if (!selectedPublication) return;
  const path = mode === "all" ? "obtener-informacion-completa" : "extraer-completo";
  const label = mode === "all" ? "Obteniendo resolución, metadatos y anexos…" : "Extrayendo todas las páginas y buscando anexos…";
  let progress = 8;
  setExtractionProgress(true, progress, label);
  if (extractionProgressTimer) clearInterval(extractionProgressTimer);
  extractionProgressTimer = setInterval(() => {
    progress = Math.min(88, progress + Math.max(2, Math.round((90 - progress) / 7)));
    setExtractionProgress(true, progress, label);
  }, 550);
  try {
    selectedPublication = await api(`/api/boletin/publicaciones/${selectedPublication.id}/${path}`, {method:"POST", body:"{}"});
    clearInterval(extractionProgressTimer);
    extractionProgressTimer = null;
    setExtractionProgress(true, 100, "Extracción finalizada");
    renderSelectedPublication();
    loadHistory(historyPage).catch(error => showAlert(error.message, "error"));
    setTimeout(() => setExtractionProgress(false), 900);
    const annexCount = (selectedPublication.annexes || []).length;
    showAlert(annexCount ? `Extracción completa: ${annexCount} anexo${annexCount === 1 ? "" : "s"} detectado${annexCount === 1 ? "" : "s"}.` : "Extracción completa. No se detectaron anexos.", "success");
  } catch(error){
    if (extractionProgressTimer) clearInterval(extractionProgressTimer);
    extractionProgressTimer = null;
    setExtractionProgress(false);
    showAlert(error.message, "error");
  }
}

async function downloadAnnex(index){
  if (!selectedPublication) return;
  try {
    await fetchDownload(`/api/boletin/publicaciones/${selectedPublication.id}/anexos/${index}/pdf`, `anexo_${index + 1}.pdf`);
  } catch(error){ showAlert(error.message, "error"); }
}

async function loadAlerts(){
  const payload = await api("/api/boletin/alertas");
  alerts = payload.items || [];
  renderAlerts();
  renderAlertFilter();
}
function renderAlerts(){
  const body = document.getElementById("alerts_table");
  if (!alerts.length){
    body.innerHTML = `<tr><td colspan="6">No hay alertas configuradas.</td></tr>`;
    return;
  }
  body.innerHTML = alerts.map(item => `<tr>
    <td><strong>${escapeHtml(item.nombre)}</strong></td>
    <td class="alias-cell"><div class="or-terms-display">${orTermsHtml(item.aliases)}</div></td>
    <td><span class="status-dot ${item.active ? "active" : "paused"}">${item.active ? "Activa" : "Pausada"}</span></td>
    <td>v${Number(item.current_version || 1)}</td>
    <td>${escapeHtml(formatDate(item.updated_at))}</td>
    <td><div class="table-actions">
      <button class="mini-button" data-alert-edit="${item.id}" type="button">Editar</button>
      <button class="mini-button" data-alert-state="${item.id}" data-active="${item.active ? "1" : "0"}" type="button">${item.active ? "Pausar" : "Reactivar"}</button>
      <button class="mini-button" data-alert-delete="${item.id}" type="button">Eliminar</button>
    </div></td>
  </tr>`).join("");
}
function renderAlertFilter(){
  const select = document.getElementById("history_alert");
  const current = select.value;
  select.innerHTML = `<option value="">Todas</option>` + alerts.map(item => `<option value="${escapeHtml(item.nombre)}">${escapeHtml(item.nombre)}</option>`).join("");
  if ([...select.options].some(option => option.value === current)) select.value = current;
}

function addAlertTerm(value=""){
  const builder = document.getElementById("alert_terms_builder");
  const row = document.createElement("div");
  row.className = "or-term-row";
  row.innerHTML = `<input class="alert-term-input" type="text" maxlength="300" placeholder="Ej.: Cooperativa Aguas de Capilla" value="${escapeHtml(value)}"><button class="or-term-remove" type="button" aria-label="Quitar término">×</button>`;
  builder.appendChild(row);
}

function alertTerms(){
  return [...document.querySelectorAll(".alert-term-input")].map(input => input.value.trim()).filter(Boolean);
}

function openAlertModal(item=null){
  document.getElementById("alert_modal_title").textContent = item ? "Editar alerta" : "Nueva alerta";
  document.getElementById("alert_id").value = item?.id || "";
  document.getElementById("alert_name").value = item?.nombre || "";
  document.getElementById("alert_active").checked = item ? Boolean(item.active) : true;
  document.getElementById("alert_terms_builder").innerHTML = "";
  const terms = splitSearchTerms(item?.aliases || "");
  (terms.length ? terms : [""]).forEach(addAlertTerm);
  openModal("alert_modal");
  setTimeout(() => document.getElementById("alert_name").focus(), 80);
}
async function saveAlert(event){
  event.preventDefault();
  const id = document.getElementById("alert_id").value;
  const terms = alertTerms();
  if (!terms.length){
    showAlert("Agregá al menos un término de búsqueda.", "error");
    return;
  }
  const body = {
    nombre: document.getElementById("alert_name").value.trim(),
    aliases: terms.join(" | "),
    active: document.getElementById("alert_active").checked,
  };
  try {
    await api(id ? `/api/boletin/alertas/${id}` : "/api/boletin/alertas", {method:id ? "PUT" : "POST", body:JSON.stringify(body)});
    closeModal("alert_modal");
    await loadAlerts();
    await loadHealth();
    showAlert("Alerta guardada correctamente.", "success");
  } catch(error){ showAlert(error.message, "error"); }
}
async function toggleAlert(id, active){
  await api(`/api/boletin/alertas/${id}/estado`, {method:"PATCH", body:JSON.stringify({active:!active})});
  await loadAlerts();
  await loadHealth();
}
async function deleteAlert(id){
  const item = alerts.find(entry => Number(entry.id) === Number(id));
  if (!confirm(`¿Eliminar la alerta “${item?.nombre || id}”?`)) return;
  await api(`/api/boletin/alertas/${id}`, {method:"DELETE"});
  await loadAlerts();
  await loadHealth();
}

function resetAlertImport(){
  importPreviewRows = [];
  document.getElementById("alert_import_file").value = "";
  document.getElementById("alert_import_filename").textContent = "Ningún archivo seleccionado";
  document.getElementById("import_preview").hidden = true;
  document.getElementById("import_summary").innerHTML = "";
  document.getElementById("import_preview_table").innerHTML = "";
  document.getElementById("btn_confirm_alert_import").disabled = true;
}

function openImportModal(){
  resetAlertImport();
  openModal("import_modal");
}

async function previewAlertImport(file){
  if (!file) return;
  document.getElementById("alert_import_filename").textContent = file.name;
  const form = new FormData();
  form.append("file", file);
  const button = document.getElementById("btn_choose_alert_file");
  button.disabled = true;
  button.textContent = "Analizando archivo…";
  try {
    const payload = await apiForm("/api/boletin/alertas/importacion/vista-previa", form);
    importPreviewRows = payload.filas || [];
    renderImportPreview(payload);
  } catch(error){
    resetAlertImport();
    showAlert(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Seleccionar .xlsx o .csv";
  }
}

function renderImportPreview(payload){
  const summary = payload.resumen || {};
  const values = [
    ["Filas totales", summary.total_filas || 0],
    ["Filas válidas", summary.filas_validas || 0],
    ["Incompletas", summary.filas_incompletas || 0],
    ["Posibles duplicadas", summary.posibles_duplicadas || 0],
    ["Se actualizarán", summary.se_actualizaran || 0],
    ["Se incorporarán", summary.total_incorporar || 0],
  ];
  document.getElementById("import_summary").innerHTML = values.map(([label,value]) => `<div class="import-summary-item"><span>${escapeHtml(label)}</span><strong>${Number(value)}</strong></div>`).join("");
  document.getElementById("import_preview_table").innerHTML = importPreviewRows.map(row => {
    const statusClass = row.accion === "crear" ? "create" : row.accion === "actualizar" ? "update" : "reject";
    const statusLabel = row.accion === "crear" ? "Se creará" : row.accion === "actualizar" ? "Se actualizará" : `Rechazada${row.errores?.length ? `: ${row.errores.join(" ")}` : ""}`;
    return `<tr><td>${Number(row.fila)}</td><td><strong>${escapeHtml(row.alias || "—")}</strong></td><td><div class="or-terms-display">${orTermsHtml(row.palabras_claves)}</div></td><td><span class="import-status ${statusClass}">${escapeHtml(statusLabel)}</span></td></tr>`;
  }).join("");
  document.getElementById("import_preview").hidden = false;
  document.getElementById("btn_confirm_alert_import").disabled = Number(summary.total_incorporar || 0) === 0;
}

async function confirmAlertImport(){
  if (!importPreviewRows.length) return;
  const button = document.getElementById("btn_confirm_alert_import");
  button.disabled = true;
  button.textContent = "Importando…";
  try {
    const payload = await api("/api/boletin/alertas/importacion/confirmar", {
      method:"POST",
      body:JSON.stringify({filas:importPreviewRows.map(row => ({
        fila:row.fila,
        alias:row.alias,
        palabras_claves:row.palabras_claves,
        accion:row.accion,
      }))}),
    });
    closeModal("import_modal");
    await loadAlerts();
    await loadHealth();
    showAlert(`Importación finalizada: ${payload.creadas} creadas, ${payload.actualizadas} actualizadas y ${payload.rechazadas} rechazadas.`, "success");
  } catch(error){
    showAlert(error.message, "error");
    button.disabled = false;
  } finally {
    button.textContent = "Confirmar importación";
  }
}

function historyParams(page=historyPage){
  const params = new URLSearchParams({page:String(page), page_size:"25"});
  const mapping = {
    texto: document.getElementById("history_text").value.trim(),
    anio: document.getElementById("history_year").value,
    estado: document.getElementById("history_state").value,
    prestadora: document.getElementById("history_provider").value.trim(),
    alerta: document.getElementById("history_alert").value,
  };
  Object.entries(mapping).forEach(([key,value]) => { if (value) params.set(key,value); });
  if (document.getElementById("history_news_only").checked) params.set("solo_novedades","true");
  return params;
}
async function loadHistoryFilterOptions(){
  const payload = await api("/api/boletin/historial/filtros");
  const yearSelect = document.getElementById("history_year");
  const stateSelect = document.getElementById("history_state");
  const currentYear = yearSelect.value;
  const currentState = stateSelect.value;
  yearSelect.innerHTML = `<option value="">Todos</option>` + (payload.years || []).map(year => `<option value="${Number(year)}">${Number(year)}</option>`).join("");
  stateSelect.innerHTML = `<option value="">Todos</option>` + (payload.states || []).map(state => `<option value="${escapeHtml(state)}">${escapeHtml(state)}</option>`).join("");
  yearSelect.value = currentYear;
  stateSelect.value = currentState;
}

async function loadHistory(page=historyPage){
  historyPage = page;
  const payload = await api(`/api/boletin/historial?${historyParams(page)}`);
  historyPages = payload.pages || 1;
  renderHistory(payload.items || [], payload.total || 0);
  populateHistoryOptions(payload.items || []);
}
function populateHistoryOptions(items){
  const yearSelect = document.getElementById("history_year");
  const stateSelect = document.getElementById("history_state");
  const currentYear = yearSelect.value;
  const currentState = stateSelect.value;
  const years = [...new Set(items.map(item => item.year).filter(Boolean))].sort((a,b) => b-a);
  const states = [...new Set(items.map(item => item.detected_state).filter(Boolean))].sort();
  for (const year of years){ if (![...yearSelect.options].some(option => option.value === String(year))) yearSelect.add(new Option(String(year), String(year))); }
  for (const state of states){ if (![...stateSelect.options].some(option => option.value === state)) stateSelect.add(new Option(state, state)); }
  yearSelect.value = currentYear;
  stateSelect.value = currentState;
}
function renderHistory(items, total){
  const body = document.getElementById("history_table");
  if (!items.length){
    body.innerHTML = `<tr><td colspan="11">No hay publicaciones que coincidan con los filtros.</td></tr>`;
  } else {
    body.innerHTML = items.map(item => {
      const alertNames = (item.matched_alerts || []).map(entry => typeof entry === "string" ? entry : entry.nombre).filter(Boolean);
      return `<tr>
        <td>${escapeHtml(item.publication_date || "—")}</td>
        <td><strong>${escapeHtml(item.resolution_number)}</strong></td>
        <td>${escapeHtml(expedienteLabel(item.expediente_number))}</td>
        <td>${escapeHtml(item.provider || "—")}</td>
        <td><span class="badge state">${escapeHtml(item.detected_state || "—")}</span></td>
        <td>${escapeHtml(alertNames.join(" O ") || "—")}</td>
        <td>${escapeHtml(formatDate(item.first_seen_at))}</td>
        <td>${escapeHtml(formatDate(item.last_seen_at))}</td>
        <td class="num">${Number(item.verification_count || 1)}</td>
        <td><span class="badge ${changeClass(item.last_change_type)}">${escapeHtml(item.last_change_type)}</span><div class="hash-indicator" title="${escapeHtml(item.content_hash)}">${escapeHtml(item.content_hash || "")}</div></td>
        <td><div class="table-actions"><button class="mini-button" data-copy-id="${item.id}" type="button">Copiar datos</button><button class="mini-button" data-detail-id="${item.id}" type="button">Abrir</button></div></td>
      </tr>`;
    }).join("");
  }
  document.getElementById("history_page_label").textContent = `Página ${historyPage} de ${historyPages} · ${total} registros`;
  document.getElementById("history_prev").disabled = historyPage <= 1;
  document.getElementById("history_next").disabled = historyPage >= historyPages;
}
function clearHistoryFilters(){
  ["history_text","history_provider"].forEach(id => document.getElementById(id).value = "");
  ["history_year","history_state","history_alert"].forEach(id => document.getElementById(id).value = "");
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
    await fetchDownload(
      `/api/boletin/exportar?${params.toString()}`,
      `historial_boletin.${format === "xlsx" ? "xlsx" : "json"}`
    );
    showAlert(`Exportación ${format === "xlsx" ? "Excel" : "JSON"} descargada correctamente.`, "success");
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
  document.getElementById("btn_new_alert").onclick = () => openAlertModal();
  document.getElementById("btn_import_alerts").onclick = openImportModal;
  document.getElementById("btn_add_alert_term").onclick = () => addAlertTerm();
  document.getElementById("btn_download_alert_template").onclick = () => fetchDownload("/api/boletin/alertas/importacion/plantilla", "plantilla_importacion_alertas.xlsx").catch(error => showAlert(error.message, "error"));
  document.getElementById("btn_choose_alert_file").onclick = () => document.getElementById("alert_import_file").click();
  document.getElementById("alert_import_file").onchange = event => previewAlertImport(event.target.files?.[0]);
  document.getElementById("btn_confirm_alert_import").onclick = confirmAlertImport;
  document.getElementById("alert_form").addEventListener("submit", saveAlert);
  document.getElementById("monitor_process_all").onchange = event => {
    const unchanged = document.getElementById("monitor_unchanged");
    if (event.target.checked) unchanged.checked = true;
    unchanged.disabled = event.target.checked;
  };
  document.getElementById("btn_history_filter").onclick = () => loadHistory(1).catch(error => showAlert(error.message, "error"));
  document.getElementById("btn_history_clear").onclick = clearHistoryFilters;
  document.getElementById("history_prev").onclick = () => loadHistory(Math.max(1, historyPage - 1)).catch(error => showAlert(error.message, "error"));
  document.getElementById("history_next").onclick = () => loadHistory(Math.min(historyPages, historyPage + 1)).catch(error => showAlert(error.message, "error"));
  document.getElementById("btn_export_json").onclick = () => exportHistory("json");
  document.getElementById("btn_export_excel").onclick = () => exportHistory("xlsx");
  document.getElementById("history_text").addEventListener("keydown", event => { if (event.key === "Enter") loadHistory(1).catch(error => showAlert(error.message, "error")); });

  document.body.addEventListener("click", async event => {
    const copyButton = event.target.closest("[data-copy-id]");
    if (copyButton) return copyPublicationData(Number(copyButton.dataset.copyId));
    const detailButton = event.target.closest("[data-detail-id]");
    if (detailButton) return openDetail(Number(detailButton.dataset.detailId));
    const removeTermButton = event.target.closest(".or-term-remove");
    if (removeTermButton){
      const rows = document.querySelectorAll(".or-term-row");
      if (rows.length === 1) rows[0].querySelector("input").value = "";
      else removeTermButton.closest(".or-term-row").remove();
      return;
    }
    const annexOpen = event.target.closest("[data-annex-open]");
    if (annexOpen){
      const annex = selectedPublication?.annexes?.[Number(annexOpen.dataset.annexOpen)];
      const url = annex?.url || selectedPublication?.source_url;
      if (url) window.open(url, "_blank", "noopener");
      return;
    }
    const annexDownload = event.target.closest("[data-annex-download]");
    if (annexDownload) return downloadAnnex(Number(annexDownload.dataset.annexDownload));
    const annexCopy = event.target.closest("[data-annex-copy]");
    if (annexCopy){
      const annex = selectedPublication?.annexes?.[Number(annexCopy.dataset.annexCopy)];
      if (annex?.texto){
        await copyToClipboard(annex.texto);
        showAlert("Texto del anexo copiado al portapapeles.", "success");
      }
      return;
    }
    const editButton = event.target.closest("[data-alert-edit]");
    if (editButton) return openAlertModal(alerts.find(item => Number(item.id) === Number(editButton.dataset.alertEdit)));
    const stateButton = event.target.closest("[data-alert-state]");
    if (stateButton){
      try { await toggleAlert(Number(stateButton.dataset.alertState), stateButton.dataset.active === "1"); }
      catch(error){ showAlert(error.message, "error"); }
      return;
    }
    const deleteButton = event.target.closest("[data-alert-delete]");
    if (deleteButton){
      try { await deleteAlert(Number(deleteButton.dataset.alertDelete)); }
      catch(error){ showAlert(error.message, "error"); }
      return;
    }
    const closeButton = event.target.closest("[data-close]");
    if (closeButton){
      const modalByName = {detail:"detail_modal", alert:"alert_modal", import:"import_modal", tutorial:"tutorial_modal"};
      closeModal(modalByName[closeButton.dataset.close] || "tutorial_modal");
    }
  });

  document.getElementById("detail_open_pdf").onclick = () => {
    if (selectedPublication?.source_url) window.open(selectedPublication.source_url, "_blank", "noopener");
  };
  document.getElementById("detail_download_pdf").onclick = downloadSelectedPdf;
  document.getElementById("detail_copy_data").onclick = () => copyPublicationData();
  document.getElementById("detail_copy_full").onclick = () => copySelected("text_full", "Resolución completa");
  document.getElementById("detail_copy_resuelve").onclick = () => copySelected("text_resuelve", "Bloque RESUELVE");
  document.getElementById("detail_extract_full").onclick = () => extractSelectedInformation("complete");
  document.getElementById("detail_get_all").onclick = () => extractSelectedInformation("all");
  document.getElementById("btn_theme").onclick = () => applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  document.getElementById("btn_home").onclick = () => location.href = "./index.html";
  document.getElementById("btn_logout").onclick = goLogin;
  document.addEventListener("keydown", event => {
    if (event.key === "Escape"){
      closeModal("detail_modal");
      closeModal("alert_modal");
      closeModal("import_modal");
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
    await Promise.all([loadHealth(), loadAlerts(), loadHistoryFilterOptions(), loadHistory(1)]);
  } catch(error){
    document.getElementById("status").textContent = "Error de conexión";
    showAlert(error.message, "error");
  }
}

initialize();
