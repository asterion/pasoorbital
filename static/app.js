"use strict";

/* ================================================================ estado */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const C_KM_S = 299792.458;
const STORAGE = "pasoorbital.cfg.v1";
const PAGE = 250;

const COMPASS_WORDS = ["norte", "noreste", "este", "sureste", "sur", "suroeste", "oeste", "noroeste"];

/* Glosario: se usa tanto en la ventana de ayuda como en los botones «?». */
const GLOSSARY = [
  { id: "aos", term: "AOS", sub: "inicio del paso", text: "Del inglés Acquisition of Signal. Es el momento en que el satélite asoma por el horizonte y empieza a poder escucharse. En la tabla esta columna se llama «Aparece»." },
  { id: "tca", term: "TCA", sub: "punto más alto", text: "Time of Closest Approach o culminación: el momento en que el satélite está más alto en el cielo. Suele ser el mejor momento para escucharlo, porque hay menos obstáculos y la señal es más fuerte. En el detalle aparece como «Punto más alto»." },
  { id: "los", term: "LOS", sub: "fin del paso", text: "Loss of Signal: el momento en que el satélite se oculta por el horizonte y deja de oírse. No tiene columna propia en la tabla: se obtiene sumando la hora de «Aparece» y la «Duración». En el detalle aparece como «Termina»." },
  { id: "paso", term: "Paso", sub: "pass", text: "El recorrido visible de un satélite desde tu ubicación, desde que aparece (AOS) hasta que desaparece (LOS). En órbita baja suele durar entre 3 y 12 minutos." },
  { id: "duracion", term: "Duración", sub: "tiempo visible", text: "Cuánto tiempo estará el satélite por encima del horizonte, desde que aparece hasta que se va. En órbita baja suele durar entre 3 y 12 minutos; los pasos más altos suelen durar más." },
  { id: "elevacion", term: "Elevación", sub: "altura", text: "La altura del satélite sobre el horizonte, en grados: 0° es el horizonte y 90° es justo encima de tu cabeza. Cuanto más alta, mejor señal y menos edificios o árboles de por medio." },
  { id: "azimut", term: "Azimut", sub: "dirección", text: "La dirección en el horizonte, en grados: 0° norte, 90° este, 180° sur, 270° oeste. Por ejemplo, 135° es sureste. En la tabla verás la dirección abreviada (S, NE…) y los grados debajo." },
  { id: "culminacion", term: "Culminación", sub: "máxima altura", text: "El punto más alto del paso. Coincide con el TCA y en el detalle aparece como «Punto más alto». Es el momento en que el satélite está más cerca del cenit y suele oírse mejor." },
  { id: "doppler", term: "Doppler", sub: "desvío de frecuencia", text: "El cambio aparente de frecuencia porque el satélite se acerca o se aleja. Al acercarse, la frecuencia sube; al alejarse, baja. En FM se nota poco; en SSB/CW hay que corregirlo a mano." },
  { id: "downlink", term: "Frecuencia de bajada", sub: "downlink", text: "La frecuencia en la que transmite el satélite. Es la que sintonizas para escucharlo. Si aparece «subida», es la frecuencia a la que tendrías que transmitir (solo con licencia y permiso)." },
  { id: "utc", term: "UTC", sub: "hora universal", text: "La hora de referencia mundial. La página usa por defecto la hora local de tu navegador; si activas «Mostrar en UTC», verás la hora universal, útil para comparar con otras fuentes." },
  { id: "tle", term: "TLE", sub: "datos de la órbita", text: "La ficha con los datos orbitales de un satélite, publicada por CelesTrak. Cuanto más reciente, mejor es la predicción. La página muestra la antigüedad de los TLE que está usando." },
  { id: "modos", term: "Modos de radio", sub: "FM, SSB, CW, APT, LRPT", text: "FM es voz y es lo más fácil de escuchar. SSB y CW son modos de radioaficionado, con señales más débiles y estrechas. APT es la imagen analógica de los NOAA; LRPT, la imagen digital de los Meteor." },
  { id: "polarizacion", term: "Polarización", sub: "orientación de la antena", text: "La orientación del campo de la señal. Si la antena no coincide, se pierde señal. Afecta sobre todo a las imágenes de satélites meteorológicos (APT/LRPT); en FM es menos crítica." },
  { id: "sdr", term: "SDR", sub: "radio por software", text: "Un receptor de radio que se conecta al computador (por ejemplo, un RTL-SDR) y procesa la señal con software. Es el equipo que asumen los comandos de escucha de esta página." },
  { id: "envivo", term: "Paso en curso", sub: "ya visible", text: "El satélite ya estaba sobre el horizonte cuando calculaste la predicción. La hora real de aparición fue antes; la que ves es el inicio de la ventana consultada." },
];

const state = {
  cfg: {
    lat: null,
    lon: null,
    alt: 0,
    label: "",
    days: 2,
    minEl: 5,
    groups: ["stations", "weather", "amateur"],
    onlyFreq: true,
  },
  utc: false,
  groups: [],
  catalog: [],
  byNorad: new Map(),
  passes: [],
  meta: null,
  shown: PAGE,
  busy: false,
  calculated: false,
  detail: null,
  nextPass: null,
  toastTimer: null,
};

let FMT = null;
let DATE_KEY = null;

