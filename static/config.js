/* Configuración del frontend servido directamente por FastAPI. */
window.ERSEP_CONFIG = Object.freeze({
  API_BASE_URL: window.location.origin
});

window.apiUrl = function apiUrl(path) {
  const value = String(path || "");
  if (/^https?:\/\//i.test(value)) return value;
  const base = String(window.ERSEP_CONFIG.API_BASE_URL || "").replace(/\/+$/, "");
  const normalized = value.startsWith("/") ? value : `/${value}`;
  return `${base}${normalized}`;
};
