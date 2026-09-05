// ===== auth + theme (reutiliza las mismas keys que ya usás) =====
const TOKEN_KEY = "cyt-token";

function getToken() { return localStorage.getItem(TOKEN_KEY) ?? ""; }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("btn_theme");
  if (btn) btn.textContent = theme === "dark" ? "☀️" : "🌙";
  localStorage.setItem("cyt-theme", theme);
}
function initTheme() {
  const saved = localStorage.getItem("cyt-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved ?? (prefersDark ? "dark" : "light"));
}
function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") ?? "light";
  applyTheme(current === "dark" ? "light" : "dark");
}

async function api(path, options = {}) {
  const token = getToken();
  const r = await fetch(apiUrl(path), {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  });
  if (r.status === 401) { clearToken(); location.href = "./index.html"; throw new Error("Sesión expirada."); }
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail ?? "Error"); }
  return r.json();
}

function formatDateLabel(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s).trim());
  if (!m) return s;
  const y = Number(m[1]), mm = Number(m[2]);
  const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
  return `${meses[mm-1]}-${y}`;
}
function toEsNumberString(v, decimals = 2) {
  if (typeof v !== "number" || !Number.isFinite(v)) return "";
  return v.toLocaleString("es-AR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).replace(/\./g, "");
}

// ===== monthpicker (igual al tuyo, mínimo necesario) =====
let _ALL_SERIES = [];
let _ALL_DATES  = [];
let _DATES_BY_YM = new Map();
let _YEARS = [];
let _PICK_TARGET = "desde";
let _PICK_YEAR = null;
let _PICK_SELECTED_YM = null;

function ymKeyFromIso(iso) {
  const m = /^(\d{4})-(\d{2})-\d{2}$/.exec(String(iso).trim());
  return m ? `${m[1]}-${m[2]}` : null;
}
function labelFromYm(ym) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(ym));
  if (!m) return ym;
  const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
  return `${meses[Number(m[2])-1]}-${Number(m[1])}`;
}
function rebuildDatesIndex() {
  _DATES_BY_YM = new Map();
  const yearsSet = new Set();
  for (const d of (_ALL_DATES || [])) {
    const iso = String(d.value ?? "").trim();
    const ym = ymKeyFromIso(iso);
    if (!ym) continue;
    if (!_DATES_BY_YM.has(ym)) _DATES_BY_YM.set(ym, iso);
    yearsSet.add(Number(ym.slice(0,4)));
  }
  _YEARS = Array.from(yearsSet).filter(Number.isFinite).sort((a,b)=>a-b);
}
function setPickValue(target, isoDate) {
  const sel = document.getElementById(target === "desde" ? "sel_desde" : "sel_hasta");
  sel.value = isoDate;
  const txt = target === "desde" ? document.getElementById("txt_desde") : document.getElementById("txt_hasta");
  const ym = ymKeyFromIso(isoDate);
  txt.textContent = ym ? labelFromYm(ym) : formatDateLabel(isoDate);
}
function openMonthPicker(target) {
  _PICK_TARGET = target;
  const currentIso = document.getElementById(target === "desde" ? "sel_desde" : "sel_hasta").value;
  const curYm = ymKeyFromIso(currentIso);
  _PICK_SELECTED_YM = curYm;
  const fallbackYear = _YEARS.length ? _YEARS[_YEARS.length - 1] : new Date().getFullYear();
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
  const prev = document.getElementById("yearPrev");
  const next = document.getElementById("yearNext");
  yearLabel.textContent = String(_PICK_YEAR);

  const minY = _YEARS.length ? _YEARS[0] : _PICK_YEAR;
  const maxY = _YEARS.length ? _YEARS[_YEARS.length - 1] : _PICK_YEAR;
  prev.disabled = _PICK_YEAR <= minY;
  next.disabled = _PICK_YEAR >= maxY;

  const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
  grid.innerHTML = meses.map((name, i) => {
    const mm = String(i+1).padStart(2,"0");
    const ym = `${_PICK_YEAR}-${mm}`;
    const iso = _DATES_BY_YM.get(ym);
    const isDisabled = !iso;
    const isActive = _PICK_SELECTED_YM === ym;
    return `<div class="month-item ${isDisabled ? "disabled":""} ${isActive ? "active":""}" data-ym="${ym}">${name}</div>`;
  }).join("");

  grid.querySelectorAll(".month-item").forEach(el => {
    el.onclick = () => {
      if (el.classList.contains("disabled")) return;
      _PICK_SELECTED_YM = el.getAttribute("data-ym");
      renderMonthPicker();
    };
  });
}