/* ============================================================ utilidades */

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function buildFormatters() {
  const tz = state.utc ? "UTC" : undefined;
  const mk = (opts) => new Intl.DateTimeFormat("es-ES", { timeZone: tz, hour12: false, ...opts });
  FMT = {
    time: mk({ hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    hm: mk({ hour: "2-digit", minute: "2-digit" }),
    rel: mk({ weekday: "long", day: "2-digit", month: "short" }),
    full: mk({ day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }),
  };
  DATE_KEY = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const dateOf = (ts) => new Date(ts * 1000);
const dateKey = (ts) => DATE_KEY.format(dateOf(ts));
const fmtTime = (ts) => FMT.time.format(dateOf(ts));
const fmtHM = (ts) => FMT.hm.format(dateOf(ts));

/* «hoy», «mañana» o «Lunes 19 oct» para la fecha de aparición. */
function relativeDay(ts) {
  const now = Date.now() / 1000;
  const key = dateKey(ts);
  if (key === dateKey(now)) return "hoy";
  if (key === dateKey(now + 86400)) return "mañana";
  return capitalize(FMT.rel.format(dateOf(ts)).replace(",", ""));
}

function fmtFreq(hz) {
  if (!hz) return "—";
  let s = (hz / 1e6).toFixed(4);
  if (s.endsWith("00")) s = s.slice(0, -1);
  return s + " MHz";
}

function fmtDop(hz) {
  if (hz === null || hz === undefined) return "—";
  const k = hz / 1000;
  if (Math.abs(k) < 0.05) return "0.0 kHz";
  const sign = k > 0 ? "+" : "−";
  return `${sign}${Math.abs(k).toFixed(1)} kHz`;
}

function fmtDur(seconds) {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return "< 1 min";
  const mins = Math.round(total / 60);
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

const compassIndex = (deg) => Math.round((((deg % 360) + 360) % 360) / 45) % 8;
const compassWord = (deg) => COMPASS_WORDS[compassIndex(deg)];
const fmtAz = (deg) => `${capitalize(compassWord(deg))} · ${Math.round(deg)}°`;

function fmtAge(seconds) {
  if (seconds < 3600) return `hace ${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 48 * 3600) return `hace ${Math.round(seconds / 3600)} h`;
  return `hace ${Math.round(seconds / 86400)} d`;
}

function fmtCountdown(ms) {
  const s = Math.round(ms / 1000);
  if (s <= 0) return "ahora";
  if (s < 60) return `en ${s} s`;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m < 60) return `en ${m} min ${String(sec).padStart(2, "0")} s`;
  const h = Math.floor(m / 60);
  return `en ${h} h ${String(m % 60).padStart(2, "0")} min`;
}

function toast(message, bad = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("bad", !!bad);
  el.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (err) {
    throw new Error("No se pudo conectar con el servidor local. ¿Sigue en marcha?");
  }
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (err) {
    /* respuesta no JSON */
  }
  if (!res.ok) {
    throw new Error((data && data.error) || `Error ${res.status}`);
  }
  return data;
}

/* =============================================================== inicial */

document.addEventListener("DOMContentLoaded", init);

async function init() {
  loadCfg();
  buildFormatters();
  fillForm();
  bindEvents();
  initHelp();
  updateClock();
  setInterval(updateClock, 1000);
  setInterval(renderNext, 1000);
  await loadCatalog(false);
  if (state.cfg.lat !== null && state.cfg.lon !== null) {
    calculate();
  }
}

function loadCfg() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE) || "null");
    if (raw && typeof raw === "object") {
      state.cfg = { ...state.cfg, ...raw, groups: Array.isArray(raw.groups) && raw.groups.length ? raw.groups : state.cfg.groups };
    }
  } catch (err) {
    /* configuración corrupta: se ignora */
  }
}

function saveCfg() {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(state.cfg));
  } catch (err) {
    /* sin almacenamiento */
  }
}

function fillForm() {
  $("#lat").value = state.cfg.lat ?? "";
  $("#lon").value = state.cfg.lon ?? "";
  $("#alt").value = state.cfg.alt ?? 0;
  $("#days").value = String(state.cfg.days);
  $("#min-el").value = String(state.cfg.minEl);
  $("#only-freq").checked = !!state.cfg.onlyFreq;
  $("#utc").checked = state.utc;
  updateLocLabel();
  updateTzChip();
}

function updateLocLabel() {
  const el = $("#loc-label");
  if (state.cfg.lat === null || state.cfg.lon === null) {
    el.textContent = "Sin ubicación: busca una dirección o usa tu posición.";
    el.classList.remove("warn");
    return;
  }
  const coords = `${Number(state.cfg.lat).toFixed(4)}, ${Number(state.cfg.lon).toFixed(4)}`;
  el.textContent = state.cfg.label ? `${state.cfg.label} · ${coords}` : coords;
  el.classList.remove("warn");
}

function updateTzChip() {
  const zone = state.utc ? "UTC" : Intl.DateTimeFormat().resolvedOptions().timeZone || "local";
  $("#tz-chip").textContent = `Hora: ${zone}`;
}

function updateClock() {
  const el = $("#now-clock");
  if (el) el.textContent = `Ahora: ${FMT.full.format(new Date())}`;
}

/* =============================================================== eventos */

function bindEvents() {
  $("#search-address").addEventListener("click", geocode);
  $("#address").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      geocode();
    }
  });
  $("#geo-btn").addEventListener("click", useMyLocation);
  $("#calc").addEventListener("click", calculate);
  $("#refresh-tle").addEventListener("click", () => loadCatalog(true));
  $("#filter").addEventListener("input", () => {
    state.shown = PAGE;
    renderTable();
  });
  $("#only-freq").addEventListener("change", (ev) => {
    state.cfg.onlyFreq = ev.target.checked;
    saveCfg();
    state.shown = PAGE;
    renderTable();
  });
  $("#utc").addEventListener("change", (ev) => {
    state.utc = ev.target.checked;
    buildFormatters();
    updateTzChip();
    updateClock();
    renderTable();
    renderNext();
  });
  $("#more").addEventListener("click", () => {
    state.shown += PAGE;
    renderTable();
  });
  $("#ics").addEventListener("click", () => exportIcs());
  $("#next-card").addEventListener("click", () => {
    if (state.nextPass) openDetail(state.nextPass);
  });
  $$("#modal [data-close]").forEach((el) => el.addEventListener("click", () => showModal(false)));
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (!$("#glossary").hidden) closeGlossary();
    else showModal(false);
  });
}

/* ============================================================= catálogo */

async function loadCatalog(force) {
  const chip = $("#tle-chip");
  const button = $("#refresh-tle");
  chip.textContent = force ? "TLE: actualizando…" : "TLE: cargando…";
  chip.className = "chip";
  button.classList.add("spin");
  try {
    const data = await api(`/api/catalog${force ? "?refresh=1" : ""}`);
    state.catalog = data.satellites || [];
    state.groups = data.groups || [];
    state.byNorad = new Map(state.catalog.map((s) => [s.norad, s]));
    renderGroups();
    renderTleChip();
    if (force && state.cfg.lat !== null && state.cfg.lon !== null) {
      calculate();
    }
  } catch (err) {
    chip.textContent = "TLE: sin datos";
    chip.className = "chip bad";
    showError(err.message);
  } finally {
    button.classList.remove("spin");
  }
}

function renderGroups() {
  const box = $("#groups");
  box.replaceChildren();
  const available = state.groups.map((g) => g.id);
  const selected = state.cfg.groups.filter((g) => available.includes(g));
  if (!selected.length) state.cfg.groups = available.filter((g) => ["stations", "weather", "amateur"].includes(g));

  for (const group of state.groups) {
    const label = document.createElement("label");
    label.className = "check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = group.id;
    input.checked = state.cfg.groups.includes(group.id);
    input.addEventListener("change", () => {
      state.cfg.groups = selectedGroups();
      saveCfg();
    });
    const name = document.createElement("span");
    name.textContent = group.label;
    const count = document.createElement("span");
    count.className = "count";
    if (group.error && !group.count) {
      count.textContent = "sin datos";
      count.classList.add("warn");
    } else {
      count.textContent = `${group.count}${group.stale ? " · caché" : ""}`;
    }
    label.append(input, name, count);
    box.append(label);
  }
}

function selectedGroups() {
  return $$("#groups input:checked").map((input) => input.value);
}

function renderTleChip() {
  const chip = $("#tle-chip");
  const fetched = state.groups.map((g) => g.fetched_at).filter(Boolean);
  if (!fetched.length) {
    chip.textContent = "TLE: sin datos";
    chip.className = "chip bad";
    return;
  }
  const oldest = Math.min(...fetched);
  const age = Date.now() / 1000 - oldest;
  const stale = state.groups.some((g) => g.stale);
  const old = age > 7 * 86400;
  chip.textContent = `TLE: ${fmtAge(age)}${stale ? " · caché" : ""}`;
  chip.className = "chip" + (stale || old ? " warn" : "");
  chip.title = state.groups
    .map((g) => `${g.label}: ${g.count} satélites${g.error ? ` (${g.error})` : ""}`)
    .join("\n");
}

/* ========================================================== geocodificar */

async function geocode() {
  const query = $("#address").value.trim();
  if (query.length < 3) {
    toast("Escribe una dirección más completa.", true);
    return;
  }
  const list = $("#geo-results");
  list.hidden = true;
  list.replaceChildren();
  try {
    const data = await api(`/api/geocode?q=${encodeURIComponent(query)}`);
    if (!data.results || !data.results.length) {
      toast("No he encontrado esa dirección. Prueba con más detalle.", true);
      return;
    }
    for (const result of data.results) {
      const li = document.createElement("li");
      li.tabIndex = 0;
      const label = document.createElement("span");
      label.textContent = result.name;
      const coords = document.createElement("span");
      coords.className = "geo-coords";
      coords.textContent = `${result.lat.toFixed(4)}, ${result.lon.toFixed(4)}`;
      li.append(label, coords);
      const choose = () => {
        setLocation(result.lat, result.lon, result.name);
        list.hidden = true;
        calculate();
      };
      li.addEventListener("click", choose);
      li.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") choose();
      });
      list.append(li);
    }
    list.hidden = false;
  } catch (err) {
    toast(err.message, true);
  }
}

function setLocation(lat, lon, label) {
  state.cfg.lat = Number(lat);
  state.cfg.lon = Number(lon);
  state.cfg.label = label || "";
  $("#lat").value = state.cfg.lat.toFixed(4);
  $("#lon").value = state.cfg.lon.toFixed(4);
  saveCfg();
  updateLocLabel();
}

function useMyLocation() {
  if (!navigator.geolocation) {
    toast("Tu navegador no permite geolocalización.", true);
    return;
  }
  toast("Obteniendo tu posición…");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      setLocation(pos.coords.latitude, pos.coords.longitude, "Mi ubicación");
      calculate();
    },
    () => toast("No se pudo obtener la posición. Revisa los permisos.", true),
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
  );
}

/* ============================================================== calcular */

async function calculate() {
  if (state.busy) return;

  const lat = Number.parseFloat($("#lat").value);
  const lon = Number.parseFloat($("#lon").value);
  if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
    toast("Latitud no válida.", true);
    return;
  }
  if (!Number.isFinite(lon) || lon < -180 || lon > 180) {
    toast("Longitud no válida.", true);
    return;
  }
  const groups = selectedGroups();
  if (!groups.length) {
    toast("Selecciona al menos un grupo de satélites.", true);
    return;
  }

  state.cfg.lat = lat;
  state.cfg.lon = lon;
  state.cfg.alt = Number.parseFloat($("#alt").value) || 0;
  state.cfg.days = Number($("#days").value);
  state.cfg.minEl = Number($("#min-el").value);
  state.cfg.groups = groups;
  state.cfg.onlyFreq = $("#only-freq").checked;
  saveCfg();
  updateLocLabel();

  setBusy(true);
  hideError();
  try {
    const data = await api("/api/passes", {
      method: "POST",
      body: JSON.stringify({
        lat: state.cfg.lat,
        lon: state.cfg.lon,
        alt_m: state.cfg.alt,
        days: state.cfg.days,
        min_el: state.cfg.minEl,
        groups,
        start: "now",
      }),
    });
    state.passes = data.passes || [];
    state.meta = data.meta || null;
    state.calculated = true;
    state.shown = PAGE;
    $("#calc-hint").textContent = `Calculado en ${state.meta.elapsed_s} s · ${state.meta.satellites} satélites.`;
    renderTable();
    renderNext();
    renderTleChip();
    $("#ics").disabled = state.passes.length === 0;
  } catch (err) {
    showError(err.message);
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  state.busy = busy;
  const button = $("#calc");
  button.disabled = busy;
  button.textContent = busy ? "Calculando…" : "Calcular pasos";
  if (busy) $("#calc-hint").textContent = "Calculando órbitas… puede tardar unos segundos.";
}

function showError(message) {
  const box = $("#error");
  box.textContent = message;
  box.hidden = false;
}

function hideError() {
  $("#error").hidden = true;
}

/* ================================================================ tabla */

function filteredPasses() {
  const query = $("#filter").value.trim().toLowerCase();
  return state.passes.filter((p) => {
    if (state.cfg.onlyFreq && !p.freq_hz) return false;
    if (query && !p.name.toLowerCase().includes(query)) return false;
    return true;
  });
}

const elClass = (el) => (el >= 30 ? "el-hi" : el >= 15 ? "el-mid" : "el-lo");

function renderTable() {
  const list = filteredPasses();
  const body = $("#pass-body");
  const now = Date.now() / 1000;
  const visible = list.slice(0, state.shown);
  const frag = document.createDocumentFragment();

  for (const p of visible) {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    const live = now >= p.aos_ts && now <= p.los_ts;
    if (live) tr.classList.add("live");

    const tdSat = document.createElement("td");
    const name = document.createElement("span");
    name.className = "sat-name";
    name.textContent = p.name;
    const sub = document.createElement("span");
    sub.className = "sat-sub";
    sub.textContent = `NORAD ${p.norad}`;
    if (live) {
      const tag = document.createElement("span");
      tag.className = "live-tag";
      tag.textContent = "en curso";
      sub.append(" ", tag);
    }
    tdSat.append(name, sub);

    const tdAos = document.createElement("td");
    tdAos.className = "time";
    tdAos.innerHTML = `${fmtTime(p.aos_ts)}<span class="date-sub">${relativeDay(p.aos_ts)}</span>`;

    const tdDur = document.createElement("td");
    tdDur.className = "num-col muted";
    tdDur.textContent = fmtDur(p.duration_s);

    const tdEl = document.createElement("td");
    tdEl.className = "num-col";
    const badge = document.createElement("span");
    badge.className = `el-badge ${elClass(p.max_el)}`;
    badge.textContent = `${p.max_el.toFixed(0)}°`;
    tdEl.append(badge);

    const tdAz = document.createElement("td");
    tdAz.className = "az-col";
    tdAz.innerHTML =
      `<span class="az-dir">${capitalize(compassWord(p.az_aos))} → ${capitalize(compassWord(p.az_los))}</span>` +
      `<span class="date-sub">${Math.round(p.az_aos)}° → ${Math.round(p.az_los)}°</span>`;

    const tdFreq = document.createElement("td");
    if (p.freq_hz) {
      tdFreq.className = "freq";
      tdFreq.innerHTML = `${fmtFreq(p.freq_hz)}<small>${esc(p.label || p.mode || "")}</small>`;
    } else {
      tdFreq.className = "muted";
      tdFreq.textContent = "—";
    }

    const tdDop = document.createElement("td");
    tdDop.className = "num-col";
    if (p.doppler_max_hz !== null && p.doppler_max_hz !== undefined) {
      const span = document.createElement("span");
      span.className = "dop";
      span.textContent = `±${(p.doppler_max_hz / 1000).toFixed(1)} kHz`;
      tdDop.append(span);
    } else {
      tdDop.textContent = "—";
    }

    tr.append(tdSat, tdAos, tdDur, tdEl, tdAz, tdFreq, tdDop);
    tr.addEventListener("click", () => openDetail(p));
    tr.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        openDetail(p);
      }
    });
    frag.append(tr);
  }
  body.replaceChildren(frag);

  const meta = state.meta;
  if (meta) {
    const suffix =
      list.length === state.passes.length
        ? `${state.passes.length} pasos · ${meta.satellites} satélites`
        : `${list.length} de ${state.passes.length} pasos (filtrado)`;
    const extra = meta.truncated ? " · resultados truncados" : "";
    const tleAge = meta.tle_oldest_refresh ? ` · TLE ${fmtAge(Date.now() / 1000 - meta.tle_oldest_refresh)}` : "";
    $("#pass-meta").textContent = `${suffix} · calculado en ${meta.elapsed_s} s${tleAge}${extra}`;
  }

  const more = $("#more");
  if (list.length > visible.length) {
    more.hidden = false;
    more.textContent = `Mostrar más (${list.length - visible.length} restantes)`;
  } else {
    more.hidden = true;
  }

  const has = list.length > 0;
  $("#table-wrap").hidden = !has;
  $("#empty").hidden = has;
  if (!has && state.calculated) {
    $("#empty h3").textContent = "Ningún paso coincide";
    $("#empty p").textContent =
      state.passes.length > 0
        ? "Prueba a quitar el filtro o a marcar «Solo satélites con frecuencia conocida»."
        : "No hay pasos por encima de la elevación mínima en este periodo.";
  }
}

/* =============================================================== próximo */

function renderNext() {
  const card = $("#next-card");
  if (!state.passes.length) {
    card.hidden = true;
    return;
  }
  const now = Date.now() / 1000;
  const next = filteredPasses().find((p) => p.los_ts > now);
  if (!next) {
    card.hidden = true;
    state.nextPass = null;
    return;
  }
  card.hidden = false;
  state.nextPass = next;

  const live = now >= next.aos_ts;
  const label = live ? "Ahora mismo" : fmtCountdown((next.aos_ts - now) * 1000);
  const detail = live ? `quedan ${fmtDur(Math.max(0, next.los_ts - now))}` : `Aparece ${fmtTime(next.aos_ts)}`;
  const body = $("#next-body");
  body.innerHTML =
    `<p class="next-name">${esc(next.name)}</p>` +
    `<p class="next-sub">${next.freq_hz ? fmtFreq(next.freq_hz) + " · " + esc(next.mode || "") : "sin frecuencia registrada"}</p>` +
    `<div class="countdown">${esc(label)}</div>` +
    `<div class="next-meta">` +
    `<span class="pill">${detail}</span>` +
    `<span class="pill">Altura máx. ${next.max_el.toFixed(0)}°</span>` +
    `<span class="pill amber">Dirección ${fmtAz(next.az_tca)}</span>` +
    `</div>`;
}

/* =================================================================== ayuda */

function initHelp() {
  buildGlossary();
  const panel = $("#help-panel");
  const hidePanel = () => {
    panel.hidden = true;
    try {
      localStorage.setItem("pasoorbital.helpSeen", "1");
    } catch (err) {
      /* almacenamiento bloqueado */
    }
  };
  $("#help-btn").addEventListener("click", () => openGlossary());
  $("#help-glossary").addEventListener("click", () => openGlossary());
  $("#help-ok").addEventListener("click", hidePanel);
  $("#help-close").addEventListener("click", hidePanel);
  $("#help-toggle").addEventListener("click", () => {
    panel.hidden = !panel.hidden;
  });
  $$("#glossary [data-glossary-close]").forEach((el) => el.addEventListener("click", closeGlossary));
  document.addEventListener("click", (ev) => {
    const dot = ev.target.closest("[data-term]");
    if (!dot) return;
    ev.preventDefault();
    ev.stopPropagation();
    openGlossary(dot.dataset.term);
  });
  let seen = false;
  try {
    seen = !!localStorage.getItem("pasoorbital.helpSeen");
  } catch (err) {
    seen = false;
  }
  if (!seen) panel.hidden = false;
}

function buildGlossary() {
  const box = $("#glossary-body");
  if (!box || box.childElementCount) return;
  box.innerHTML = GLOSSARY.map(
    (g) =>
      `<div class="gloss-item" id="gloss-${g.id}">
        <h4>${esc(g.term)}<span>${esc(g.sub || "")}</span></h4>
        <p>${esc(g.text)}</p>
      </div>`
  ).join("");
}

function openGlossary(term) {
  const box = $("#glossary");
  if (!box) return;
  box.hidden = false;
  document.body.style.overflow = "hidden";
  $$(".gloss-item").forEach((el) => el.classList.remove("flash"));
  if (term) {
    const item = document.getElementById(`gloss-${term}`);
    if (item) {
      item.scrollIntoView({ block: "center" });
      item.classList.add("flash");
      setTimeout(() => item.classList.remove("flash"), 2600);
    }
  } else {
    const card = $(".glossary-card");
    if (card) card.scrollTop = 0;
  }
}

function closeGlossary() {
  $("#glossary").hidden = true;
  if ($("#modal").hidden) document.body.style.overflow = "";
}

/* Resumen en lenguaje llano que se muestra al abrir un paso. */
function passSummary(p) {
  const dirA = compassWord(p.az_aos);
  const dirL = compassWord(p.az_los);
  const el = p.max_el.toFixed(0);

  const freq = p.freq_hz
    ? `Podrás escucharlo en <strong>${fmtFreq(p.freq_hz)}</strong>${p.mode ? ` (${esc(p.mode)})` : ""}.`
    : "No hay una frecuencia de escucha registrada para este satélite.";

  let text;
  if (p.partial_start) {
    text =
      `El <strong>${esc(p.name)}</strong> ya está en curso: ahora va por el <strong>${dirA}</strong>, ` +
      `llegará a <strong>${el}°</strong> de altura a las <strong>${fmtTime(p.tca_ts)}</strong> y ` +
      `desaparecerá por el <strong>${dirL}</strong> a las <strong>${fmtTime(p.los_ts)}</strong>.`;
  } else if (p.partial_end) {
    text =
      `El <strong>${esc(p.name)}</strong> aparecerá por el <strong>${dirA}</strong> a las ` +
      `<strong>${fmtTime(p.aos_ts)}</strong> y llegará a <strong>${el}°</strong> de altura a las ` +
      `<strong>${fmtTime(p.tca_ts)}</strong>. Seguirá visible al menos hasta el final de la ventana ` +
      `(${fmtTime(p.los_ts)}).`;
  } else {
    const quality = p.max_el >= 30 ? "un paso alto" : p.max_el >= 15 ? "un paso aceptable" : "un paso bajo";
    text =
      `El <strong>${esc(p.name)}</strong> aparecerá por el <strong>${dirA}</strong> a las ` +
      `<strong>${fmtTime(p.aos_ts)}</strong>, subirá hasta <strong>${el}°</strong> de altura ` +
      `(${quality}) a las <strong>${fmtTime(p.tca_ts)}</strong> y desaparecerá por el ` +
      `<strong>${dirL}</strong> a las <strong>${fmtTime(p.los_ts)}</strong>. ` +
      `Dura unos <strong>${fmtDur(p.duration_s)}</strong>.`;
  }

  let dop = "";
  if (p.freq_hz && p.doppler_aos_hz !== null && p.doppler_los_hz !== null) {
    if (Math.abs(p.doppler_aos_hz) < 50 && Math.abs(p.doppler_los_hz) < 50) {
      dop = " El Doppler será casi nulo.";
    } else {
      dop = ` Al empezar, la frecuencia estará ${fmtDop(p.doppler_aos_hz)} respecto a la nominal; al final, ${fmtDop(p.doppler_los_hz)}.`;
    }
  }
  return `${text} ${freq}${dop}`;
}

/* ================================================================= modal */

function showModal(show) {
  const modal = $("#modal");
  modal.hidden = !show;
  document.body.style.overflow = show ? "hidden" : "";
  if (!show) {
    state.detail = null;
    $("#modal-body").replaceChildren();
  }
}

async function openDetail(p) {
  const entry = state.byNorad.get(p.norad) || null;
  state.detail = { pass: p, entry };
  showModal(true);
  $("#modal-body").innerHTML = `<p class="hint">Cargando trayectoria…</p>`;

  const observer = (state.meta && state.meta.observer) || {
    lat: state.cfg.lat,
    lon: state.cfg.lon,
    alt_m: state.cfg.alt,
  };
  try {
    const track = await api("/api/track", {
      method: "POST",
      body: JSON.stringify({
        norad: p.norad,
        lat: observer.lat,
        lon: observer.lon,
        alt_m: observer.alt_m,
        aos: p.aos,
        los: p.los,
      }),
    });
    if (!state.detail || state.detail.pass !== p) return;
    renderDetail(p, entry, track);
  } catch (err) {
    $("#modal-body").innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

function renderDetail(p, entry, track) {
  const channels = (entry && entry.channels) || [];
  const primary = channels[0] || null;
  const freq = primary ? primary.freq_hz : null;
  const shift = (rate) => (freq ? (-rate / C_KM_S) * freq : null);

  const orbit = entry
    ? `órbita de ${entry.alt_km.toFixed(0)} km · inclinación ${entry.incl_deg.toFixed(1)}° · TLE ${entry.tle_age_days.toFixed(1)} d`
    : `NORAD ${p.norad}`;

  const quando = state.utc ? "UTC" : `hora local (${Intl.DateTimeFormat().resolvedOptions().timeZone})`;

  const aosLabel = p.partial_start ? "Ya en curso" : "Aparece";
  const losLabel = p.partial_end ? "Fin de la ventana" : "Termina";
  const partialNote = p.partial_start
    ? `<p class="hint">El satélite ya estaba visible al calcular la predicción: la hora real de aparición es anterior a la que se muestra.</p>`
    : "";

  const stats = `
    <div class="stat"><div class="k">${aosLabel}</div><div class="v">${fmtTime(p.aos_ts)}</div><div class="v"><small>${relativeDay(p.aos_ts)}</small></div></div>
    <div class="stat"><div class="k">Punto más alto</div><div class="v">${fmtTime(p.tca_ts)}</div><div class="v"><small>${relativeDay(p.tca_ts)}</small></div></div>
    <div class="stat"><div class="k">${losLabel}</div><div class="v">${fmtTime(p.los_ts)}</div><div class="v"><small>${relativeDay(p.los_ts)}</small></div></div>
    <div class="stat"><div class="k">Duración</div><div class="v">${fmtDur(p.duration_s)}</div></div>
    <div class="stat"><div class="k">Altura máxima</div><div class="v">${p.max_el.toFixed(1)}°</div></div>
    <div class="stat"><div class="k">Dirección (entrada → salida)</div><div class="v">${capitalize(compassWord(p.az_aos))} → ${capitalize(compassWord(p.az_los))}</div><div class="v"><small>${Math.round(p.az_aos)}° → ${Math.round(p.az_los)}°</small></div></div>
    <div class="stat"><div class="k">Distancia en el punto más alto</div><div class="v">${p.range_tca.toFixed(0)} <small>km</small></div></div>
    <div class="stat"><div class="k">TLE</div><div class="v">${p.tle_age_days.toFixed(1)} <small>días</small></div></div>`;

  let channelsHtml;
  if (channels.length) {
    channelsHtml = `<div class="channels">${channels
      .map(
        (ch) => `
        <div class="channel">
          <div class="ch-main">${fmtFreq(ch.freq_hz)}</div>
          <div class="ch-mode">${esc(ch.mode || "")}</div>
          <div class="ch-label">${esc(ch.label || "Frecuencia de escucha")}</div>
          ${ch.note ? `<div class="ch-note">${esc(ch.note)}</div>` : ""}
          ${
            ch.uplink_hz && !(ch.note && /subida|uplink/i.test(ch.note))
              ? `<div class="ch-note">Subida: ${fmtFreq(ch.uplink_hz)}${ch.tone_hz ? ` · tono ${ch.tone_hz} Hz` : ""}</div>`
              : ""
          }
        </div>`
      )
      .join("")}</div>`;
  } else {
    channelsHtml = `<p class="hint">Sin frecuencia registrada para este satélite. Puedes añadirla en <code>data/frequencies.json</code> (por NORAD).</p>`;
  }

  let dopplerHtml = "";
  if (freq) {
    const dAos = shift(p.rate_aos);
    const dLos = shift(p.rate_los);
    const dTca = shift(p.rate_tca);
    const dAosLabel = p.partial_start ? "Al empezar (ya visible)" : "Al aparecer (se acerca)";
    const dLosLabel = p.partial_end ? "Al final (ventana)" : "Al irse (se aleja)";
    dopplerHtml = `
      <div class="stat-grid">
        <div class="stat"><div class="k">${dAosLabel}</div><div class="v">${fmtFreq(freq + dAos)}</div><div class="v"><small>${fmtDop(dAos)} respecto a ${fmtFreq(freq)}</small></div></div>
        <div class="stat"><div class="k">En el punto más alto</div><div class="v">${fmtFreq(freq + dTca)}</div><div class="v"><small>${fmtDop(dTca)}</small></div></div>
        <div class="stat"><div class="k">${dLosLabel}</div><div class="v">${fmtFreq(freq + dLos)}</div><div class="v"><small>${fmtDop(dLos)}</small></div></div>
      </div>
      <p class="hint">Sintoniza la frecuencia nominal y corrige a mano: al principio el satélite se acerca (frecuencia más alta), al final se aleja (más baja). El desplazamiento máximo es de ±${(Math.abs((-p.rate_max / C_KM_S) * freq) / 1000).toFixed(1)} kHz.</p>`;
  }

  const commands = channels.map((ch) => commandFor(ch, p));
  const commandsHtml = channels.length
    ? `<div class="cmds">${commands
        .map(
          (cmd, i) =>
            `<div class="cmd"><pre>${esc(cmd)}</pre><button class="copy" type="button" data-i="${i}">Copiar</button></div>`
        )
        .join("")}</div>
       <p class="hint">Requiere un RTL-SDR (u otro SDR) y <code>sox</code>; para APT/LRPT, además <code>noaa-apt</code> o <code>SatDump</code>. En SatDump el primer argumento es el <strong>pipeline</strong> (<code>meteor_m2-x_lrpt</code>; si no existe, prueba <code>meteor_m2_lrpt</code>) y el segundo la carpeta de salida; en versiones 2.x puede que tengas que usar <code>satdump legacy live</code>. Ajusta la ganancia y el dispositivo.</p>`
    : "";

  $("#modal-body").innerHTML = `
    <div class="modal-head">
      <div>
        <h2 id="modal-title">${esc(p.name)}</h2>
        <div class="sub">NORAD ${p.norad} · ${esc(orbit)}</div>
      </div>
      <div class="pills">
        <span class="pill">Altura máx. ${p.max_el.toFixed(0)}°</span>
        ${freq ? `<span class="pill amber">${fmtFreq(freq)}</span>` : ""}
        ${p.partial_start ? `<span class="pill amber">paso en curso</span>` : ""}
      </div>
    </div>

    <p class="summary">${passSummary(p)}</p>

    <div class="section">
      <h3>Horario · ${esc(quando)}</h3>
      <div class="stat-grid">${stats}</div>
      ${partialNote}
      <p class="hint">Altura = grados sobre el horizonte (90° es justo encima) · Dirección = por dónde aparece y por dónde se va · Duración = tiempo visible.</p>
    </div>

    ${dopplerHtml ? `<div class="section"><h3>Doppler</h3>${dopplerHtml}</div>` : ""}

    <div class="section">
      <h3>Frecuencias</h3>
      ${channelsHtml}
    </div>

    <div class="section">
      <h3>Trayectoria en el cielo</h3>
      <p class="hint">El centro del círculo es justo encima de ti (cenit) y el borde es el horizonte. Arriba está el norte y a la derecha el este.</p>
      <div class="plots">
        <div class="plot-box">${polarSvg(track.points, p)}<div class="legend"><span><i style="background:var(--accent)"></i>Aparece</span><span><i style="background:var(--accent-2)"></i>Punto más alto</span><span><i style="background:var(--danger)"></i>Termina</span></div></div>
        <div class="plot-box">${chartSvg(track.points, p, freq)}<div class="legend"><span><i style="background:var(--accent)"></i>Elevación</span><span><i style="background:var(--accent-2)"></i>Doppler</span></div></div>
      </div>
    </div>

    ${commandsHtml ? `<div class="section"><h3>Comandos de escucha</h3>${commandsHtml}</div>` : ""}

    <div class="section">
      <button class="btn ghost" type="button" id="ics-one">Añadir este paso al calendario</button>
    </div>`;

  $$("#modal-body .copy").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cmd = commands[Number(btn.dataset.i)];
      copyText(cmd);
    });
  });
  const icsOne = $("#ics-one");
  if (icsOne) icsOne.addEventListener("click", () => exportIcs([p]));

}

/* =============================================================== gráficos */

function polarSvg(points, pass) {
  const S = 320;
  const c = S / 2;
  const R = 126;
  const ring = (el) => R * (1 - el / 90);

  const grid = [0, 30, 60, 90]
    .map(
      (el) =>
        `<circle cx="${c}" cy="${c}" r="${ring(el).toFixed(1)}" fill="none" stroke="#1d2a3a" stroke-width="1"/>`
    )
    .join("");
  const spokes = [0, 90, 180, 270]
    .map((a) => {
      const rad = (a * Math.PI) / 180;
      return `<line x1="${c}" y1="${c}" x2="${(c + R * Math.sin(rad)).toFixed(1)}" y2="${(c - R * Math.cos(rad)).toFixed(1)}" stroke="#16202e" stroke-width="1"/>`;
    })
    .join("");

  const pts = [];
  for (let i = 0; i < points.az.length; i++) {
    const az = points.az[i];
    const el = points.el[i];
    if (az === null || el === null || el < 0) continue;
    const r = ring(el);
    const rad = (az * Math.PI) / 180;
    pts.push([c + r * Math.sin(rad), c - r * Math.cos(rad)]);
  }
  const path = pts.length
    ? `M ${pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L ")}`
    : "";

  const dot = (x, y, color) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.5" fill="${color}" stroke="#0b1017" stroke-width="1.5"/>`;
  const first = pts[0];
  const last = pts[pts.length - 1];

  const tca = (() => {
    let best = -1;
    let idx = 0;
    for (let i = 0; i < points.el.length; i++) {
      if (points.el[i] !== null && points.el[i] > best) {
        best = points.el[i];
        idx = i;
      }
    }
    const az = points.az[idx];
    const el = points.el[idx];
    if (az === null || el === null) return null;
    const r = ring(el);
    const rad = (az * Math.PI) / 180;
    return [c + r * Math.sin(rad), c - r * Math.cos(rad)];
  })();

  return `<svg viewBox="0 0 ${S} ${S}" role="img" aria-label="Trayectoria aparente del satélite">
    <circle cx="${c}" cy="${c}" r="${R}" fill="#081019"/>
    ${grid}${spokes}
    <path d="${path}" fill="none" stroke="#3fe0c5" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
    ${first ? dot(first[0], first[1], "#3fe0c5") : ""}
    ${tca ? dot(tca[0], tca[1], "#ffb454") : ""}
    ${last ? dot(last[0], last[1], "#ff6f6f") : ""}
    <text x="${c}" y="${c - R - 8}" text-anchor="middle" fill="#7f93a8" font-size="12" font-family="sans-serif" font-weight="600">N</text>
    <text x="${c}" y="${c + R + 15}" text-anchor="middle" fill="#7f93a8" font-size="12" font-family="sans-serif" font-weight="600">S</text>
    <text x="${c + R + 10}" y="${c + 4}" text-anchor="middle" fill="#7f93a8" font-size="12" font-family="sans-serif" font-weight="600">E</text>
    <text x="${c - R - 10}" y="${c + 4}" text-anchor="middle" fill="#7f93a8" font-size="12" font-family="sans-serif" font-weight="600">O</text>
    </svg>`;
}

function chartSvg(points, pass, freq) {
  const W = 620;
  const H = 250;
  const L = 44;
  const R = 88;
  const T = 16;
  const B = 30;
  const t0 = points.t[0];
  const t1 = points.t[points.t.length - 1];
  const span = Math.max(1, t1 - t0);

  const x = (t) => L + ((t - t0) / span) * (W - L - R);
  const yEl = (el) => T + (1 - el / 90) * (H - T - B);

  const rates = points.rate.filter((v) => v !== null && Number.isFinite(v));
  const maxRate = Math.max(0.2, ...rates.map((v) => Math.abs(v)));
  const maxDop = freq ? (maxRate / C_KM_S) * freq : 0; // Hz
  const yDop = (hz) => T + (0.5 - (maxDop ? hz / (2 * maxDop) : 0)) * (H - T - B);

  const coords = [];
  for (let i = 0; i < points.t.length; i++) {
    if (points.el[i] === null) continue;
    coords.push([x(points.t[i]), yEl(points.el[i])]);
  }
  const line = coords.length ? `M ${coords.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" L ")}` : "";
  const area = coords.length
    ? `M ${x(t0).toFixed(1)},${yEl(0).toFixed(1)} L ${coords
        .map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`)
        .join(" L ")} L ${x(t1).toFixed(1)},${yEl(0).toFixed(1)} Z`
    : "";

  const gridY = [0, 30, 60, 90]
    .map((el) => {
      const y = yEl(el);
      return `<line x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}" stroke="#16202e" stroke-width="1"/>
              <text x="${L - 8}" y="${(y + 3.5).toFixed(1)}" text-anchor="end" fill="#5b6d80" font-size="10" font-family="monospace">${el}°</text>`;
    })
    .join("");

  const tcaX = x(pass.tca_ts);
  const markers = `
    <line x1="${tcaX.toFixed(1)}" y1="${T}" x2="${tcaX.toFixed(1)}" y2="${H - B}" stroke="#ffb454" stroke-width="1" stroke-dasharray="3 3" opacity="0.6"/>
    <text x="${(tcaX + (tcaX < L + 28 ? 5 : tcaX > W - R - 28 ? -5 : 0)).toFixed(1)}" y="${T + 24}" text-anchor="${tcaX < L + 28 ? "start" : tcaX > W - R - 28 ? "end" : "middle"}" fill="#ffb454" font-size="10" font-family="monospace">Máx.</text>`;

  let dopLine = "";
  let dopLabels = "";
  if (freq && rates.length) {
    const pts = [];
    for (let i = 0; i < points.t.length; i++) {
      if (points.rate[i] === null) continue;
      const shift = (-points.rate[i] / C_KM_S) * freq;
      pts.push([x(points.t[i]), yDop(shift)]);
    }
    dopLine = `<path d="M ${pts.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" L ")}" fill="none" stroke="#ffb454" stroke-width="1.6" stroke-dasharray="5 4" opacity="0.9"/>`;
    const maxK = (maxDop / 1000).toFixed(1);
    dopLabels = `
      <text x="${W - R + 7}" y="${(T + 10).toFixed(1)}" fill="#ffb454" font-size="9.5" font-family="monospace">+${maxK} kHz</text>
      <text x="${W - R + 7}" y="${yDop(0) + 3.5}" fill="#5b6d80" font-size="10" font-family="monospace">0</text>
      <text x="${W - R + 7}" y="${(H - B).toFixed(1)}" fill="#ffb454" font-size="9.5" font-family="monospace">−${maxK} kHz</text>`;
  }

  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Elevación y Doppler durante el paso">
    <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="#081019" rx="6"/>
    ${gridY}
    <path d="${area}" fill="rgba(63,224,197,0.10)"/>
    <path d="${line}" fill="none" stroke="#3fe0c5" stroke-width="2"/>
    ${dopLine}${markers}${dopLabels}
    <text x="${L}" y="${H - 8}" fill="#5b6d80" font-size="10" font-family="monospace">${fmtHM(pass.aos_ts)}</text>
    <text x="${tcaX.toFixed(1)}" y="${H - 8}" text-anchor="middle" fill="#5b6d80" font-size="10" font-family="monospace">${fmtHM(pass.tca_ts)}</text>
    <text x="${W - R}" y="${H - 8}" text-anchor="end" fill="#5b6d80" font-size="10" font-family="monospace">${fmtHM(pass.los_ts)}</text>
  </svg>`;
}

/* =============================================================== comandos */

function commandFor(ch, p) {
  const mhz = (ch.freq_hz / 1e6).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  const slug = (p.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || `sat-${p.norad}`).slice(0, 40);
  const mode = (ch.mode || "").toUpperCase();

  if (mode.includes("APT")) {
    return (
      `# APT: graba el paso y decodifica la imagen\n` +
      `rtl_fm -f ${mhz}M -M fm -s 60k -r 60k -g 40 | \\\n` +
      `  sox -t raw -r 60k -e s -b 16 -c 1 - -r 11025 ${slug}.wav\n` +
      `noaa-apt ${slug}.wav -o ${slug}.png`
    );
  }
  if (mode.includes("LRPT")) {
    const mhz = (ch.freq_hz / 1e6).toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
    return (
      `# LRPT con SatDump (Ctrl+C para terminar)\n` +
      `satdump live meteor_m2-x_lrpt ./${slug}-lrpt --source rtlsdr \\\n` +
      `  --frequency ${mhz}e6 --samplerate 2.4e6 --gain 40`
    );
  }
  if (mode.includes("APRS")) {
    return (
      `# APRS / AX.25\n` +
      `rtl_fm -f ${mhz}M -M fm -s 24k -r 24k -g 40 | \\\n` +
      `  sox -t raw -r 24k -e s -b 16 -c 1 - -t wav - | direwolf -r 24000 -`
    );
  }
  if (mode.includes("FM")) {
    return (
      `# FM: escucha en directo\n` +
      `rtl_fm -f ${mhz}M -M fm -s 24k -r 24k -g 40 | \\\n` +
      `  sox -t raw -r 24k -e s -b 16 -c 1 - -d`
    );
  }
  return (
    `# SSB/CW: escucha en directo\n` +
    `rtl_fm -f ${mhz}M -M usb -s 12k -r 12k -g 40 | \\\n` +
    `  sox -t raw -r 12k -e s -b 16 -c 1 - -d`
  );
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copiado al portapapeles.");
  } catch (err) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    try {
      document.execCommand("copy");
      toast("Copiado al portapapeles.");
    } catch (e) {
      toast("No se pudo copiar.", true);
    }
    area.remove();
  }
}

