const TOKEN_KEY = "cyt-token";
const THEME_KEY = "cyt-theme";
const richState = new WeakMap();

const PROFILE_DEFAULTS = {
  minorista_agua: {caracter_prestadora:"prestadora minorista", servicio:"servicio de agua potable"},
  minorista_cloaca: {caracter_prestadora:"prestadora minorista", servicio:"servicio de saneamiento cloacal"},
  minorista_agua_cloaca: {caracter_prestadora:"prestadora minorista", servicio:"servicios de agua potable y saneamiento cloacal"},
  mayorista_agua: {caracter_prestadora:"prestadora mayorista", servicio:"servicio mayorista de agua potable"},
  mayorista_cloaca: {caracter_prestadora:"prestadora mayorista", servicio:"servicio mayorista de saneamiento cloacal"},
  mayorista_agua_cloaca: {caracter_prestadora:"prestadora mayorista", servicio:"servicios mayoristas de agua potable y saneamiento cloacal"},
};

function getToken(){ return localStorage.getItem(TOKEN_KEY) || ""; }
function clearToken(){ localStorage.removeItem(TOKEN_KEY); }
function tokenValid(){
  try { const body = JSON.parse(atob(getToken().split(".")[1])); return Number(body.exp || 0) * 1000 > Date.now(); }
  catch { return false; }
}
function goLogin(){ clearToken(); location.href = "./index.html"; }
function applyTheme(theme){
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  document.getElementById("btn_theme").textContent = theme === "dark" ? "☀️" : "🌙";
}
function initTheme(){ applyTheme(localStorage.getItem(THEME_KEY) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")); }
function showAlert(message, type=""){
  const element = document.getElementById("alert");
  element.className = `tool-alert ${type}`;
  element.textContent = message;
  element.style.display = "block";
}
function hideAlert(){ document.getElementById("alert").style.display = "none"; }
function activateSection(name){
  document.querySelectorAll(".it-nav-btn").forEach(button => button.classList.toggle("active", button.dataset.section === name));
  document.querySelectorAll(".it-section").forEach(panel => panel.classList.toggle("active", panel.dataset.panel === name));
  window.scrollTo({top: 250, behavior:"smooth"});
}
function collectData(){
  const data = {};
  document.querySelectorAll("[data-field]").forEach(input => { data[input.dataset.field] = input.value.trim(); });
  return data;
}
function filenameFromDisposition(header){
  const match = /filename\*=UTF-8''([^;]+)/i.exec(header || "");
  if (match) return decodeURIComponent(match[1]);
  return "Informe_Tecnico_CyT.docx";
}

function fileAsDataUrl(file){
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("No se pudo leer la imagen."));
    reader.readAsDataURL(file);
  });
}

function cellSpec(cell){
  const style = getComputedStyle(cell);
  const weight = Number.parseInt(style.fontWeight, 10);
  const bold = cell.querySelector("b,strong") !== null || style.fontWeight === "bold" || (!Number.isNaN(weight) && weight >= 600);
  let bg = style.backgroundColor || "";
  if (bg === "rgba(0, 0, 0, 0)" || bg === "transparent") bg = "";
  return {
    text: (cell.innerText || cell.textContent || "").replace(/\u00a0/g, " ").trim(),
    bold,
    bg,
    align: ["center","right"].includes(style.textAlign) ? style.textAlign : "left",
  };
}

function tableFromHtml(html){
  const holder = document.createElement("div");
  holder.className = "clipboard-html-sandbox";
  holder.setAttribute("aria-hidden", "true");
  holder.innerHTML = html;
  document.body.appendChild(holder);
  try {
    const table = holder.querySelector("table");
    if (!table) return null;
    const rows = Array.from(table.rows).slice(0, 250).map(row => {
      const out = [];
      Array.from(row.cells).slice(0, 20).forEach(cell => {
        const spec = cellSpec(cell);
        const span = Math.max(1, Math.min(20, Number(cell.colSpan || 1)));
        out.push(spec);
        for (let i=1; i<span; i++) out.push({...spec, text:""});
      });
      return out.slice(0, 20);
    });
    return rows.some(row => row.length) ? rows : null;
  } finally {
    holder.remove();
  }
}

function tableFromTsv(text){
  const lines = String(text || "").replace(/\r/g, "").split("\n").filter((line, i, arr) => line.length || i < arr.length - 1);
  if (!lines.length || !lines.some(line => line.includes("\t"))) return null;
  return lines.slice(0, 250).map((line, ridx) => line.split("\t").slice(0, 20).map(value => ({
    text:value.trim(), bold:ridx === 0, bg:"", align:"left"
  })));
}

function payloadLabel(payload){
  if (!payload) return "";
  if (payload.kind === "image") return "Imagen lista para insertar en Word";
  if (payload.kind === "table") {
    const rows = payload.rows?.length || 0;
    const cols = Math.max(0, ...(payload.rows || []).map(row => row.length));
    return `Rango de Excel detectado: ${rows} filas × ${cols} columnas`;
  }
  return "Contenido listo";
}