// ===== charts usando plotly (con librerías) =====
// Dibuja un “sparkline” simple en SVG
function renderPlotlyLines(containerId, datesIso, seriesArr, useBase100, mainCol) {
  const el = document.getElementById(containerId);

  // helper: calcula MoM% desde un array de niveles
  function calcMoMPct(levels) {
    const out = new Array(levels.length).fill(null);
    for (let i = 1; i < levels.length; i++) {
      const prev = levels[i - 1];
      const cur  = levels[i];
      if (typeof prev === "number" && Number.isFinite(prev) && prev !== 0 &&
          typeof cur  === "number" && Number.isFinite(cur)) {
        out[i] = ((cur / prev) - 1) * 100;
      } else {
        out[i] = null;
      }
    }
    return out;
  }

  const traces = seriesArr.map((s) => {
    // Si está tildado "Base 100", en realidad mostramos MoM%
    // 1) si backend ya manda mom_pct, lo usamos
    // 2) si no, lo calculamos desde values
    const yRaw = useBase100
      ? ((Array.isArray(s.mom_pct) && s.mom_pct.length) ? s.mom_pct : calcMoMPct(s.values || []))
      : ((s.values) || []);

    const x = [];
    const y = [];

    for (let i = 0; i < datesIso.length; i++) {
      const v = yRaw[i];
      if (typeof v === "number" && Number.isFinite(v)) {
        x.push(datesIso[i]);
        y.push(v);
      }
    }

    const isMain = s.col === mainCol;

    return {
      type: "scatter",
      mode: "lines",
      name:
        (document.querySelector(`#sel_main option[value="${CSS.escape(s.col)}"]`)?.textContent?.trim()) ??
        s.col,
      x,
      y,
      line: { width: isMain ? 3 : 2 },
      hovertemplate:
        "<b>%{fullData.name}</b><br>" +
        "%{x|%b-%Y}<br>" +
        (useBase100 ? "%{y:.2f}% (MoM)" : "%{y:.2f}") +
        "<extra></extra>",
    };
  });

  const layout = {
    margin: { l: 60, r: 20, t: 20, b: 55 },
    height: 360,
    hovermode: "x unified",
    legend: { orientation: "h", y: -0.25 },
    xaxis: {
      title: "Período",
      type: "date",
      tickformat: "%b-%Y",
      showgrid: true,
      rangeslider: { visible: true },
    },
    yaxis: useBase100
      ? { title: "Variación mensual (%)", showgrid: true, ticksuffix: "%" }
      : { title: "Valor", showgrid: true, tickformat: ",.2f" },
  };

  const config = {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["select2d", "lasso2d"],
  };

  Plotly.newPlot(el, traces, layout, config);
}
function renderPlotlyBarsMoM(containerId, datesIso, momPct, seriesName) {
  const el = document.getElementById(containerId);

  const x = [];
  const y = [];
  for (let i = 0; i < (datesIso || []).length; i++) {
    const v = momPct?.[i];
    if (typeof v === "number" && Number.isFinite(v)) {
      x.push(datesIso[i]);
      y.push(v);
    }
  }

  if (!x.length) {
    el.innerHTML = `<div class="chart-zero">No hay variaciones mensuales numéricas.</div>`;
    return;
  }

  const trace = {
    type: "bar",
    name: seriesName || "MoM",
    x,
    y,
    hovertemplate:
      "<b>%{fullData.name}</b><br>" +
      "%{x|%b-%Y}<br>" +
      "%{y:.2f}%<extra></extra>",
  };

  const layout = {
    margin: { l: 60, r: 20, t: 10, b: 90 },
    height: 360,
    hovermode: "x",
    showlegend: false,
    xaxis: {
      title: "Período",
      type: "date",
      tickformat: "%b-%Y",
      showgrid: true,
      automargin: true,
      tickangle: -35,
      rangeslider: { visible: false },
    },
    yaxis: { title: "Variación mensual (%)", showgrid: true, ticksuffix: "%", automargin: true },
  };

  const config = { responsive: true, displaylogo: false };

  Plotly.newPlot(el, [trace], layout, config);
}