/* ================================================================ calendario */

function icsDate(ts) {
  return new Date(ts * 1000).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

function icsText(text) {
  return String(text).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
}

function exportIcs(list) {
  const passes = list || filteredPasses();
  if (!passes.length) {
    toast("No hay pasos que exportar.", true);
    return;
  }
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//PasoOrbital//ES",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
  ];
  for (const p of passes) {
    const channels = (state.byNorad.get(p.norad) || {}).channels || [];
    const freq = channels.length ? fmtFreq(channels[0].freq_hz) : "sin frecuencia";
    const desc = [
      `NORAD ${p.norad}`,
      `${freq}${p.mode ? ` (${p.mode})` : ""}`,
      `Altura máxima ${p.max_el.toFixed(0)}°`,
      `Dirección ${Math.round(p.az_aos)}° → ${Math.round(p.az_los)}°`,
      `Duración ${fmtDur(p.duration_s)}`,
      `Punto más alto ${fmtTime(p.tca_ts)}`,
    ].join("\n");
    lines.push(
      "BEGIN:VEVENT",
      `UID:pasoorbital-${p.norad}-${Math.round(p.aos_ts)}@local`,
      `DTSTAMP:${icsDate(Date.now() / 1000)}`,
      `DTSTART:${icsDate(p.aos_ts)}`,
      `DTEND:${icsDate(p.los_ts)}`,
      `SUMMARY:${icsText(`${p.name} — paso (${p.max_el.toFixed(0)}°)`)}`,
      `DESCRIPTION:${icsText(desc)}`,
      "END:VEVENT"
    );
  }
  lines.push("END:VCALENDAR");

  const blob = new Blob([lines.join("\r\n")], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  a.href = url;
  a.download = `pasoorbital-${stamp}.ics`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  toast(`${passes.length} pasos exportados al calendario.`);
}
