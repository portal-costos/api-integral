/* =========================================================
   Configuración del frontend público (GitHub Pages)
   =========================================================
   Este archivo NO contiene secretos. El backend real vive en Render.
*/
window.ERSEP_CONFIG = Object.freeze({
  API_BASE_URL: "https://api-integral-costos.onrender.com"
});

window.apiUrl = function apiUrl(path) {
  const value = String(path || "");
  if (/^https?:\/\//i.test(value)) return value;
  const base = String(window.ERSEP_CONFIG.API_BASE_URL || "").replace(/\/+$/, "");
  const normalized = value.startsWith("/") ? value : `/${value}`;
  return `${base}${normalized}`;
};