// ===== init screen =====
function setupFilter(inputId, selectId) {
  document.getElementById(inputId).addEventListener("input", (e) => {
    const term = e.target.value.toLowerCase();
    const options = document.getElementById(selectId).options;
    for (let i = 0; i < options.length; i++) {
      options[i].style.display = options[i].text.toLowerCase().includes(term) ? "" : "none";
    }
  });
}

let _SERIES_INDEX = []; // [{id,name}]
let _SERIES_BY_ID = new Map();

function seriesNameById(id){
  return _SERIES_BY_ID.get(String(id)) ?? String(id);
}

function renderChips(){
  const mainEl = document.getElementById("chip_main");
  const cmpEl  = document.getElementById("chip_cmp");

  mainEl.innerHTML = _MAIN
    ? `<div class="chip main">${seriesNameById(_MAIN)} <span class="x" id="chip_main_x">✕</span></div>`
    : `<div class="chart-zero">No seleccionada</div>`;

  cmpEl.innerHTML = Array.from(_SELECTED).map(id => `
    <div class="chip" data-id="${String(id)}">
      ${seriesNameById(id)}
      <span class="x" data-x="${String(id)}">✕</span>
    </div>
  `).join("") || `<div class="chart-zero">Sin comparadas</div>`;

  const xMain = document.getElementById("chip_main_x");
  if (xMain) xMain.onclick = () => {
    _MAIN = null;
    document.getElementById("sel_main").value = "";
    renderChips();
  };

  cmpEl.querySelectorAll("[data-x]").forEach(btn => {
    btn.onclick = () => {
      const id = btn.getAttribute("data-x");
      _SELECTED.delete(id);
      renderChips();
    };
  });
}

function hideResults(){
  const box = document.getElementById("series_results");
  box.style.display = "none";
  box.innerHTML = "";
}

function showResults(items){
  const box = document.getElementById("series_results");
  if (!items.length) { hideResults(); return; }

  box.innerHTML = items.map(s => {
    const isMain = String(s.id) === String(_MAIN);
    const isSel  = _SELECTED.has(String(s.id));
    return `
      <div class="picker-item" data-id="${String(s.id)}">
        <div style="min-width:0;">
          <div class="picker-name">${s.name}</div>
          <div class="picker-meta">${String(s.id)}</div>
        </div>
        <div class="picker-actions">
          <button class="picker-btn primary" data-main="${String(s.id)}">${isMain ? "Principal ✓" : "Principal"}</button>
          <button class="picker-btn" data-add="${String(s.id)}">${isSel ? "Agregada ✓" : "+ Comparar"}</button>
        </div>
      </div>
    `;
  }).join("");

  box.style.display = "block";

  box.querySelectorAll("[data-main]").forEach(b => {
    b.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();

      const id = b.getAttribute("data-main");
      _MAIN = id;
      document.getElementById("sel_main").value = id;

      renderChips();

      // Mantener el menú abierto y refrescar tildes
      showResults(items);

      const input = document.getElementById("series_search");
      if (input) input.focus();
    };
  });

  box.querySelectorAll("[data-add]").forEach(b => {
    b.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();

      const id = String(b.getAttribute("data-add"));

      // Toggle simple
      if (_SELECTED.has(id)) _SELECTED.delete(id);
      else _SELECTED.add(id);

      renderChips();

      // No re-render masivo
      b.textContent = _SELECTED.has(id) ? "Agregada ✓" : "+ Comparar";

      const input = document.getElementById("series_search");
      if (input) input.focus();
    };
  });
} // ✅ cierre de showResults


