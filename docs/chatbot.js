/* =========================================================
   CyT · Asistente Estadístico por reglas (sin IA)
   - Catálogo dinámico desde /api/meta
   - Sinónimos y desambiguación
   - Fechas mensuales y contexto conversacional simple
   - Datos siempre obtenidos desde la API
   ========================================================= */

(() => {
  "use strict";

  let CHAT_SERIES = [];
  let CHAT_DATES = [];
  let CHAT_READY = false;
  let CHAT_BUSY = false;
  const CHAT_CONTEXT = {
    seriesIds: [],
    desde: null,
    hasta: null,
    intent: null,
  };

  const STOPWORDS = new Set([
    "de", "del", "la", "el", "los", "las", "y", "en", "base", "indice", "indices",
    "promedio", "mensual", "serie", "empalme", "desde", "para", "por", "con", "un",
    "una", "nivel", "general", "valor", "valores", "cordoba", "indec", "bcra"
  ]);

  const MONTHS = {
    enero: 1, ene: 1,
    febrero: 2, feb: 2,
    marzo: 3, mar: 3,
    abril: 4, abr: 4,
    mayo: 5, may: 5,
    junio: 6, jun: 6,
    julio: 7, jul: 7,
    agosto: 8, ago: 8,
    septiembre: 9, setiembre: 9, sep: 9, sept: 9,
    octubre: 10, oct: 10,
    noviembre: 11, nov: 11,
    diciembre: 12, dic: 12,
  };

  const MONTH_PATTERN = Object.keys(MONTHS)
    .sort((a, b) => b.length - a.length)
    .join("|");

  function normalizeText(value) {
    return String(value ?? "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[“”«»]/g, '"')
      .replace(/[^a-z0-9%$+\-/\.\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function meaningfulTokens(value) {
    return normalizeText(value)
      .split(/\s+/)
      .filter(token => token.length >= 3 && !STOPWORDS.has(token) && !/^20\d{2}$/.test(token));
  }

  function isAllowedSeries(series) {
    const n = normalizeText(series?.name || series?.id || "");
    return n && !n.includes("no usar en api") && !n.includes("no usar en la api");
  }

  function findSeriesByFragments(fragments) {
    const norms = fragments.map(normalizeText);
    return CHAT_SERIES.find(s => norms.every(f => s.norm.includes(f))) || null;
  }

  function findAllSeriesByFragments(fragments) {
    const norms = fragments.map(normalizeText);
    return CHAT_SERIES.filter(s => norms.every(f => s.norm.includes(f)));
  }

  // Alias humanos. El catálogo final sigue siendo dinámico: cada alias busca
  // una serie real cargada desde /api/meta por fragmentos de su nombre oficial.
  const ALIAS_RULES = [
    // IPC / inflación
    { terms: ["inflacion cordoba", "inflacion de cordoba", "ipc cordoba", "ipc cordoba nivel general", "ipc cba", "ipc cba nivel general"], fragments: ["ipc cordoba", "nivel general"] },
    { terms: ["inflacion nacional", "inflacion argentina", "ipc nacional", "ipc indec nivel general", "ipc indec"], fragments: ["ipc indec", "nivel general"] },
    { terms: ["ipc indec estacional", "ipc nacional estacional"], fragments: ["ipc indec", "estacional"] },
    { terms: ["ipc indec nucleo", "inflacion nucleo nacional", "ipc nacional nucleo"], fragments: ["ipc indec", "nucleo"] },
    { terms: ["ipc indec regulados", "ipc nacional regulados"], fragments: ["ipc indec", "regulados"] },
    { terms: ["ipc indec bienes", "ipc nacional bienes"], fragments: ["ipc indec", "bienes"] },
    { terms: ["ipc indec servicios", "ipc nacional servicios"], fragments: ["ipc indec", "servicios"] },
    { terms: ["inflacion san luis", "ipc san luis"], fragments: ["ipc san luis"] },
    { terms: ["inflacion eeuu", "inflacion usa", "ipc eeuu", "ipc estados unidos"], fragments: ["ipc eeuu"] },
    { terms: ["ipc cordoba estacionales", "inflacion cordoba estacional"], fragments: ["ipc cordoba", "estacionales"] },
    { terms: ["ipc cordoba regulados", "inflacion cordoba regulados"], fragments: ["ipc cordoba", "regulados"] },
    { terms: ["ipc cordoba nucleo", "inflacion nucleo cordoba"], fragments: ["ipc cordoba", "nucleo"] },
    { terms: ["ipc cordoba bienes"], fragments: ["ipc cordoba", "bienes"] },
    { terms: ["ipc cordoba servicios"], fragments: ["ipc cordoba", "servicios"] },
    { terms: ["ipc cordoba alimentos", "alimentos y bebidas cordoba"], fragments: ["ipc cordoba", "alimentos y bebidas"] },
    { terms: ["ipc cordoba alquiler", "alquiler vivienda cordoba"], fragments: ["ipc cordoba", "alquiler de vivienda"] },
    { terms: ["ipc cordoba agua", "suministro agua ipc cordoba"], fragments: ["ipc cordoba", "suministro de agua y servicios"] },
    { terms: ["ipc cordoba agua cloacas", "agua cloacas desagues ipc"], fragments: ["ipc cordoba", "cloacas y desagues"] },
    { terms: ["ipc cordoba electricidad", "electricidad ipc cordoba"], fragments: ["ipc cordoba", "electricidad"] },
    { terms: ["ipc cordoba gas", "gas ipc cordoba"], fragments: ["ipc cordoba", "gas"] },
    { terms: ["ipc cordoba combustibles", "otros combustibles ipc cordoba"], fragments: ["ipc cordoba", "otros combustibles"] },
    { terms: ["ipc cordoba transporte", "transporte ipc cordoba"], fragments: ["ipc cordoba", "transporte"] },
    { terms: ["ipc cordoba comunicaciones", "informacion y comunicaciones ipc cordoba"], fragments: ["ipc cordoba", "informacion y comunicaciones"] },
    { terms: ["servicios telefonicos ipc cordoba", "telefono ipc cordoba", "fax ipc cordoba"], fragments: ["ipc cordoba", "servicios telefonico"] },
    { terms: ["seguros ipc cordoba", "servicios financieros ipc cordoba"], fragments: ["ipc cordoba", "seguros y servicios financieros"] },

    // ICC
    { terms: ["icc indec nivel general", "icc nacional", "construccion nacional"], fragments: ["icc indec", "nivel general"] },
    { terms: ["icc indec materiales", "materiales construccion indec"], fragments: ["icc indec", "materiales"] },
    { terms: ["icc indec mano de obra", "mano de obra construccion indec"], fragments: ["icc indec", "mano de obra"] },
    { terms: ["icc indec gastos generales", "gastos generales construccion indec"], fragments: ["icc indec", "gastos generales"] },
    { terms: ["icc cordoba", "icc cordoba nivel general", "construccion cordoba", "construccion cordoba nivel general", "icc cba"], fragments: ["icc cordoba", "nivel general empalme"] },
    { terms: ["icc cordoba materiales"], fragments: ["icc cordoba", "materiales empalme"] },
    { terms: ["icc cordoba mano de obra"], fragments: ["icc cordoba", "mano de obra empalme"] },
    { terms: ["icc cordoba varios"], fragments: ["icc cordoba", "varios empalme"] },

    // IPIM
    { terms: ["ipim", "ipim general", "ipim nivel general"], fragments: ["ipim ng", "nivel general"] },
    { terms: ["ipim importados", "productos importados ipim"], fragments: ["ipim i", "productos importados"] },
    { terms: ["ipim nacionales", "productos nacionales ipim"], fragments: ["ipim n", "productos nacionales"] },
    { terms: ["ipim manufacturados", "productos manufacturados ipim"], fragments: ["ipim d", "productos manufacturados"] },
    { terms: ["ipim madera", "madera ipim"], fragments: ["ipim 20", "madera"] },
    { terms: ["ipim petroleo", "refinados del petroleo", "productos refinados petroleo"], fragments: ["ipim 23", "refinados del petroleo"] },
    { terms: ["ipim quimicos", "ipim productos quimicos", "sustancias y productos quimicos"], fragments: ["ipim 24", "productos quimicos"] },
    { terms: ["ipim jabones", "ipim detergentes", "jabones y detergentes"], fragments: ["ipim 2424", "jabones y detergentes"] },
    { terms: ["ipim minerales no metalicos"], fragments: ["ipim 26", "minerales no metalicos"] },
    { terms: ["ipim maquinas y equipos"], fragments: ["ipim 29", "maquinas y equipos"] },
    { terms: ["ipim aparatos electricos", "ipim maquinas electricas"], fragments: ["ipim 31", "aparatos electricos"] },
    { terms: ["ipim instrumentos medicion", "equipos medicina ipim"], fragments: ["ipim 33", "instrumentos de medicion"] },
    { terms: ["ipim medidores servicios", "instrumentos medicion servicios domiciliarios"], fragments: ["ipim 3312", "servicios domiciliarios"] },
    { terms: ["ipim vehiculos", "vehiculos automotores ipim", "carrocerias repuestos ipim"], fragments: ["ipim 34", "vehiculos automotores"] },
    { terms: ["ipim energia", "ipim energia electrica"], fragments: ["ipim e", "energia electrica"] },

    // Salarios / RIPTE
    { terms: ["salario privado registrado", "salarios privado registrado", "indice salarios privado registrado"], fragments: ["salarios sector privado registrado"] },
    { terms: ["salario publico registrado", "salarios sector publico", "indice salarios publico"], fragments: ["salarios sector publico registrado"] },
    { terms: ["salario total registrado", "salarios total registrado"], fragments: ["salarios total registrado"] },
    { terms: ["salario privado no registrado", "salarios no registrado", "salario informal"], fragments: ["salarios sector privado no registrado"] },
    { terms: ["indice salarios total", "salarios total"], fragments: ["salarios total -"] },
    { terms: ["ripte no decreciente"], fragments: ["ripte no decreciente"] },
    { terms: ["salario ripte", "salario en pesos ripte"], fragments: ["salario en $ ripte"] },
    { terms: ["ripte"], fragments: ["indice ripte"] },

    // Moneda / tasas
    { terms: ["dolar bna", "tipo cambio bna", "dolar banco nacion", "tipo de cambio nominal"], fragments: ["tipo de cambio nominal promedio mensual", "bna"] },
    { terms: ["dolar mayorista", "a3500", "tipo cambio mayorista"], fragments: ["tipo de cambio mayorista a3500"] },
    { terms: ["dolar minorista", "b 9791", "b9791", "tipo cambio minorista comprador"], fragments: ["tipo de cambio minorista", "9791"] },
    { terms: ["dolar libre", "dolar blue historico", "dolar libre historico"], fragments: ["dolar libre historico"] },
    { terms: ["badlar nominal", "badlar n.a", "badlar na"], fragments: ["badlar", "% n.a"] },
    { terms: ["badlar efectiva", "badlar e.a", "badlar ea"], fragments: ["badlar", "% e.a"] },
    { terms: ["cer", "coeficiente estabilizacion referencia"], fragments: ["cer", "coeficiente de estabilizacion"] },
    { terms: ["uva", "unidad valor adquisitivo"], fragments: ["uva", "unidad de valor adquisitivo"] },
    { terms: ["icl", "indice contratos locacion", "contratos de locacion"], fragments: ["indice para contratos de locacion"] },

    // Obra pública / valores Córdoba
    { terms: ["iop agua potable", "obra publica agua potable indec"], fragments: ["obras publicas", "indec agua potable"] },
    { terms: ["iop desagues cloacales", "obra publica cloacas indec"], fragments: ["obras publicas", "desagues cloacales"] },
    { terms: ["jus cordoba", "jus"], fragments: ["jus - cordoba"] },
    { terms: ["modulo cpce", "modulos cpce", "cpce cordoba"], fragments: ["cpce cordoba", "modulos"] },
    { terms: ["iop aceros", "orden 1 aceros"], fragments: ["iop cordoba orden 1", "aceros"] },
    { terms: ["iop aridos", "aridos triturados", "orden 7"], fragments: ["iop cordoba orden 7"] },
    { terms: ["iop asfaltos", "orden 8 asfaltos"], fragments: ["iop cordoba orden 8"] },
    { terms: ["iop combustible", "orden 14 combustible"], fragments: ["iop cordoba orden 14"] },
    { terms: ["iop equipo", "amortizacion equipo", "orden 17"], fragments: ["iop cordoba orden 17"] },
    { terms: ["iop gastos generales", "orden 18"], fragments: ["iop cordoba orden 18"] },
    { terms: ["iop hormigon", "orden 21 hormigon"], fragments: ["iop cordoba orden 21"] },
    { terms: ["iop mano de obra", "orden 26 mano de obra"], fragments: ["iop cordoba orden 26"] },
    { terms: ["iop pintura", "pintura termoplastica", "orden 31"], fragments: ["iop cordoba orden 31"] },
    { terms: ["iop transporte", "orden 37 transporte"], fragments: ["iop cordoba orden 37"] },
    { terms: ["iop conductores", "conductores subterraneos", "orden 45"], fragments: ["iop cordoba orden 45"] },

    // Agua / ACSA / RAC / EPEC
    { terms: ["indice rac", "rac"], fragments: ["indice rac"] },
    { terms: ["vga", "valor gestion del agua"], fragments: ["vga", "valor gestion del agua"] },
    { terms: ["ku agua en bloque", "ku bloque"], fragments: ["ku agua en bloque"] },
    { terms: ["ku agua cruda", "ku cruda"], fragments: ["ku agua cruda"] },
    { terms: ["canon agua en bloque", "precio m3 agua en bloque"], fragments: ["canon precio m3 agua en bloque"] },
    { terms: ["canon agua cruda", "precio m3 agua cruda"], fragments: ["canon precio m3 agua cruda"] },
    { terms: ["cr acumulado no residenciales", "cr usuarios no residenciales"], fragments: ["cr acumulado usuarios no residenciales"] },
    { terms: ["cr acumulado otros usuarios", "cr otro tipo usuarios"], fragments: ["cr acumulado otro tipo de usuarios"] },
    { terms: ["indice fam", "fam epec", "fam"], fragments: ["indice fam", "usar este en la api"] },
  ];

  function compactAliasText(value) {
    const connectors = new Set(["de", "del", "la", "el", "los", "las", "en"]);
    return normalizeText(value).split(/\s+/).filter(t => t && !connectors.has(t)).join(" ");
  }

  function resolveAliasRules(queryNorm) {
    const qKey = compactAliasText(queryNorm);
    const hits = [];
    for (const rule of ALIAS_RULES) {
      const series = findSeriesByFragments(rule.fragments);
      if (!series) continue;
      for (const rawTerm of rule.terms) {
        const termKey = compactAliasText(rawTerm);
        if (termKey && qKey.includes(termKey)) {
          hits.push({ series, termKey, length: termKey.length });
        }
      }
    }

    // Si coincide “IPIM” y también “IPIM productos químicos”, conserva la
    // coincidencia específica. En consultas comparativas, términos distintos
    // (por ejemplo “IPC Córdoba e IPIM”) se conservan ambos.
    const specificHits = hits.filter(hit => !hits.some(other =>
      other !== hit &&
      other.length > hit.length &&
      other.termKey.includes(hit.termKey)
    ));

    specificHits.sort((a, b) => b.length - a.length);
    const selected = [];
    for (const hit of specificHits) {
      if (!selected.some(s => s.id === hit.series.id)) selected.push(hit.series);
    }
    return selected;
  }

  function scoreSeriesAgainstQuery(series, queryNorm) {
    if (queryNorm.includes(series.norm) && series.norm.length >= 5) return 1000 + series.norm.length;
    const tokens = series.tokens;
    if (!tokens.length) return 0;
    const queryTokens = new Set(meaningfulTokens(queryNorm));
    const matched = tokens.filter(token => queryTokens.has(token));
    if (matched.length < 2) return 0;
    const score = matched.reduce((sum, t) => sum + Math.min(t.length, 10), 0);
    const coverage = matched.length / Math.max(2, Math.min(tokens.length, 6));
    return score * coverage;
  }

  function ambiguousCategory(queryNorm) {
    const q = queryNorm;
    if (/\b(inflacion|ipc)\b/.test(q) && !/(cordoba|cba|indec|nacional|argentina|san luis|eeuu|usa|estados unidos)/.test(q)) {
      return [
        findSeriesByFragments(["ipc indec", "nivel general"]),
        findSeriesByFragments(["ipc cordoba", "nivel general"]),
        findSeriesByFragments(["ipc san luis"]),
        findSeriesByFragments(["ipc eeuu"]),
      ].filter(Boolean);
    }
    if (/\bdolar\b/.test(q) && !/(bna|nacion|mayorista|a3500|minorista|9791|libre|blue)/.test(q)) {
      return [
        findSeriesByFragments(["tipo de cambio nominal promedio mensual", "bna"]),
        findSeriesByFragments(["tipo de cambio mayorista a3500"]),
        findSeriesByFragments(["tipo de cambio minorista", "9791"]),
        findSeriesByFragments(["dolar libre historico"]),
      ].filter(Boolean);
    }
    if (/\bicc\b/.test(q) && !/(cordoba|cba|indec|nacional|materiales|mano de obra|gastos|varios)/.test(q)) {
      return [
        findSeriesByFragments(["icc indec", "nivel general"]),
        findSeriesByFragments(["icc cordoba", "nivel general empalme"]),
      ].filter(Boolean);
    }
    if (/\bbadlar\b/.test(q) && !/(nominal|efectiva|n.a|na|e.a|ea)/.test(q)) {
      return [
        findSeriesByFragments(["badlar", "% n.a"]),
        findSeriesByFragments(["badlar", "% e.a"]),
      ].filter(Boolean);
    }
    if (/\bsalarios?\b/.test(q) && !/(privado|publico|registrado|no registrado|informal|total|ripte)/.test(q)) {
      return CHAT_SERIES.filter(s => s.norm.includes("indice de salarios")).slice(0, 5);
    }
    return [];
  }

  function resolveSeries(query, forcedSeriesIds = []) {
    const q = normalizeText(query);
    if (forcedSeriesIds.length) {
      const forced = forcedSeriesIds.map(id => CHAT_SERIES.find(s => s.id === id)).filter(Boolean);
      return { series: forced, ambiguous: [] };
    }

    const ambiguous = ambiguousCategory(q);
    const aliasMatches = resolveAliasRules(q);

    // Las coincidencias por alias específico ganan a una ambigüedad genérica.
    if (aliasMatches.length) {
      // Complementar con coincidencias dinámicas fuertes para consultas comparativas.
      const scored = CHAT_SERIES
        .map(s => ({ s, score: scoreSeriesAgainstQuery(s, q) }))
        .filter(x => x.score >= 17)
        .sort((a, b) => b.score - a.score)
        .slice(0, 6)
        .map(x => x.s);
      const combined = [...aliasMatches];
      for (const s of scored) if (!combined.some(x => x.id === s.id)) combined.push(s);
      return { series: combined.slice(0, 5), ambiguous: [] };
    }

    if (ambiguous.length) return { series: [], ambiguous };

    const scored = CHAT_SERIES
      .map(s => ({ s, score: scoreSeriesAgainstQuery(s, q) }))
      .filter(x => x.score > 0)
      .sort((a, b) => b.score - a.score);

    if (!scored.length) {
      const contextual = CHAT_CONTEXT.seriesIds
        .map(id => CHAT_SERIES.find(s => s.id === id))
        .filter(Boolean);
      return { series: contextual, ambiguous: [] };
    }

    const best = scored[0].score;
    const near = scored.filter(x => x.score >= Math.max(12, best * 0.78)).slice(0, 5).map(x => x.s);
    if (near.length > 1 && best < 30) return { series: [], ambiguous: near };
    return { series: near.slice(0, 3), ambiguous: [] };
  }

  function detectIntent(queryNorm, dateCount) {
    if (/\b(ayuda|que datos|que indices|que series|indices disponibles|series disponibles)\b/.test(queryNorm)) return "help";
    if (/\b(variacion|vario|varia|aumento|aumento|subio|sube|crecio|crece|cambio|punta a punta|porcentaje)\b/.test(queryNorm)) return "variation";
    if (/\bcompar/.test(queryNorm)) return "variation";
    if (/\b(tabla|datos|serie completa|mostrame la serie|mostrar serie|evolucion)\b/.test(queryNorm)) return "table";
    if (/\b(valor|cuanto fue|cuanto era|dato puntual|dato de)\b/.test(queryNorm) && dateCount <= 1) return "value";
    if (dateCount >= 2) return "variation";
    if (dateCount === 1) return "value";
    return "variation";
  }

  function parseDateMentions(query) {
    const q = normalizeText(query);
    const regex = new RegExp(`\\b(${MONTH_PATTERN})\\b(?:\\s*(?:de|del)?\\s*[-/]?\\s*(19\\d{2}|20\\d{2}))?`, "g");
    const out = [];
    let match;
    while ((match = regex.exec(q)) !== null) {
      out.push({ month: MONTHS[match[1]], year: match[2] ? Number(match[2]) : null, raw: match[0], index: match.index });
    }

    const years = [...q.matchAll(/\b(19\d{2}|20\d{2})\b/g)].map(m => Number(m[1]));
    const uniqueYears = [...new Set(years)];
    if (out.length >= 2 && uniqueYears.length === 1) {
      for (const m of out) if (!m.year) m.year = uniqueYears[0];
    }
    if (out.length === 1 && !out[0].year && uniqueYears.length === 1) out[0].year = uniqueYears[0];

    return { mentions: out, years: uniqueYears };
  }

  function latestAvailableYear() {
    if (!CHAT_DATES.length) return new Date().getFullYear();
    return Number(String(CHAT_DATES[CHAT_DATES.length - 1]?.value || "").slice(0, 4)) || new Date().getFullYear();
  }

  function yearFromIso(iso) {
    return iso ? Number(String(iso).slice(0, 4)) : null;
  }

  function isoForMonth(year, month) {
    if (!year || !month) return null;
    const ym = `${year}-${String(month).padStart(2, "0")}`;
    if (typeof _DATES_BY_YM !== "undefined" && _DATES_BY_YM?.get) return _DATES_BY_YM.get(ym) || null;
    const found = CHAT_DATES.find(d => String(d.value).startsWith(ym));
    return found?.value || null;
  }

  function yearRange(year) {
    const dates = CHAT_DATES.filter(d => String(d.value).startsWith(`${year}-`));
    if (!dates.length) return { desde: null, hasta: null };
    return { desde: dates[0].value, hasta: dates[dates.length - 1].value };
  }

  function resolveDates(query, intent) {
    const q = normalizeText(query);
    const parsed = parseDateMentions(query);
    const m = parsed.mentions;
    let desde = null;
    let hasta = null;

    if (m.length >= 2) {
      if (!m[0].year) m[0].year = m[1].year || yearFromIso(CHAT_CONTEXT.desde) || latestAvailableYear();
      if (!m[1].year) m[1].year = m[0].year || yearFromIso(CHAT_CONTEXT.hasta) || latestAvailableYear();
      desde = isoForMonth(m[0].year, m[0].month);
      hasta = isoForMonth(m[1].year, m[1].month);
    } else if (m.length === 1) {
      const mention = m[0];
      const contextYear = /\bhasta\b/.test(q)
        ? yearFromIso(CHAT_CONTEXT.hasta)
        : /\bdesde\b/.test(q)
          ? yearFromIso(CHAT_CONTEXT.desde)
          : yearFromIso(CHAT_CONTEXT.hasta) || yearFromIso(CHAT_CONTEXT.desde);
      mention.year = mention.year || contextYear || latestAvailableYear();
      const iso = isoForMonth(mention.year, mention.month);

      if (intent === "value") {
        desde = iso;
        hasta = iso;
      } else if (/\bhasta\b/.test(q) && CHAT_CONTEXT.desde) {
        desde = CHAT_CONTEXT.desde;
        hasta = iso;
      } else if (/\bdesde\b/.test(q) && CHAT_CONTEXT.hasta) {
        desde = iso;
        hasta = CHAT_CONTEXT.hasta;
      } else if (/\b(ahora|y ahora|despues)\b/.test(q) && CHAT_CONTEXT.desde) {
        desde = CHAT_CONTEXT.desde;
        hasta = iso;
      } else {
        desde = iso;
        hasta = intent === "value" ? iso : null;
      }
    } else if (parsed.years.length === 1) {
      ({ desde, hasta } = yearRange(parsed.years[0]));
      if (intent === "value") hasta = desde;
    } else if (/\b(ultimo|ultima|actual|mas reciente)\b/.test(q) && CHAT_DATES.length) {
      const last = CHAT_DATES[CHAT_DATES.length - 1].value;
      desde = last;
      hasta = last;
    } else if (CHAT_CONTEXT.desde || CHAT_CONTEXT.hasta) {
      desde = CHAT_CONTEXT.desde;
      hasta = CHAT_CONTEXT.hasta;
    }

    if (desde && hasta && desde > hasta) [desde, hasta] = [hasta, desde];
    return { desde, hasta, parsed };
  }

  function labelDate(iso) {
    if (!iso) return "—";
    if (typeof formatDateLabel === "function") return formatDateLabel(iso);
    return String(iso).slice(0, 7);
  }

  function formatNumber(value, decimals = 2) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "Sin dato";
    if (typeof toEsNumberString === "function") return toEsNumberString(value, decimals);
    return value.toLocaleString("es-AR", { maximumFractionDigits: decimals });
  }

  function appendMessage(role, html) {
    const thread = document.getElementById("chat_thread");
    if (!thread) return;
    const node = document.createElement("div");
    node.className = `chat-message ${role}`;
    node.innerHTML = role === "bot"
      ? `<div class="chat-avatar" aria-hidden="true">CyT</div><div class="chat-bubble">${html}</div>`
      : `<div class="chat-bubble">${html}</div>`;
    thread.appendChild(node);
    thread.scrollTop = thread.scrollHeight;
  }

  function appendChoices(prefix, choices, originalQuery) {
    const buttons = choices.map(s =>
      `<button type="button" class="chat-choice" data-series-id="${escapeHtml(s.id)}" data-original-query="${escapeHtml(originalQuery)}">${escapeHtml(s.name)}</button>`
    ).join("");
    appendMessage("bot", `${prefix}<div class="chat-choice-row">${buttons}</div>`);
  }

  function setBusy(isBusy) {
    CHAT_BUSY = isBusy;
    const btn = document.getElementById("chat_send");
    const input = document.getElementById("chat_input");
    if (btn) {
      btn.disabled = isBusy;
      btn.textContent = isBusy ? "Consultando..." : "Consultar";
    }
    if (input) input.disabled = isBusy;
  }

  function syncPanel(seriesIds, desde, hasta) {
    if (typeof _SELECTED_INDICES !== "undefined" && _SELECTED_INDICES?.clear) {
      _SELECTED_INDICES.clear();
      for (const id of seriesIds) _SELECTED_INDICES.add(id);
      if (typeof sincronizarSelectVisual === "function") sincronizarSelectVisual();
      if (typeof actualizarPanelIndicesElegidos === "function") actualizarPanelIndicesElegidos();
    }
    if (desde && typeof setPickValue === "function") setPickValue("desde", desde);
    if (hasta && typeof setPickValue === "function") setPickValue("hasta", hasta);
  }

  function updateContext(series, desde, hasta, intent) {
    if (series?.length) CHAT_CONTEXT.seriesIds = series.map(s => s.id);
    if (desde) CHAT_CONTEXT.desde = desde;
    if (hasta) CHAT_CONTEXT.hasta = hasta;
    if (intent) CHAT_CONTEXT.intent = intent;
  }

  function helpHtml() {
    return `
      <strong>Puedo consultar las series reales de la base.</strong><br>
      Algunos grupos: IPC nacional/Córdoba/San Luis/EE.UU.; ICC INDEC y Córdoba; IPIM y sus rubros; salarios y RIPTE; dólar BNA, A3500, minorista y libre; BADLAR, CER, UVA e ICL; IOP Córdoba; JUS/CPCE; RAC, VGA, KU y cánones de agua; FAM EPEC.<br>
      <span class="chat-muted">Ejemplos: “variación del IPIM químicos de dic-2025 a jul-2026”, “valor del dólar mayorista en agosto 2026”, “datos del IPC Córdoba durante 2025”.</span>`;
  }

  function explainMissing(item, desde, hasta) {
    const missing = Array.isArray(item.missing_points) ? item.missing_points : [];
    if (missing.includes("inicio") && missing.includes("fin")) return `faltan datos en ${labelDate(desde)} y ${labelDate(hasta)}`;
    if (missing.includes("inicio")) return `falta el dato inicial de ${labelDate(desde)}`;
    if (missing.includes("fin")) return `falta el dato final de ${labelDate(hasta)}`;
    if (item.reason === "initial_zero") return `el valor inicial de ${labelDate(desde)} es 0`;
    return "no existen dos puntas numéricas válidas para ese período";
  }

  async function runVariation(series, desde, hasta) {
    const params = `col_idxs=${encodeURIComponent(series.map(s => s.id).join(","))}&desde=${encodeURIComponent(desde)}&hasta=${encodeURIComponent(hasta)}`;
    const res = await api(`/api/variaciones?${params}`);
    const items = Array.isArray(res.data) ? res.data : [];

    if (items.length === 1) {
      const item = items[0];
      if (typeof item.variacion === "number" && Number.isFinite(item.variacion)) {
        return `<strong>${escapeHtml(item.serie)}</strong><br>
          ${labelDate(desde)}: <strong>${formatNumber(item.inicial)}</strong> · ${labelDate(hasta)}: <strong>${formatNumber(item.final)}</strong><br>
          Variación punta a punta: <strong>${formatNumber(item.variacion)}%</strong>
          <div class="chat-status-line"><span class="chat-status-dot"></span>Resultado calculado con datos de la API</div>`;
      }
      return `<strong>${escapeHtml(item.serie)}</strong><br>
        No se puede calcular la variación: <strong>${escapeHtml(explainMissing(item, desde, hasta))}</strong>.<br>
        ${labelDate(desde)}: ${formatNumber(item.inicial)} · ${labelDate(hasta)}: ${formatNumber(item.final)}`;
    }

    const rows = items.map(item => {
      const value = typeof item.variacion === "number" && Number.isFinite(item.variacion)
        ? `${formatNumber(item.variacion)}%`
        : `No calculable · ${escapeHtml(explainMissing(item, desde, hasta))}`;
      return `<tr><td>${escapeHtml(item.serie)}</td><td>${formatNumber(item.inicial)}</td><td>${formatNumber(item.final)}</td><td>${value}</td></tr>`;
    }).join("");
    return `<strong>Comparación ${labelDate(desde)} → ${labelDate(hasta)}</strong>
      <div class="chat-result-table-wrap"><table class="chat-result-table">
        <thead><tr><th>Serie</th><th>${labelDate(desde)}</th><th>${labelDate(hasta)}</th><th>Variación</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
  }

  async function runValue(series, dateIso) {
    const params = `col_idxs=${encodeURIComponent(series.map(s => s.id).join(","))}&desde=${encodeURIComponent(dateIso)}&hasta=${encodeURIComponent(dateIso)}`;
    const data = await api(`/api/data?${params}`);
    const row = Array.isArray(data.rows) ? data.rows[0] : null;
    if (!row) return `No encontré registros para ${labelDate(dateIso)}.`;

    const lines = series.map((s, index) => {
      const raw = row[index + 1];
      const numeric = typeof raw === "number" ? raw : Number(String(raw ?? "").replace(",", "."));
      const text = Number.isFinite(numeric) ? formatNumber(numeric) : (String(raw ?? "").trim() || "Sin dato");
      return `<strong>${escapeHtml(s.name)}</strong>: ${escapeHtml(text)}`;
    });
    return `${labelDate(dateIso)}<br>${lines.join("<br>")}<div class="chat-status-line"><span class="chat-status-dot"></span>Dato leído desde la API</div>`;
  }

  async function runTable(series, desde, hasta) {
    const params = `col_idxs=${encodeURIComponent(series.map(s => s.id).join(","))}&desde=${encodeURIComponent(desde)}&hasta=${encodeURIComponent(hasta)}`;
    const data = await api(`/api/data?${params}`);
    const headers = Array.isArray(data.headers) ? data.headers : [];
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const preview = rows.slice(0, 24);
    const th = headers.map(h => `<th>${escapeHtml(h)}</th>`).join("");
    const tr = preview.map(row => `<tr>${row.map((v, i) => {
      const n = typeof v === "number" ? v : Number(String(v ?? "").replace(",", "."));
      const txt = i > 0 && Number.isFinite(n) ? formatNumber(n) : String(v ?? "");
      return `<td>${escapeHtml(txt)}</td>`;
    }).join("")}</tr>`).join("");
    const suffix = rows.length > preview.length ? `<br><span class="chat-muted">Vista previa de ${preview.length} de ${rows.length} filas. La selección quedó aplicada al panel superior.</span>` : "";
    return `<strong>Datos ${labelDate(desde)} → ${labelDate(hasta)}</strong>
      <div class="chat-result-table-wrap"><table class="chat-result-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>${suffix}`;
  }

  async function processQuery(rawQuery, options = {}) {
    const query = String(rawQuery ?? "").trim();
    if (!query || CHAT_BUSY) return;
    if (!options.silentUser) appendMessage("user", escapeHtml(query));

    if (!CHAT_READY) {
      appendMessage("bot", "El catálogo todavía se está cargando desde la API. Abrí el módulo de Estadísticas y volvé a intentar en unos segundos.");
      return;
    }

    const queryNorm = normalizeText(query);
    const dateInfo = parseDateMentions(query);
    const intent = detectIntent(queryNorm, dateInfo.mentions.length);
    if (intent === "help") {
      appendMessage("bot", helpHtml());
      return;
    }

    const resolution = resolveSeries(query, options.forcedSeriesIds || []);
    if (resolution.ambiguous.length) {
      appendChoices("La consulta puede referirse a más de una serie. Elegí cuál querés usar:", resolution.ambiguous, query);
      return;
    }
    const series = resolution.series;
    if (!series.length) {
      appendMessage("bot", `No pude identificar con seguridad la serie. Probá usando una descripción más específica, por ejemplo <strong>“IPC Córdoba”</strong>, <strong>“IPC INDEC”</strong>, <strong>“dólar mayorista”</strong>, <strong>“IPIM químicos”</strong> o escribí <strong>“qué índices hay”</strong>.`);
      return;
    }

    const dates = resolveDates(query, intent);
    if (!dates.desde || !dates.hasta) {
      const available = CHAT_DATES.length ? `${labelDate(CHAT_DATES[0].value)} a ${labelDate(CHAT_DATES[CHAT_DATES.length - 1].value)}` : "la base cargada";
      appendMessage("bot", `Identifiqué <strong>${series.map(s => escapeHtml(s.name)).join(" · ")}</strong>, pero me falta el período. Indicame mes y año de inicio y fin. La base disponible abarca ${available}.`);
      return;
    }

    setBusy(true);
    try {
      syncPanel(series.map(s => s.id), dates.desde, dates.hasta);
      let html;
      if (intent === "table") html = await runTable(series, dates.desde, dates.hasta);
      else if (intent === "value") html = await runValue(series, dates.desde);
      else html = await runVariation(series, dates.desde, dates.hasta);
      appendMessage("bot", html);
      updateContext(series, dates.desde, dates.hasta, intent);
    } catch (error) {
      appendMessage("bot", `No pude completar la consulta. <strong>${escapeHtml(error?.message || "Error desconocido")}</strong>`);
    } finally {
      setBusy(false);
      document.getElementById("chat_input")?.focus();
    }
  }

  function setupChatUi() {
    const form = document.getElementById("chat_form");
    const input = document.getElementById("chat_input");
    if (!form || !input || form.dataset.ready === "1") return;
    form.dataset.ready = "1";

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) return;
      input.value = "";
      processQuery(value);
    });

    document.getElementById("chat_suggestions")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-chat-example]");
      if (!button) return;
      const value = button.dataset.chatExample || "";
      input.value = value;
      processQuery(value);
      input.value = "";
    });

    document.getElementById("chat_thread")?.addEventListener("click", (event) => {
      const button = event.target.closest(".chat-choice[data-series-id]");
      if (!button) return;
      const query = button.dataset.originalQuery || "";
      const id = button.dataset.seriesId;
      processQuery(query, { forcedSeriesIds: [id], silentUser: true });
    });
  }

  window.initStatsChatbotCatalog = function initStatsChatbotCatalog(series, dates) {
    CHAT_SERIES = (Array.isArray(series) ? series : [])
      .map(s => ({
        id: String(s.id ?? s.idx ?? s.name ?? ""),
        name: String(s.name ?? s.id ?? ""),
      }))
      .filter(isAllowedSeries)
      .map(s => ({ ...s, norm: normalizeText(s.name), tokens: meaningfulTokens(s.name) }));
    CHAT_DATES = Array.isArray(dates) ? [...dates] : [];
    CHAT_READY = CHAT_SERIES.length > 0 && CHAT_DATES.length > 0;
    setupChatUi();
  };

  document.addEventListener("DOMContentLoaded", setupChatUi);
})();
