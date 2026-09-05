const TOKEN_KEY = "cyt-token";
const THEME_KEY = "cyt-theme";

const BIRTHDAYS = [
  { name: "Lucas Sebastián González Etienot", day: 24, month: 10 },
  { name: "Natalia Viale", day: 2, month: 5 },
  { name: "Manuela Solá", day: 16, month: 8 },
  { name: "Agustín Primo", day: 1, month: 6 },
  { name: "Rodrigo San Martin", day: 20, month: 7 },
  { name: "Julieta Gallegos", day: 21, month: 8 },
  { name: "Camila Lotumolo", day: 21, month: 5 },
  { name: "Leandro Ramallo", day: 9, month: 6 },
  { name: "Marcos Nanini", day: 7, month: 10 },
];

const DAY_MS = 24 * 60 * 60 * 1000;

function getToken(){
  return localStorage.getItem(TOKEN_KEY) || "";
}

function clearToken(){
  localStorage.removeItem(TOKEN_KEY);
}

function tokenValid(){
  try {
    const tokenPart = getToken().split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const body = JSON.parse(atob(tokenPart));
    return Number(body.exp || 0) * 1000 > Date.now();
  } catch {
    return false;
  }
}

function goLogin(){
  clearToken();
  location.href = "./index.html";
}

function applyTheme(theme){
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  document.getElementById("btn_theme").textContent = theme === "dark" ? "☀️" : "🌙";
}

function initTheme(){
  const saved = localStorage.getItem(THEME_KEY);
  const preferred = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  applyTheme(saved || preferred);
}

function escapeHtml(value){
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character]);
}


