const TOKEN_KEY = "cyt-token";
const THEME_KEY = "cyt-theme";
const STORAGE_KEY = "cyt-incidencia-zonales-v1";

const DEFAULT_ZONALES = [
  {zonal:"Zonal 1", porcentaje:9.42, tarifa:14217, tarifa_sin_impuestos:9997.89029535865},
  {zonal:"Zonal 2", porcentaje:42.72, tarifa:36789, tarifa_sin_impuestos:25871.30801687764},
  {zonal:"Zonal 3", porcentaje:16.78, tarifa:39283, tarifa_sin_impuestos:27625.175808720112},
  {zonal:"Zonal 4", porcentaje:14.81, tarifa:45833, tarifa_sin_impuestos:32231.364275668075},
  {zonal:"Zonal 5", porcentaje:14.41, tarifa:34210, tarifa_sin_impuestos:24057.665260196907},
  {zonal:"Zonal 6", porcentaje:0.63, tarifa:87632, tarifa_sin_impuestos:61625.879043600566},
  {zonal:"Zonal 7", porcentaje:1.21, tarifa:184510, tarifa_sin_impuestos:129753.86779184248},
];

let currentFile = null;
let inspection = null;
let lastResult = null;

function getToken(){ return localStorage.getItem(TOKEN_KEY) || ""; }
function clearToken(){ localStorage.removeItem(TOKEN_KEY); }
function isTokenUsable(){
  const token = getToken();
  if (!token) return false;
  try { const body = JSON.parse(atob(token.split(".")[1])); return Number(body.exp || 0) * 1000 > Date.now(); }
  catch { return false; }
}
function redirectLogin(){ clearToken(); window.location.href = "./index.html"; }
function initTheme(){
  const saved = localStorage.getItem(THEME_KEY);
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (dark ? "dark" : "light"));
}
function applyTheme(theme){
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  document.getElementById("btn_theme").textContent = theme === "dark" ? "☀️" : "🌙";
}
function toggleTheme(){ applyTheme((document.documentElement.getAttribute("data-theme") || "light") === "dark" ? "light" : "dark"); }
async function api(path, options={}){
  const token = getToken();
  const headers = {...(options.headers || {}), ...(token ? {Authorization:`Bearer ${token}`} : {})};
  const response = await fetch(apiUrl(path), {...options, headers});
  if (response.status === 401){ redirectLogin(); throw new Error("Sesión expirada."); }
  if (!response.ok){ const payload = await response.json().catch(()=>({})); throw new Error(payload.detail || `Error HTTP ${response.status}`); }
  return response;
}
function setStatus(text){ document.getElementById("status").textContent = text; }
function showAlert(message, type="error"){
  const el = document.getElementById("global_alert");
  el.textContent = message; el.className = `tool-alert ${type}`; el.style.display = "block";
}
function hideAlert(){ document.getElementById("global_alert").style.display = "none"; }
function parseNumber(value){
  let text = String(value ?? "").trim().replace(/\s/g, "").replace(/\$/g, "").replace(/%/g, "");
  if (!text) return NaN;
  if (text.includes(",") && text.includes(".")) text = text.replace(/\./g, "").replace(",", ".");
  else if (text.includes(",")) text = text.replace(",", ".");
  return Number(text);
}
const money = new Intl.NumberFormat("es-AR", {style:"currency", currency:"ARS", maximumFractionDigits:0});
const number = new Intl.NumberFormat("es-AR", {maximumFractionDigits:2});
const pct = new Intl.NumberFormat("es-AR", {style:"percent", minimumFractionDigits:2, maximumFractionDigits:2});

