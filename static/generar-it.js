const TOKEN_KEY = "cyt-token";
const THEME_KEY = "cyt-theme";

function getToken(){ return localStorage.getItem(TOKEN_KEY) || ""; }
function clearToken(){ localStorage.removeItem(TOKEN_KEY); }
function tokenValid(){
  try { const body = JSON.parse(atob(getToken().split(".")[1])); return Number(body.exp || 0) * 1000 > Date.now(); }
  catch { return false; }
}
function goLogin(){ clearToken(); location.href = "/"; }
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
async function generate(event){
  event.preventDefault();
  hideAlert();
  const button = document.getElementById("btn_generate");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Generando Word...";
  document.getElementById("status").textContent = "Generando documento...";
  try {
    const response = await fetch("/api/informes/generar", {
      method:"POST",
      headers:{"Content-Type":"application/json", Authorization:`Bearer ${getToken()}`},
      body:JSON.stringify({tipo:document.getElementById("report_type").value, datos:collectData()}),
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
    showAlert("Informe Técnico generado correctamente. Revisá el archivo descargado.", "success");
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
document.getElementById("btn_home").onclick = () => location.href = "/";
document.getElementById("btn_logout").onclick = goLogin;
document.querySelectorAll(".it-nav-btn").forEach(button => button.onclick = () => activateSection(button.dataset.section));
document.getElementById("it_form").addEventListener("submit", generate);
document.getElementById("btn_reset").onclick = () => {
  if (!confirm("¿Restablecer todos los campos del formulario?")) return;
  document.getElementById("it_form").reset();
  document.getElementById("report_type").value = "comun";
  activateSection("general");
  showAlert("Formulario restablecido.");
};
document.getElementById("report_type").onchange = event => {
  const cargoButton = document.querySelector('[data-section="cargo"]');
  cargoButton.textContent = event.target.value === "cargo_tarifario" ? "4. Cargo Tarifario · activo" : "4. Cargo Tarifario";
};