function setupSeriesPicker(){
  const input = document.getElementById("series_search");
  if (!input) return;

  function showTopSeries() {
    showResults(_SERIES_INDEX); // sin recorte
  }

  input.addEventListener("focus", () => {
    if (!input.value.trim()) showTopSeries();
  });

  input.addEventListener("click", () => {
    if (!input.value.trim()) showTopSeries();
  });

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { showTopSeries(); return; }

    const res = _SERIES_INDEX.filter(s =>
      s.name.toLowerCase().includes(q) || String(s.id).toLowerCase().includes(q)
    );

    showResults(res);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { hideResults(); return; }

    if (e.key === "Backspace" && !input.value) {
      const arr = Array.from(_SELECTED);
      if (arr.length) {
        _SELECTED.delete(arr[arr.length - 1]);
        renderChips();
        e.preventDefault();
      }
      return;
    }

    if (e.key === "Enter") {
      const q = input.value.trim().toLowerCase();
      if (!q) return;

      const best = _SERIES_INDEX.find(s =>
        s.name.toLowerCase().includes(q) || String(s.id).toLowerCase().includes(q)
      );
      if (!best) return;

      const id = String(best.id);

      // Mantengo tu comportamiento: Shift+Enter principal, Enter agrega
      if (e.shiftKey) {
        _MAIN = id;
        _SELECTED.delete(id);
        document.getElementById("sel_main").value = id;
      } else {
        if (!_MAIN) {
          _MAIN = id;
          document.getElementById("sel_main").value = id;
        } else if (id !== _MAIN) {
          _SELECTED.add(id);
        }
      }

      input.value = "";
      renderChips();
      showTopSeries();
      e.preventDefault();
    }
  });

  // click afuera cierra resultados
  document.addEventListener("click", (e) => {
    const box = document.getElementById("series_results");
    const picker = box?.parentElement;
    if (!picker) return;
    if (!picker.contains(e.target)) hideResults();
  });
}

async function init() {
  const meta = await api("/api/meta");
  _ALL_SERIES = meta.value_columns;
  _ALL_DATES  = meta.index_values;

  _SERIES_INDEX = (_ALL_SERIES || []).map(s => ({ id: String(s.id ?? s.idx), name: String(s.name ?? s.id ?? s.idx) }));
  _SERIES_BY_ID = new Map(_SERIES_INDEX.map(s => [String(s.id), s.name]));

  // seguir llenando los selects ocultos (estado)
  document.getElementById("sel_main").innerHTML = _SERIES_INDEX
    .map(s => `<option value="${s.id}">${s.name}</option>`)
    .join("");

  document.getElementById("sel_cmp").innerHTML = _SERIES_INDEX
    .map(s => `<option value="${s.id}">${s.name}</option>`)
    .join("");

  setupSeriesPicker();
  renderChips();


  // fechas ocultas (monthpicker)
  const dateHtml = _ALL_DATES.map((d) => `<option value="${String(d.value)}">${String(d.label)}</option>`).join("");
  document.getElementById("sel_desde").innerHTML = dateHtml;
  document.getElementById("sel_hasta").innerHTML = dateHtml;

  const first = _ALL_DATES[0]?.value ?? "";
  const last  = _ALL_DATES[_ALL_DATES.length - 1]?.value ?? "";
  document.getElementById("sel_desde").value = first;
  document.getElementById("sel_hasta").value = last;

  rebuildDatesIndex();
  if (first) setPickValue("desde", first);
  if (last)  setPickValue("hasta", last);

  document.getElementById("status").textContent = "Ready";
}