function storedZonales(){
  try { const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY)); return Array.isArray(parsed) && parsed.length === 7 ? parsed : DEFAULT_ZONALES; }
  catch { return DEFAULT_ZONALES; }
}
function renderZonalInputs(values=storedZonales()){
  const body = document.getElementById("zonal_inputs"); body.innerHTML = "";
  values.forEach((z, i) => {
    const row = document.createElement("tr");
    row.innerHTML = `<th>${z.zonal || `Zonal ${i+1}`}</th>
      <td><input class="zonal-input" data-kind="porcentaje" data-index="${i}" inputmode="decimal" value="${z.porcentaje}"></td>
      <td><input class="zonal-input" data-kind="tarifa" data-index="${i}" inputmode="decimal" value="${z.tarifa}"></td>
      <td><input class="zonal-input" data-kind="tarifa_sin_impuestos" data-index="${i}" inputmode="decimal" value="${Number(z.tarifa_sin_impuestos).toFixed(2)}"></td>`;
    body.appendChild(row);
  });
  body.querySelectorAll("input").forEach(input => input.addEventListener("input", updateZonalTotals));
  updateZonalTotals();
}
function collectZonales(){
  const result = DEFAULT_ZONALES.map((base, i) => ({zonal:`Zonal ${i+1}`}));
  document.querySelectorAll(".zonal-input").forEach(input => {
    result[Number(input.dataset.index)][input.dataset.kind] = parseNumber(input.value);
  });
  for (const z of result){
    if (![z.porcentaje,z.tarifa,z.tarifa_sin_impuestos].every(Number.isFinite)) throw new Error(`Revisá los tres valores de ${z.zonal}.`);
    if (z.porcentaje < 0 || z.tarifa < 0 || z.tarifa_sin_impuestos < 0) throw new Error(`Los valores de ${z.zonal} no pueden ser negativos.`);
  }
  if (result.reduce((s,z)=>s+z.porcentaje,0) <= 0) throw new Error("La suma de porcentajes debe ser mayor que cero.");
  return result;
}
function updateZonalTotals(){
  try {
    const data = collectZonales(); const total = data.reduce((s,z)=>s+z.porcentaje,0); const divisor = total || 1;
    const avg = data.reduce((s,z)=>s+z.tarifa*z.porcentaje/divisor,0);
    const avgSin = data.reduce((s,z)=>s+z.tarifa_sin_impuestos*z.porcentaje/divisor,0);
    document.getElementById("zonal_pct_total").textContent = `${number.format(total)} %`;
    document.getElementById("zonal_tarifa_media").textContent = money.format(avg);
    document.getElementById("zonal_tarifa_sin_media").textContent = money.format(avgSin);
  } catch {}
}
function mappingIds(){ return ["ipcf","itf","pondih","miembros","codusu","nro_hogar","anio","trimestre","aglomerado","decil_itf","decil_ipcf"]; }
function fillSelect(select, columns, selected="", optional=true){
  select.innerHTML = optional ? '<option value="">— No utilizar —</option>' : '<option value="">— Seleccionar —</option>';
  columns.forEach(col => { const opt=document.createElement("option"); opt.value=col; opt.textContent=col; opt.selected=col===selected; select.appendChild(opt); });
}
function renderPreview(rows){
  const table = document.getElementById("preview_table"); table.innerHTML = "";
  if (!rows.length){ table.innerHTML="<tbody><tr><td>La hoja no contiene filas.</td></tr></tbody>"; return; }
  const cols = Object.keys(rows[0]);
  table.innerHTML = `<thead><tr>${cols.map(c=>`<th>${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${escapeHtml(r[c] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody>`;
}
function escapeHtml(value){ const div=document.createElement("div"); div.textContent=String(value); return div.innerHTML; }
async function inspectFile(sheetName=null){
  if (!currentFile) return;
  hideAlert(); setStatus("Inspeccionando Excel...");
  const form = new FormData(); form.append("file", currentFile); if (sheetName) form.append("sheet_name", sheetName);
  try {
    const response = await api("/api/incidencia/inspect-excel", {method:"POST", body:form}); inspection = await response.json();
    const sheet = document.getElementById("sheet_name"); const oldSheet=sheet.value; sheet.innerHTML="";
    inspection.sheet_names.forEach(name=>{ const opt=document.createElement("option"); opt.value=name; opt.textContent=name; opt.selected=name===inspection.selected_sheet; sheet.appendChild(opt); });
    mappingIds().forEach(key => fillSelect(document.getElementById(`col_${key}`), inspection.columns, inspection.suggested_mapping[key] || "", !["ipcf","itf","pondih"].includes(key)));
    document.getElementById("rows_chip").textContent = `${number.format(inspection.rows)} filas`;
    document.getElementById("preview_meta").textContent = `${inspection.selected_sheet} · primeras ${inspection.preview.length} filas`;
    renderPreview(inspection.preview);
    document.getElementById("mapping_panel").style.display = "block";
    setStatus("Archivo inspeccionado");
    if (oldSheet !== inspection.selected_sheet) document.getElementById("mapping_panel").scrollIntoView({behavior:"smooth", block:"start"});
  } catch (error){ showAlert(error.message); setStatus("Error de inspección"); }
}
function collectMapping(){
  const result={}; mappingIds().forEach(key=>result[key]=document.getElementById(`col_${key}`).value);
  for (const key of ["ipcf","itf","pondih"]) if (!result[key]) throw new Error(`Debés seleccionar la columna ${key.toUpperCase()}.`);
  return result;
}
function buildFormData(){
  if (!currentFile || !inspection) throw new Error("Primero seleccioná e inspeccioná un Excel.");
  const form = new FormData();
  form.append("file", currentFile); form.append("sheet_name", document.getElementById("sheet_name").value);
  form.append("mapping_json", JSON.stringify(collectMapping())); form.append("zonales_json", JSON.stringify(collectZonales()));
  form.append("aglomerado_valor", document.getElementById("aglomerado_valor").value.trim());
  form.append("eliminar_duplicados", document.getElementById("eliminar_duplicados").checked ? "true" : "false");
  return form;
}
function incidenceClass(value){ return value >= .03 ? "metric-high" : value >= .02 ? "metric-mid" : "metric-low"; }
function renderZonalResults(rows){
  const table=document.getElementById("zonal_results_table");
  const headers=["Zonal","Usuarios","Tramo","ITF medio","IPCF medio","Miembros","Tarifa c/imp.","Incidencia","Carga media","Tarifa s/imp.","Incidencia s/imp.","Carga s/imp.","Sin ingreso"];
  table.innerHTML=`<thead><tr>${headers.map(h=>`<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(z=>`<tr>
    <td><strong>${z.zonal}</strong></td><td>${pct.format(z.porcentaje_normalizado)}</td><td>P${number.format(z.percentil_inicial*100)}–P${number.format(z.percentil_final*100)}</td>
    <td>${money.format(z.itf_medio)}</td><td>${money.format(z.ipcf_medio)}</td><td>${z.miembros_promedio==null?"—":number.format(z.miembros_promedio)}</td>
    <td>${money.format(z.tarifa)}</td><td class="${incidenceClass(z.incidencia_general)}">${pct.format(z.incidencia_general)}</td><td>${z.carga_media_positivos==null?"—":pct.format(z.carga_media_positivos)}</td>
    <td>${money.format(z.tarifa_sin_impuestos)}</td><td>${pct.format(z.incidencia_general_sin_impuestos)}</td><td>${z.carga_media_positivos_sin_impuestos==null?"—":pct.format(z.carga_media_positivos_sin_impuestos)}</td><td>${pct.format(z.proporcion_sin_ingreso)}</td>
  </tr>`).join("")}</tbody>`;
  const max=Math.max(...rows.map(z=>z.incidencia_general));
  document.getElementById("incidence_bars").innerHTML=rows.map(z=>`<div class="incidence-bar-row"><strong>${z.zonal}</strong><div class="bar-track"><div class="bar-tax" title="Con impuestos" style="width:${max?z.incidencia_general/max*100:0}%"></div><div class="bar-no-tax" title="Sin impuestos" style="width:${max?z.incidencia_general_sin_impuestos/max*100:0}%"></div></div><span class="bar-label">${pct.format(z.incidencia_general)}</span></div>`).join("");
}
function renderPercentiles(rows){
  document.getElementById("eph_percentiles_table").innerHTML=`<thead><tr><th>Percentil</th><th>ITF</th><th>IPCF</th></tr></thead><tbody>${rows.map(r=>`<tr><td>P${r.percentil}</td><td>${money.format(r.itf)}</td><td>${money.format(r.ipcf)}</td></tr>`).join("")}</tbody>`;
}
function renderZonalPercentiles(rows){
  document.getElementById("zonal_percentiles_table").innerHTML=`<thead><tr><th>Zonal</th><th>Percentil interno</th><th>ITF</th><th>IPCF</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.zonal}</td><td>P${r.percentil}</td><td>${money.format(r.itf)}</td><td>${money.format(r.ipcf)}</td></tr>`).join("")}</tbody>`;
}
function renderResults(data){
  lastResult=data; const r=data.resumen;
  document.getElementById("kpi_hogares").textContent=number.format(r.hogares_expandidos);
  document.getElementById("kpi_tarifa").textContent=money.format(r.tarifa_promedio_ponderada);
  document.getElementById("kpi_incidencia").textContent=pct.format(r.incidencia_general_ponderada);
  document.getElementById("kpi_carga").textContent=pct.format(r.carga_media_positivos_ponderada);
  document.getElementById("kpi_sin_ingreso").textContent=pct.format(r.proporcion_total_sin_ingreso);
  const periodos=(r.periodos||[]).join(", ") || "período no identificado";
  document.getElementById("results_subtitle").textContent=`${number.format(r.filas_utilizadas)} hogares muestrales · ${periodos} · aglomerado ${r.aglomerado_filtro}`;
  document.getElementById("results_warnings").innerHTML=(data.advertencias||[]).map(w=>`<div class="warning-item">⚠ ${escapeHtml(w)}</div>`).join("");
  document.getElementById("automatic_analysis").innerHTML=(data.analisis||[]).map(a=>`<div class="analysis-item">${escapeHtml(a)}</div>`).join("");
  document.getElementById("method_list").innerHTML=(data.metodologia||[]).map(m=>`<li>${escapeHtml(m)}</li>`).join("");
  renderZonalResults(data.zonales); renderPercentiles(data.percentiles_eph); renderZonalPercentiles(data.percentiles_zonales);
  document.getElementById("results_section").style.display="block";
  document.getElementById("results_section").scrollIntoView({behavior:"smooth", block:"start"});
}
async function calculate(){
  hideAlert(); const btn=document.getElementById("btn_calculate"); const original=btn.textContent; btn.disabled=true; btn.textContent="Calculando..."; setStatus("Procesando EPH...");
  try { const response=await api("/api/incidencia/calcular",{method:"POST",body:buildFormData()}); const data=await response.json(); renderResults(data); setStatus("Análisis completado"); }
  catch(error){ showAlert(error.message); setStatus("Error de cálculo"); }
  finally{ btn.disabled=false; btn.textContent=original; }
}
async function exportExcel(){
  const btn=document.getElementById("btn_export"); const original=btn.textContent; btn.disabled=true; btn.textContent="Generando Excel..."; setStatus("Preparando descarga...");
  try {
    const response=await api("/api/incidencia/exportar.xlsx",{method:"POST",body:buildFormData()}); const blob=await response.blob();
    const disposition=response.headers.get("Content-Disposition")||""; const match=disposition.match(/filename="?([^";]+)"?/i); const filename=match?match[1]:"incidencia_tarifaria.xlsx";
    const url=URL.createObjectURL(blob); const a=document.createElement("a"); a.href=url; a.download=filename; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url); setStatus("Excel descargado");
  } catch(error){ showAlert(error.message); setStatus("Error de exportación"); }
  finally{btn.disabled=false;btn.textContent=original;}
}
async function downloadTemplate(){
  try { const response=await api("/api/incidencia/plantilla.xlsx"); const blob=await response.blob(); const url=URL.createObjectURL(blob); const a=document.createElement("a"); a.href=url;a.download="plantilla_eph_incidencia.xlsx";document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url); }
  catch(error){showAlert(error.message);}
}
function initTabs(){ document.querySelectorAll(".results-tab").forEach(btn=>btn.addEventListener("click",()=>{ document.querySelectorAll(".results-tab").forEach(b=>b.classList.toggle("active",b===btn)); document.querySelectorAll(".result-panel").forEach(p=>p.classList.remove("active")); document.getElementById(`result-${btn.dataset.resultTab}`).classList.add("active"); })); }
function init(){
  if (!isTokenUsable()){redirectLogin();return;} initTheme(); renderZonalInputs(); initTabs();
  document.getElementById("btn_home").onclick=()=>window.location.href="./index.html";
  document.getElementById("btn_theme").onclick=toggleTheme;
  document.getElementById("btn_logout").onclick=()=>{clearToken();window.location.href="./index.html";};
  document.getElementById("btn_reset_zonales").onclick=()=>{localStorage.removeItem(STORAGE_KEY);renderZonalInputs(DEFAULT_ZONALES);showAlert("Valores zonales restaurados.","success");};
  document.getElementById("btn_save_zonales").onclick=()=>{try{localStorage.setItem(STORAGE_KEY,JSON.stringify(collectZonales()));showAlert("Valores guardados en este navegador.","success");}catch(e){showAlert(e.message);}};
  document.getElementById("eph_file").addEventListener("change",event=>{currentFile=event.target.files?.[0]||null;inspection=null;lastResult=null;document.getElementById("mapping_panel").style.display="none";document.getElementById("results_section").style.display="none";document.getElementById("btn_inspect").disabled=!currentFile;if(currentFile){document.getElementById("file_title").textContent=currentFile.name;document.getElementById("file_subtitle").textContent=`${number.format(currentFile.size/1024)} KB · listo para inspeccionar`;}});
  document.getElementById("btn_inspect").onclick=()=>inspectFile();
  document.getElementById("sheet_name").addEventListener("change",event=>inspectFile(event.target.value));
  document.getElementById("btn_calculate").onclick=calculate;
  document.getElementById("btn_export").onclick=exportExcel;
  document.getElementById("btn_template").onclick=downloadTemplate;
}
document.addEventListener("DOMContentLoaded",init);
