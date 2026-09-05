const TOKEN_KEY = "cyt-token";
const THEME_KEY = "cyt-theme";
let currentFile = null;
let lastInspection = null;
let ratesPayload = null;

function getToken(){ return localStorage.getItem(TOKEN_KEY) || ""; }
function clearToken(){ localStorage.removeItem(TOKEN_KEY); }
function isTokenUsable(){
  const token = getToken();
  if (!token) return false;
  try {
    const body = JSON.parse(atob(token.split(".")[1]));
    return Number(body.exp || 0) * 1000 > Date.now();
  } catch { return false; }
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
function toggleTheme(){
  const current = document.documentElement.getAttribute("data-theme") || "light";
  applyTheme(current === "dark" ? "light" : "dark");
}

async function api(path, options = {}){
  const token = getToken();
  const headers = { ...(options.headers || {}), ...(token ? {Authorization:`Bearer ${token}`} : {}) };
  if (!(options.body instanceof FormData) && options.body && !headers["Content-Type"]){
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(apiUrl(path), {...options, headers});
  if (response.status === 401){ redirectLogin(); throw new Error("Sesión expirada."); }
  if (!response.ok){
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Error HTTP ${response.status}`);
  }
  return response;
}

function setStatus(text){ document.getElementById("status").textContent = text; }
function showAlert(message, type="info"){
  const el = document.getElementById("global_alert");
  el.textContent = message || "";
  el.className = `arca-alert ${type}`;
  el.style.display = message ? "block" : "none";
}
function money(value){
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("es-AR", {style:"currency", currency:"ARS", minimumFractionDigits:2});
}
function numberEs(value, decimals=2){
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("es-AR", {minimumFractionDigits:decimals, maximumFractionDigits:decimals}) : "—";
}
function parseMoney(text){
  let s = String(text || "").trim().replace(/\$/g, "").replace(/\s/g, "");
  if (!s) return NaN;
  if (s.includes(",") && s.includes(".")) s = s.replace(/\./g, "").replace(",", ".");
  else if (s.includes(",")) s = s.replace(",", ".");
  else {
    const parts = s.split(".");
    if (parts.length > 1 && parts[parts.length-1].length === 3) s = parts.join("");
  }
  return Number(s);
}
function dateToArca(iso){
  if (!iso) return "";
  const [y,m,d] = iso.split("-");
  return `${d}/${m}/${y}`;
}
function escapeFilename(value){ return value.replace(/["\\/]/g, "_"); }

function setTabs(){
  document.querySelectorAll(".arca-tab").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".arca-tab").forEach(x => x.classList.remove("active"));
      document.querySelectorAll(".arca-panel").forEach(x => x.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(`tab-${button.dataset.tab}`).classList.add("active");
    });
  });
}

function renderRates(payload){
  ratesPayload = payload;
  const latest = payload.latest;
  document.getElementById("rate_value").textContent = latest ? `${numberEs(latest.resarcitorio_mensual,2)}%` : "—";
  document.getElementById("rate_period").textContent = latest ? `Desde ${latest.desde}` : "Sin tasas";
  const sourceLabel = payload.source === "official" ? "fuente oficial ARCA" : payload.source === "cache" ? "caché local" : "respaldo local";
  document.getElementById("rates_meta").textContent = `${payload.count || 0} tramos · ${sourceLabel} · carga ${payload.loaded_at || "—"}`;

  const body = document.getElementById("rates_body");
  body.replaceChildren();
  (payload.rates || []).slice().reverse().forEach(rate => {
    const tr = document.createElement("tr");
    [
      rate.Desde,
      rate.Hasta,
      rate.Norma,
      `${numberEs(rate["Resarcitorio mensual"],4)}%`,
      `${numberEs(rate["Resarcitorio diario"],6)}%`,
      rate.Fuente,
    ].forEach(value => {
      const td = document.createElement("td");
      td.textContent = value ?? "";
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });

  if ((payload.warnings || []).length){
    showAlert(payload.warnings.join("\n"), "warn");
  } else {
    showAlert("Tasas ARCA cargadas correctamente.", "success");
    setTimeout(() => showAlert(""), 2200);
  }
}

async function loadRates(force=false){
  setStatus(force ? "Consultando ARCA..." : "Cargando tasas...");
  const button = document.getElementById("btn_refresh_rates");
  button.disabled = true;
  try {
    const response = await api(`/api/arca/tasas${force ? "?force=true" : ""}`);
    renderRates(await response.json());
    setStatus("ARCA listo");
  } catch (error){
    setStatus("Error ARCA");
    showAlert(error.message, "error");
  } finally { button.disabled = false; }
}

function renderCalculation(result){
  if (!result.ok){
    document.getElementById("calc_result").style.display = "none";
    showAlert(result.error || "No se pudo realizar el cálculo.", "error");
    return;
  }
  showAlert("");
  document.getElementById("res_capital").textContent = money(result.importe_capital);
  document.getElementById("res_resarcitorios").textContent = money(result.intereses_resarcitorios);
  document.getElementById("res_capitalizados").textContent = money(result.intereses_capitalizados);
  document.getElementById("res_total").textContent = money(result.intereses_total);
  document.getElementById("res_dias").textContent = String(result.dias_transcurridos ?? 0);

  const body = document.getElementById("detail_body");
  body.replaceChildren();
  (result.detalle || []).forEach(detail => {
    const tr = document.createElement("tr");
    [
      detail.desde_mostrado,
      detail.hasta_mostrado,
      detail.tipo,
      money(detail.importe),
      `${numberEs(detail.tasa_mensual,4)}%`,
      `${numberEs(detail.tasa_diaria,6)}%`,
      detail.dias_transcurridos,
      money(detail.intereses),
      detail.norma || "",
    ].forEach(value => {
      const td = document.createElement("td");
      td.textContent = value ?? "";
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
  document.getElementById("calc_result").style.display = "block";
  document.getElementById("calc_result").scrollIntoView({behavior:"smooth", block:"start"});
}

async function calculate(event){
  event.preventDefault();
  const amount = parseMoney(document.getElementById("importe_capital").value);
  if (!Number.isFinite(amount) || amount <= 0){ showAlert("Ingresá un importe válido y mayor que cero.", "error"); return; }
  const payload = {
    fecha_vencimiento: dateToArca(document.getElementById("fecha_vencimiento").value),
    fecha_pago_capital: dateToArca(document.getElementById("fecha_pago_capital").value),
    importe_capital: amount,
    fecha_pago_intereses: dateToArca(document.getElementById("fecha_pago_intereses").value) || null,
  };
  const button = document.getElementById("btn_calcular");
  button.disabled = true; button.textContent = "Calculando..."; setStatus("Calculando...");
  try {
    const response = await api("/api/arca/calcular", {method:"POST", body:JSON.stringify(payload)});
    renderCalculation(await response.json());
    setStatus("Cálculo finalizado");
  } catch (error){ showAlert(error.message, "error"); setStatus("Error de cálculo"); }
  finally { button.disabled=false; button.textContent="Calcular intereses"; }
}

function clearCalculation(){
  document.getElementById("calc_form").reset();
  document.getElementById("calc_result").style.display = "none";
  showAlert("");
}

function fillSelect(select, columns, value="", optional=false){
  select.replaceChildren();
  if (optional){
    const empty = document.createElement("option"); empty.value=""; empty.textContent="— No utilizar —"; select.appendChild(empty);
  } else {
    const empty = document.createElement("option"); empty.value=""; empty.textContent="— Seleccionar —"; select.appendChild(empty);
  }
  columns.forEach(column => {
    const option = document.createElement("option"); option.value=column; option.textContent=column; select.appendChild(option);
  });
  select.value = value || "";
}

function renderPreview(columns, rows){
  const table = document.getElementById("preview_table");
  table.replaceChildren();
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach(column => { const th=document.createElement("th"); th.textContent=column; headRow.appendChild(th); });
  thead.appendChild(headRow); table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach(row => {
    const tr=document.createElement("tr");
    columns.forEach(column => { const td=document.createElement("td"); const v=row[column]; td.textContent=v===null||v===undefined?"":String(v); tr.appendChild(td); });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
}

async function inspectExcel(sheetName=null){
  if (!currentFile) return;
  const button=document.getElementById("btn_inspect");
  button.disabled=true; button.textContent="Inspeccionando..."; setStatus("Leyendo Excel...");
  const form=new FormData(); form.append("file",currentFile); if(sheetName) form.append("sheet_name",sheetName);
  try {
    const response=await api("/api/arca/inspect-excel",{method:"POST",body:form});
    const data=await response.json(); lastInspection=data;
    const sheet=document.getElementById("sheet_name");
    const previous=sheetName || data.selected_sheet;
    sheet.replaceChildren();
    data.sheet_names.forEach(name=>{const o=document.createElement("option");o.value=name;o.textContent=name;sheet.appendChild(o);});
    sheet.value=previous;
    const m=data.suggested_mapping || {};
    fillSelect(document.getElementById("col_vencimiento"),data.columns,m.fecha_vencimiento,false);
    fillSelect(document.getElementById("col_pago_capital"),data.columns,m.fecha_pago_capital,false);
    fillSelect(document.getElementById("col_importe"),data.columns,m.importe_capital,false);
    fillSelect(document.getElementById("col_pago_intereses"),data.columns,m.fecha_pago_intereses,true);
    document.getElementById("excel_rows").textContent=`${data.rows} filas`;
    renderPreview(data.columns,data.preview || []);
    document.getElementById("excel_config").style.display="block";
    setStatus("Excel inspeccionado"); showAlert("Archivo leído correctamente. Confirmá el mapeo antes de procesar.","success");
  } catch(error){ showAlert(error.message,"error"); setStatus("Error al leer Excel"); }
  finally{ button.disabled=false; button.textContent="Inspeccionar archivo"; }
}

async function processExcel(){
  if(!currentFile||!lastInspection){showAlert("Primero inspeccioná un archivo.","error");return;}
  const values={
    sheet_name:document.getElementById("sheet_name").value,
    col_vencimiento:document.getElementById("col_vencimiento").value,
    col_pago_capital:document.getElementById("col_pago_capital").value,
    col_importe:document.getElementById("col_importe").value,
    col_pago_intereses:document.getElementById("col_pago_intereses").value,
  };
  if(!values.col_vencimiento||!values.col_pago_capital||!values.col_importe){showAlert("Completá las tres columnas obligatorias.","error");return;}
  const form=new FormData();form.append("file",currentFile);Object.entries(values).forEach(([k,v])=>form.append(k,v));
  const button=document.getElementById("btn_process_excel");button.disabled=true;button.textContent="Procesando...";setStatus("Procesando Excel...");
  try{
    const response=await api("/api/arca/procesar-excel",{method:"POST",body:form});
    const blob=await response.blob();
    const disposition=response.headers.get("Content-Disposition")||"";
    const match=/filename="?([^";]+)"?/i.exec(disposition);
    const filename=escapeFilename(match?match[1]:"excel_con_intereses_arca.xlsx");
    const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
    showAlert("Excel procesado y descargado. Incluye resultados, tasas, resumen y detalle por tramos.","success");setStatus("Excel descargado");
  }catch(error){showAlert(error.message,"error");setStatus("Error al procesar");}
  finally{button.disabled=false;button.textContent="Procesar y descargar Excel final";}
}

async function downloadRates(){
  try{
    const response=await api("/api/arca/tasas.xlsx");const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="tasas_arca_usadas.xlsx";document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  }catch(error){showAlert(error.message,"error");}
}

function bindEvents(){
  document.getElementById("btn_home").onclick=()=>window.location.href="./index.html";
  document.getElementById("btn_theme").onclick=toggleTheme;
  document.getElementById("btn_logout").onclick=redirectLogin;
  document.getElementById("calc_form").addEventListener("submit",calculate);
  document.getElementById("btn_clear_calc").onclick=clearCalculation;
  document.getElementById("btn_refresh_rates").onclick=()=>loadRates(true);
  document.getElementById("btn_download_rates").onclick=downloadRates;
  const fileInput=document.getElementById("excel_file");
  fileInput.addEventListener("change",()=>{
    currentFile=fileInput.files[0]||null;lastInspection=null;document.getElementById("excel_config").style.display="none";
    document.getElementById("btn_inspect").disabled=!currentFile;
    document.getElementById("file_title").textContent=currentFile?currentFile.name:"Seleccionar Excel";
    document.getElementById("file_subtitle").textContent=currentFile?`${(currentFile.size/1024/1024).toFixed(2)} MB`:".xlsx o .xls · máximo configurable";
  });
  document.getElementById("btn_inspect").onclick=()=>inspectExcel();
  document.getElementById("sheet_name").addEventListener("change",e=>inspectExcel(e.target.value));
  document.getElementById("btn_process_excel").onclick=processExcel;
}

document.addEventListener("DOMContentLoaded",async()=>{
  if(!isTokenUsable()){redirectLogin();return;}
  initTheme();setTabs();bindEvents();await loadRates(false);
});