function renderPayloadPreview(block){
  const preview = block.querySelector(".rich-preview");
  const zone = block.querySelector(".rich-paste");
  const payload = richState.get(block);
  preview.innerHTML = "";
  if (!payload) {
    preview.hidden = true;
    zone.classList.remove("has-content");
    return;
  }
  zone.classList.add("has-content");
  preview.hidden = false;

  const meta = document.createElement("div");
  meta.className = "rich-preview-meta";
  meta.textContent = payloadLabel(payload);
  preview.appendChild(meta);

  if (payload.kind === "image") {
    const img = document.createElement("img");
    img.src = payload.data;
    img.alt = "Vista previa del contenido pegado";
    preview.appendChild(img);
    return;
  }
  if (payload.kind === "table") {
    const table = document.createElement("table");
    payload.rows.slice(0, 8).forEach((row, ridx) => {
      const tr = document.createElement("tr");
      row.slice(0, 8).forEach(cell => {
        const td = document.createElement(ridx === 0 ? "th" : "td");
        td.textContent = cell.text;
        if (cell.bg) td.style.background = cell.bg;
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    preview.appendChild(table);
    if (payload.rows.length > 8 || Math.max(0, ...payload.rows.map(row => row.length)) > 8) {
      const note = document.createElement("small");
      note.textContent = "Vista previa recortada; el Word incluirá la tabla completa.";
      preview.appendChild(note);
    }
  }
}

async function setImagePayload(block, file){
  if (!file || !file.type.startsWith("image/")) throw new Error("Seleccioná una imagen PNG o JPG.");
  if (file.size > 8 * 1024 * 1024) throw new Error("La imagen supera el máximo de 8 MB.");
  richState.set(block, {kind:"image", data:await fileAsDataUrl(file)});
  renderPayloadPreview(block);
}

async function handlePaste(event, block){
  event.preventDefault();
  hideAlert();
  const clipboard = event.clipboardData;
  if (!clipboard) return;

  const imageItem = Array.from(clipboard.items || []).find(item => item.kind === "file" && item.type.startsWith("image/"));
  if (imageItem) {
    await setImagePayload(block, imageItem.getAsFile());
    return;
  }

  const html = clipboard.getData("text/html");
  if (html) {
    const rows = tableFromHtml(html);
    if (rows) {
      richState.set(block, {kind:"table", rows});
      renderPayloadPreview(block);
      return;
    }
  }

  const text = clipboard.getData("text/plain");
  const rows = tableFromTsv(text);
  if (rows) {
    richState.set(block, {kind:"table", rows});
    renderPayloadPreview(block);
    return;
  }

  showAlert("El portapapeles no contiene una imagen ni un rango tabular de Excel. Para conservar el aspecto exacto, usá “Copiar como imagen” en Excel y pegalo aquí.", "error");
}

function initRichBlock(block){
  if (block.dataset.ready === "1") return;
  block.dataset.ready = "1";
  const zone = block.querySelector(".rich-paste");
  const fileInput = block.querySelector(".rich-file");
  zone.addEventListener("paste", event => handlePaste(event, block).catch(error => showAlert(error.message, "error")));
  zone.addEventListener("click", () => zone.focus());
  zone.addEventListener("dragover", event => { event.preventDefault(); zone.classList.add("dragging"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", event => {
    event.preventDefault();
    zone.classList.remove("dragging");
    const file = Array.from(event.dataTransfer?.files || []).find(item => item.type.startsWith("image/"));
    if (file) setImagePayload(block, file).catch(error => showAlert(error.message, "error"));
  });
  block.querySelector(".rich-file-btn").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (file) setImagePayload(block, file).catch(error => showAlert(error.message, "error"));
  });
  block.querySelector(".rich-clear-btn").addEventListener("click", () => {
    richState.delete(block);
    fileInput.value = "";
    renderPayloadPreview(block);
  });
  const remove = block.querySelector(".rich-remove-btn");
  if (remove) remove.addEventListener("click", () => block.remove());
}

function addCustomBlock(){
  const container = document.getElementById("rich_blocks");
  const article = document.createElement("article");
  article.className = "rich-block custom-rich-block";
  article.innerHTML = `
    <div class="rich-block-head"><strong>Bloque técnico adicional</strong><button type="button" class="rich-remove-btn" title="Eliminar bloque">×</button></div>
    <div class="rich-block-grid">
      <label class="tool-field"><span>Título / epígrafe</span><input class="rich-title" placeholder="Ej.: TABLA N.º 4: Composición por localidad"></label>
      <label class="tool-field"><span>Ubicación</span><select class="rich-position">
        <option value="analisis">Análisis de costos</option>
        <option value="canon">Rubro Canon</option>
        <option value="agua_bloque">Agua en bloque</option>
        <option value="metodologia">Después de Metodología</option>
        <option value="base">Base de facturación</option>
        <option value="cargos">Cargos especiales</option>
        <option value="cargo">Cargo Tarifario</option>
        <option value="pre_conclusion">Antes de la conclusión</option>
        <option value="anexo">Anexo</option>
      </select></label>
    </div>
    <label class="tool-field"><span>Texto previo al cuadro (opcional)</span><textarea class="rich-text" placeholder="Breve explicación del cuadro o gráfico."></textarea></label>
    <div class="rich-paste" tabindex="0"><span class="rich-paste-main">Pegá acá un gráfico, imagen o rango de Excel</span><span class="rich-paste-sub">Ctrl+V · también podés arrastrar una imagen</span></div>
    <div class="rich-preview" hidden></div>
    <div class="rich-actions"><button type="button" class="action rich-file-btn">Elegir imagen</button><button type="button" class="action rich-clear-btn">Limpiar</button></div>
    <input class="rich-file" type="file" accept="image/png,image/jpeg,image/gif,image/bmp" hidden>
    <input class="rich-source" placeholder="Fuente (opcional)">
  `;
  container.appendChild(article);
  initRichBlock(article);
  article.querySelector(".rich-title").focus();
}

function collectBlocks(){
  return Array.from(document.querySelectorAll(".rich-block")).map(block => ({
    title: block.querySelector(".rich-title")?.value.trim() || "",
    position: block.querySelector(".rich-position")?.value || "analisis",
    text: block.querySelector(".rich-text")?.value.trim() || "",
    source: block.querySelector(".rich-source")?.value.trim() || "",
    payload: richState.get(block) || null,
  })).filter(block => block.payload || block.text);
}

function applyProfileDefaults(){
  const profile = PROFILE_DEFAULTS[document.getElementById("report_profile").value];
  if (!profile) return;
  ["caracter_prestadora", "servicio"].forEach(key => {
    const input = document.querySelector(`[data-field="${key}"]`);
    if (!input.value.trim() || input.dataset.profileDefault === "1") {
      input.value = profile[key];
      input.dataset.profileDefault = "1";
    }
  });
}

async function generate(event){
  event.preventDefault();
  hideAlert();
  const button = document.getElementById("btn_generate");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Generando Word...";
  document.getElementById("status").textContent = "Generando documento...";
  try {
    const response = await fetch(apiUrl("/api/informes/generar"), {
      method:"POST",
      headers:{"Content-Type":"application/json", Authorization:`Bearer ${getToken()}`},
      body:JSON.stringify({
        tipo:document.getElementById("report_type").value,
        perfil:document.getElementById("report_profile").value,
        modalidad:document.getElementById("report_mode").value,
        datos:collectData(),
        bloques:collectBlocks(),
      }),
    });
    if (response.status === 401) { goLogin(); return; }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Error HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filenameFromDisposition(response.headers.get("Content-Disposition"));
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showAlert("Informe Técnico generado correctamente. Revisá el Word descargado.", "success");
    document.getElementById("status").textContent = "Documento generado";
  } catch(error) {
    showAlert(error.message, "error");
    document.getElementById("status").textContent = "No se pudo generar";
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

if (!tokenValid()) goLogin();
initTheme();
document.getElementById("btn_theme").onclick = () => applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
document.getElementById("btn_home").onclick = () => location.href = "./index.html";
document.getElementById("btn_logout").onclick = goLogin;
document.querySelectorAll(".it-nav-btn").forEach(button => button.onclick = () => activateSection(button.dataset.section));
document.getElementById("it_form").addEventListener("submit", generate);
document.querySelectorAll(".rich-block").forEach(initRichBlock);
document.getElementById("btn_add_block").onclick = addCustomBlock;
document.getElementById("report_profile").onchange = applyProfileDefaults;
document.querySelectorAll('[data-field="caracter_prestadora"], [data-field="servicio"]').forEach(input => {
  input.addEventListener("input", () => { input.dataset.profileDefault = "0"; });
});
applyProfileDefaults();

document.getElementById("btn_reset").onclick = () => {
  if (!confirm("¿Restablecer todos los campos del formulario y los cuadros pegados?")) return;
  document.getElementById("it_form").reset();
  document.getElementById("report_type").value = "comun";
  document.getElementById("report_profile").value = "minorista_agua";
  document.getElementById("report_mode").value = "revision";
  document.querySelectorAll(".custom-rich-block").forEach(block => block.remove());
  document.querySelectorAll(".rich-block").forEach(block => { richState.delete(block); renderPayloadPreview(block); });
  document.querySelectorAll('[data-field="caracter_prestadora"], [data-field="servicio"]').forEach(input => { input.dataset.profileDefault = "1"; });
  applyProfileDefaults();
  activateSection("general");
  showAlert("Formulario restablecido.");
};

document.getElementById("report_type").onchange = event => {
  const cargoButton = document.querySelector('[data-section="cargo"]');
  cargoButton.textContent = event.target.value === "cargo_tarifario" ? "4. Cargo Tarifario · activo" : "4. Cargo Tarifario";
};