async function api(path, options={}){
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    goLogin();
    throw new Error("Sesión expirada.");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Error HTTP ${response.status}`);
  return payload;
}

function parseAmount(value){
  let text = String(value || "").trim().replace(/[$\s]/g, "");
  if (text.includes(",") && text.includes(".")) text = text.replace(/\./g, "").replace(",", ".");
  else if (text.includes(",")) text = text.replace(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(text)) text = text.replace(/\./g, "");
  const number = Number(text);
  if (!Number.isFinite(number) || number <= 0) throw new Error("Ingresá un valor base mayor que cero.");
  return number;
}

function money(value){
  return Number(value).toLocaleString("es-AR", {
    style: "currency",
    currency: "ARS",
    maximumFractionDigits: 2,
  });
}

function num(value, digits=4){
  return Number(value).toLocaleString("es-AR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function pct(value){
  return `${Number(value).toLocaleString("es-AR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

function showAlert(message, type=""){
  const element = document.getElementById("alert");
  element.className = `tool-alert ${type}`;
  element.textContent = message;
  element.style.display = "block";
}

function hideAlert(){
  document.getElementById("alert").style.display = "none";
}

async function loadMeta(){
  const payload = await api("/api/cumpleanos/meta");
  const options = payload.months
    .map(item => `<option value="${item.value}">${escapeHtml(item.label)}</option>`)
    .join("");

  document.getElementById("base_month").innerHTML = options;
  document.getElementById("target_month").innerHTML = options;
  document.getElementById("base_month").value = payload.default_base;
  document.getElementById("target_month").value = payload.default_target;
  document.getElementById("amount").value = Number(payload.default_amount || 10000).toLocaleString("es-AR");
  document.getElementById("status").textContent = `${BIRTHDAYS.length} agentes · base conectada`;
}

function renderCalculation(payload){
  const cards = document.getElementById("result_cards");
  const table = document.getElementById("result_table");

  cards.innerHTML = payload.results.map(item => {
    if (!item.available) {
      return `<article class="result-card unavailable" data-accent="${item.accent}">
        <div class="result-label">${escapeHtml(item.label)}</div>
        <strong>Sin datos suficientes</strong>
        <div class="result-index">${escapeHtml(item.reason)}</div>
      </article>`;
    }
    return `<article class="result-card" data-accent="${item.accent}">
      <div class="result-label">${escapeHtml(item.label)}</div>
      <strong>${money(item.updated_amount)}</strong>
      <div class="result-change">${pct(item.variation_pct)} acumulado</div>
      <div class="result-index">Índice ${num(item.base_index)} → ${num(item.target_index)}</div>
    </article>`;
  }).join("");

  table.innerHTML = payload.results.map(item => {
    if (!item.available) {
      return `<tr><td>${escapeHtml(item.label)}</td><td colspan="5">${escapeHtml(item.reason)}</td></tr>`;
    }
    return `<tr>
      <td>${escapeHtml(item.label)}</td>
      <td class="num">${num(item.base_index)}</td>
      <td class="num">${num(item.target_index)}</td>
      <td class="num">${num(item.factor, 6)}</td>
      <td class="num">${pct(item.variation_pct)}</td>
      <td class="num"><strong>${money(item.updated_amount)}</strong></td>
    </tr>`;
  }).join("");

  document.getElementById("results").style.display = "block";
  showAlert(`Cálculo realizado con ${payload.available_count} series disponibles.`, "success");
}

async function calculate(event){
  event.preventDefault();
  hideAlert();
  const button = document.getElementById("btn_calculate");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Calculando...";

  try {
    const payload = await api("/api/cumpleanos/calcular", {
      method: "POST",
      body: JSON.stringify({
        amount: parseAmount(document.getElementById("amount").value),
        base_month: document.getElementById("base_month").value,
        target_month: document.getElementById("target_month").value,
      }),
    });
    renderCalculation(payload);
  } catch (error) {
    showAlert(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function localDateOnly(date = new Date()){
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function getNextBirthdayDate(birthday, today){
  let nextDate = new Date(today.getFullYear(), birthday.month - 1, birthday.day);
  if (nextDate < today) {
    nextDate = new Date(today.getFullYear() + 1, birthday.month - 1, birthday.day);
  }
  return nextDate;
}

function getDaysUntil(date, today){
  return Math.round((date.getTime() - today.getTime()) / DAY_MS);
}

function getTrafficLight(days){
  if (days <= 7) {
    return {
      className: "danger",
      label: days === 0 ? "¡Es hoy!" : "Cumpleaños inminente",
    };
  }
  if (days <= 30) {
    return {
      className: "warning",
      label: "Falta menos de un mes",
    };
  }
  return {
    className: "safe",
    label: "Todavía hay tiempo",
  };
}

function formatBirthdayDate(date){
  return new Intl.DateTimeFormat("es-AR", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(date);
}

function formatShortBirthdayDate(date){
  return new Intl.DateTimeFormat("es-AR", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  }).format(date);
}

function formatDays(days){
  if (days === 0) return "Hoy";
  if (days === 1) return "Mañana";
  return `${days} días`;
}

function formatInitials(name){
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0].toUpperCase())
    .join("");
}

function getBirthdaySchedule(){
  const today = localDateOnly();
  return BIRTHDAYS
    .map(birthday => {
      const nextDate = getNextBirthdayDate(birthday, today);
      const days = getDaysUntil(nextDate, today);
      return {
        ...birthday,
        nextDate,
        days,
        trafficLight: getTrafficLight(days),
      };
    })
    .sort((a, b) => a.days - b.days || a.name.localeCompare(b.name, "es"));
}

function renderSummary(schedule){
  const nextBirthday = schedule[0];
  const thisMonth = BIRTHDAYS.filter(item => item.month === new Date().getMonth() + 1);
  const trafficLight = nextBirthday.trafficLight;

  document.getElementById("next_birthday_name").textContent = nextBirthday.name;
  document.getElementById("next_birthday_date").textContent = formatBirthdayDate(nextBirthday.nextDate);
  document.getElementById("next_birthday_countdown").textContent = formatDays(nextBirthday.days);
  document.getElementById("next_birthday_message").textContent = trafficLight.label;
  document.getElementById("birthdays_this_month").textContent = String(thisMonth.length);
  document.getElementById("birthdays_this_month_detail").textContent =
    thisMonth.length === 1 ? "Cumpleaños registrado este mes" : "Cumpleaños registrados este mes";

  const countdownCard = document.getElementById("countdown_card");
  const countdownDot = document.getElementById("countdown_dot");
  countdownCard.classList.remove("danger", "warning", "safe");
  countdownDot.classList.remove("danger", "warning", "safe");
  countdownCard.classList.add(trafficLight.className);
  countdownDot.classList.add(trafficLight.className);
}

function renderBirthdayList(schedule){
  const list = document.getElementById("birthday_list");

  list.innerHTML = schedule.map((birthday, index) => {
    const isNext = index === 0;
    const daysLabel = formatDays(birthday.days);
    const nextBadge = isNext ? '<span class="birthday-next-badge">Próximo</span>' : "";

    return `
      <article class="birthday-person ${birthday.trafficLight.className}${isNext ? " is-next" : ""}">
        <div class="birthday-avatar" aria-hidden="true">${escapeHtml(formatInitials(birthday.name))}</div>
        <div>
          <strong class="birthday-person-name">${escapeHtml(birthday.name)}</strong>
          <span class="birthday-person-date">${escapeHtml(formatShortBirthdayDate(birthday.nextDate))}</span>
          ${nextBadge}
        </div>
        <div class="birthday-days">
          <strong>${escapeHtml(daysLabel)}</strong>
          <span>${escapeHtml(birthday.trafficLight.label)}</span>
        </div>
      </article>
    `;
  }).join("");
}

function renderBirthdayPanel(){
  const schedule = getBirthdaySchedule();
  renderSummary(schedule);
  renderBirthdayList(schedule);

  const now = new Date();
  document.getElementById("status").textContent = `${BIRTHDAYS.length} agentes · agenda actualizada`;
  document.getElementById("birthday_updated_at").textContent =
    `Actualizado automáticamente al ${new Intl.DateTimeFormat("es-AR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(now)}.`;
}

if (!tokenValid()) {
  goLogin();
} else {
  initTheme();
  document.getElementById("btn_theme").onclick = () => {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    applyTheme(currentTheme === "dark" ? "light" : "dark");
  };
  document.getElementById("btn_home").onclick = () => location.href = "./index.html";
  document.getElementById("btn_logout").onclick = goLogin;

  renderBirthdayPanel();

  document.getElementById("birthday_form").addEventListener("submit", calculate);
  document.getElementById("btn_swap").onclick = () => {
    const base = document.getElementById("base_month");
    const target = document.getElementById("target_month");
    [base.value, target.value] = [target.value, base.value];
  };

  loadMeta().catch(error => {
    document.getElementById("status").textContent = `${BIRTHDAYS.length} agentes · agenda lista`;
    showAlert(`La agenda funciona correctamente, pero no se pudo conectar la herramienta de actualización: ${error.message}`, "error");
  });

  let renderedDay = localDateOnly().getTime();
  setInterval(() => {
    const currentDay = localDateOnly().getTime();
    if (currentDay !== renderedDay) {
      renderedDay = currentDay;
      renderBirthdayPanel();
    }
  }, 60 * 1000);
}