async function graficar() {
  _MAIN = document.getElementById("sel_main").value;

  const desde = document.getElementById("sel_desde").value;
  const hasta = document.getElementById("sel_hasta").value;

  const cols = [_MAIN, ...Array.from(_SELECTED)].filter(Boolean);
  if (!cols.length) return alert("Elegí una serie principal.");

  const resp = await api(
    `/api/series?col_idxs=${encodeURIComponent(cols.join(","))}&desde=${encodeURIComponent(desde)}&hasta=${encodeURIComponent(hasta)}`
  );

  const useBase = document.getElementById("chk_base100").checked;
  const desdeLbl = formatDateLabel(resp.desde);
  const hastaLbl = formatDateLabel(resp.hasta);

  // Ficha comparativa
  document.getElementById("view_ficha").style.display = "block";
  document.getElementById("ficha_title").textContent = `Comparación | ${desdeLbl} → ${hastaLbl}`;

  const rows = resp.series.map(s => {
    const m = s.metrics || {};
    const tg = m.total_growth_pct == null ? "-" : (toEsNumberString(m.total_growth_pct,2) + "%");
    const av = m.avg_mom_pct == null ? "-" : (toEsNumberString(m.avg_mom_pct,2) + "%");
    const vo = m.vol_mom_pct == null ? "-" : (toEsNumberString(m.vol_mom_pct,2) + "%");

    const best = m.best_month ? `${formatDateLabel(m.best_month.date)} (${toEsNumberString(m.best_month.pct,2)}%)` : "-";
    const worst = m.worst_month ? `${formatDateLabel(m.worst_month.date)} (${toEsNumberString(m.worst_month.pct,2)}%)` : "-";

    const nameOpt = document.querySelector(`#sel_main option[value="${CSS.escape(s.col)}"]`);
    const name = nameOpt ? nameOpt.text.trim() : s.col;

    return `<tr>
      <td>${name}${s.col===_MAIN ? " <b>(principal)</b>" : ""}</td>
      <td class="num">${tg}</td>
      <td class="num">${av}</td>
      <td class="num">${vo}</td>
      <td>${best}</td>
      <td>${worst}</td>
    </tr>`;
  }).join("");

  document.getElementById("ficha_body").innerHTML = `
    <div class="table-wrap" style="margin:0; box-shadow:none; border:0;">
      <table class="tbl" style="width:100%;">
        <thead>
          <tr>
            <th>Serie</th>
            <th>Crec. total</th>
            <th>Prom. mensual</th>
            <th>Volatilidad (MoM)</th>
            <th>Mejor mes</th>
            <th>Peor mes</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div style="margin-top:10px; color:var(--text-faint); font-size:12px;">
        Nota: “Base 100” permite comparar evoluciones relativas aun cuando las series estén en distintas unidades.
      </div>
    </div>
  `;

  // Gráfico de líneas comparativo
  document.getElementById("view_linea").style.display = "block";
document.getElementById("chart_title").textContent =
  useBase
    ? `Variación mensual (%) | ${desdeLbl} → ${hastaLbl}`
    : `Evolución (niveles) | ${desdeLbl} → ${hastaLbl}`;

  renderPlotlyLines("line_chart", resp.dates, resp.series, useBase, _MAIN);

  const mainObj = resp.series.find(x => x.col === _MAIN);
  renderPlotlyBarsMoM(
    "mom_chart",
    resp.dates,
    mainObj ? mainObj.mom_pct : [],
    "Variación mensual (principal)"
  );

  document.getElementById("view_mom").style.display = "block";
} // <-- ESTA llave faltaba


// ===== comparación de series (estado) =====
const _SELECTED = new Set(); // series extra (comparación)
let _MAIN = null;



// ===== listeners =====
initTheme();

document.getElementById("btn_theme").onclick = toggleTheme;
document.getElementById("btn_home").onclick = () => { location.href = "./index.html"; };
document.getElementById("btn_logout").onclick = () => { clearToken(); location.href = "./index.html"; };
document.getElementById("btn_pick_desde").onclick = () => openMonthPicker("desde");
document.getElementById("btn_pick_hasta").onclick = () => openMonthPicker("hasta");
document.getElementById("monthBackdrop").onclick = closeMonthPicker;
document.getElementById("monthClose").onclick = closeMonthPicker;
document.getElementById("yearPrev").onclick = () => { _PICK_YEAR -= 1; renderMonthPicker(); };
document.getElementById("yearNext").onclick = () => { _PICK_YEAR += 1; renderMonthPicker(); };

document.getElementById("monthOk").onclick = () => {
  if (!_PICK_SELECTED_YM) return;
  const iso = _DATES_BY_YM.get(_PICK_SELECTED_YM);
  if (!iso) return;
  setPickValue(_PICK_TARGET, iso);
  closeMonthPicker();
};

document.getElementById("btn_graficar").onclick = graficar;
document.getElementById("btn_volver").onclick = () => { location.href = "./index.html"; };

// Arranque único
init().catch(e => alert(e.message));
