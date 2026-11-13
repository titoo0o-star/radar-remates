/* Radar de Remates — mapa y tabla con un solo estado de filtros.
   Datos: data/remates.json (fase 1) y data/barrios.json (capa opcional). */
"use strict";

const AREAS = {
  "Bogotá": [4.6510, -74.0817, 11], "Medellín": [6.2442, -75.5812, 12], "Cali": [3.4516, -76.5320, 12],
  "Barranquilla": [10.9685, -74.7813, 12], "Cartagena": [10.3910, -75.4794, 12], "Bucaramanga": [7.1193, -73.1227, 12],
};
const COLOMBIA = [[1.5, -77.5], [11.5, -72.5]];
const MOD = { subasta: "Subasta", puja_electronica: "Puja electrónica", venta_directa: "Venta directa" };
const FUENTE = { sae: "SAE", cisa: "CISA", davivienda: "Davivienda", bancolombia: "Bancolombia" };
const OCUP = { ocupado: "Ocupado", desocupado: "Desocupado", sin_dato: "Sin dato" };
const NIVEL = { barrio: "mismo barrio", radio: "a ≤1 km", radio2: "a ≤2 km", ciudad: "mediana de la ciudad" };
const POR_TANDA = 80;

const $ = (s) => document.querySelector(s);
const nf = new Intl.NumberFormat("es-CO");
const pesos = (v) => v == null ? "—" : "$" + nf.format(Math.round(v));
const mill = (v) => v == null ? "—" : (v >= 1e9 ? (v / 1e9).toLocaleString("es-CO", { maximumFractionDigits: 2 }) + " mil M" : nf.format(Math.round(v / 1e6)) + " M");
const m2 = (v) => v == null ? "—" : (v / 1e6).toLocaleString("es-CO", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " M";
const pct = (v) => v == null ? "—" : Math.round(v * 100) + "%";
const sinTilde = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const color = (m) => m == null ? "gris" : m >= 0.4 ? "verde" : m >= 0.3 ? "amarillo" : "gris";

let datos = [], porId = new Map(), marcadores = new Map();
let filtrados = [], visiblesTabla = [], pintadas = 0, seleccion = null;
let mapa, cluster, capaBarrios = null, barriosData = null;

/* ---------------- estado <-> URL ---------------- */
const DEF = { area: "", tipo: "", mm: 0, pmin: "", pmax: "", amin: "", amax: "",
  mod: ["subasta", "puja_electronica", "venta_directa"], fuente: null, barrio: "",
  oc: false, zona: false, capa: false, orden: "margen_pct", dir: "desc", vista: "mapa" };
let E = structuredClone(DEF);

function leerURL() {
  const p = new URLSearchParams(location.search);
  const g = (k) => p.get(k);
  if (g("c")) E.area = g("c");
  if (g("t")) E.tipo = g("t");
  if (g("mm")) E.mm = +g("mm") || 0;
  for (const k of ["pmin", "pmax", "amin", "amax"]) if (g(k)) E[k] = g(k);
  if (g("mod") != null) E.mod = g("mod") ? g("mod").split(",") : [];
  if (g("f") != null) E.fuente = g("f") ? g("f").split(",") : [];
  if (g("b")) E.barrio = g("b");
  E.oc = g("oc") === "1"; E.zona = g("z") === "1"; E.capa = g("capa") === "1";
  if (g("s")) E.orden = g("s");
  if (g("d")) E.dir = g("d") === "asc" ? "asc" : "desc";
  if (g("v")) E.vista = g("v") === "tabla" ? "tabla" : "mapa";
}

function escribirURL() {
  const p = new URLSearchParams();
  const fuentesTodas = [...new Set(datos.map((r) => r.fuente))];
  if (E.area) p.set("c", E.area);
  if (E.tipo) p.set("t", E.tipo);
  if (E.mm) p.set("mm", E.mm);
  for (const k of ["pmin", "pmax", "amin", "amax"]) if (E[k] !== "") p.set(k, E[k]);
  if (E.mod.length !== DEF.mod.length) p.set("mod", E.mod.join(","));
  if (E.fuente && E.fuente.length !== fuentesTodas.length) p.set("f", E.fuente.join(","));
  if (E.barrio) p.set("b", E.barrio);
  if (E.oc) p.set("oc", "1");
  if (E.zona) p.set("z", "1");
  if (E.capa) p.set("capa", "1");
  if (E.orden !== DEF.orden) p.set("s", E.orden);
  if (E.dir !== DEF.dir) p.set("d", E.dir);
  if (E.vista !== "mapa") p.set("v", E.vista);
  const q = p.toString();
  history.replaceState(null, "", q ? "?" + q : location.pathname);
}

function estadoAFormulario() {
  $("#f-area").value = E.area; $("#f-tipo").value = E.tipo;
  $("#f-margen").value = E.mm; $("#o-margen").value = E.mm + "%";
  for (const k of ["pmin", "pmax", "amin", "amax"]) $("#f-" + k).value = E[k];
  document.querySelectorAll("input[name=mod]").forEach((c) => (c.checked = E.mod.includes(c.value)));
  document.querySelectorAll("input[name=fuente]").forEach((c) => (c.checked = E.fuente.includes(c.value)));
  $("#f-barrio").value = E.barrio; $("#f-ocupados").checked = E.oc;
  $("#f-zona").checked = E.zona; $("#f-capa").checked = E.capa;
}

function formularioAEstado() {
  E.area = $("#f-area").value; E.tipo = $("#f-tipo").value; E.mm = +$("#f-margen").value;
  for (const k of ["pmin", "pmax", "amin", "amax"]) E[k] = $("#f-" + k).value;
  E.mod = [...document.querySelectorAll("input[name=mod]:checked")].map((c) => c.value);
  E.fuente = [...document.querySelectorAll("input[name=fuente]:checked")].map((c) => c.value);
  E.barrio = $("#f-barrio").value.trim(); E.oc = $("#f-ocupados").checked;
  E.zona = $("#f-zona").checked; E.capa = $("#f-capa").checked;
  $("#o-margen").value = E.mm + "%";
}

/* ---------------- filtrar y ordenar ---------------- */
function pasa(r) {
  if (E.area && r.area_metro !== E.area) return false;
  if (E.tipo && r.tipo !== E.tipo) return false;
  if (E.mm > 0 && !(r.margen_pct != null && r.margen_pct * 100 >= E.mm)) return false;
  const pm = r.precio_compra / 1e6;
  if (E.pmin !== "" && pm < +E.pmin) return false;
  if (E.pmax !== "" && pm > +E.pmax) return false;
  if (E.amin !== "" && !(r.area_m2 >= +E.amin)) return false;
  if (E.amax !== "" && !(r.area_m2 <= +E.amax)) return false;
  if (!E.mod.includes(r.modalidad)) return false;
  if (E.fuente && !E.fuente.includes(r.fuente)) return false;
  if (E.barrio && !sinTilde(r.barrio).includes(sinTilde(E.barrio))) return false;
  if (E.oc && r.estado_ocupacion === "ocupado") return false;
  return true;
}

function ordenar(lista) {
  const k = E.orden, s = E.dir === "asc" ? 1 : -1;
  return lista.sort((a, b) => {
    let x = a[k], y = b[k];
    if (x == null && y == null) return 0;
    if (x == null) return 1;            // vacíos siempre al final
    if (y == null) return -1;
    if (typeof x === "string") return s * x.localeCompare(y, "es");
    return s * (x - y);
  });
}

function aplicar({ moverMapa = false } = {}) {
  filtrados = ordenar(datos.filter(pasa));
  // mapa: todos los filtrados
  cluster.clearLayers();
  cluster.addLayers(filtrados.map((r) => marcadores.get(r.id)).filter(Boolean));
  if (moverMapa) encuadrar();
  actualizarTabla();
  actualizarCapa();
  escribirURL();
}

/* La tabla muestra los filtrados; con "Solo esta zona", solo los visibles en el mapa. */
function actualizarTabla() {
  const b = mapa.getBounds();
  visiblesTabla = E.zona ? filtrados.filter((r) => r.lat != null && b.contains([r.lat, r.lon])) : filtrados;
  $("#tabla tbody").innerHTML = "";
  pintadas = 0;
  pintarTanda();
  $("#vacio").hidden = visiblesTabla.length > 0;
  const total = datos.length, n = visiblesTabla.length;
  $("#contador").textContent = `${nf.format(n)} de ${nf.format(total)} inmuebles` + (E.zona ? " · en esta zona" : "");
  document.querySelectorAll("thead th").forEach((th) =>
    th.setAttribute("aria-sort", th.dataset.k === E.orden ? (E.dir === "asc" ? "ascending" : "descending") : "none"));
}

function pintarTanda(hasta) {
  const fin = Math.min(visiblesTabla.length, Math.max(pintadas + POR_TANDA, hasta ?? 0));
  if (fin <= pintadas) return;
  const frag = document.createDocumentFragment();
  for (let i = pintadas; i < fin; i++) frag.appendChild(fila(visiblesTabla[i]));
  $("#tabla tbody").appendChild(frag);
  pintadas = fin;
}

function fila(r) {
  const tr = document.createElement("tr");
  tr.dataset.id = r.id;
  if (r.id === seleccion) tr.classList.add("sel");
  const alerta = r.revisar && r.revisar.length ? ` <span class="alerta" title="${esc(r.revisar.join(" · "))}">⚠</span>` : "";
  const lugar = [r.barrio, r.ciudad].filter(Boolean).join(", ");
  tr.innerHTML = `
    <td class="num"><span class="chip c-${color(r.margen_pct)}">${pct(r.margen_pct)}</span>${alerta}</td>
    <td class="num col-neto">${pct(r.margen_neto_pct)}</td>
    <td class="inm"><b>${r.tipo === "local" ? "Local" : "Apartamento"} · ${esc(FUENTE[r.fuente] || r.fuente)}</b><small>${esc(lugar)}</small></td>
    <td class="num">${r.area_m2 == null ? "—" : nf.format(Math.round(r.area_m2))}</td>
    <td class="num">${mill(r.precio_compra)}</td>
    <td class="num col-m2">${m2(r.precio_m2)}<br><small class="mercado">vs ${m2(r.precio_m2_mercado)}</small></td>
    <td class="col-mod">${MOD[r.modalidad] || r.modalidad}${r.estado_ocupacion === "ocupado" ? "<br><small class=mercado>Ocupado</small>" : ""}</td>`;
  return tr;
}

/* ---------------- mapa ---------------- */
function icono(r, sel) {
  const hueco = r.precision_ubicacion && r.precision_ubicacion !== "exacta" ? " hueco" : "";
  return L.divIcon({
    className: "", iconSize: [16, 16], iconAnchor: [8, 8], popupAnchor: [0, -8],
    html: `<div class="pin ${r.tipo} ${color(r.margen_pct)}${hueco}${sel ? " sel" : ""}"></div>`,
  });
}

function ficha(r) {
  const rev = r.revisar && r.revisar.length ? `<ul>${r.revisar.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  const prec = { exacta: "", barrio: " (ubicación aproximada: barrio)", ciudad: " (ubicación aproximada: ciudad)" }[r.precision_ubicacion] || "";
  const notaCisa = r.fuente === "cisa" ? ` <small>(buscar código ${esc(r.codigo)})</small>` : "";
  return `<div class="ficha">
    <h3>${esc(r.titulo)}</h3>
    <div class="sub">${esc([r.direccion, r.barrio, r.ciudad].filter(Boolean).join(" · "))}${prec}</div>
    <dl>
      <dt>Precio</dt><dd><b>${pesos(r.precio_compra)}</b></dd>
      <dt>Área</dt><dd>${r.area_m2 == null ? "—" : nf.format(r.area_m2) + " m²"}</dd>
      <dt>$/m²</dt><dd>${pesos(r.precio_m2)}</dd>
      <dt>Mercado $/m²</dt><dd>${pesos(r.precio_m2_mercado)}</dd>
      <dt>Margen</dt><dd><span class="chip c-${color(r.margen_pct)}">${pct(r.margen_pct)}</span></dd>
      <dt>Margen neto</dt><dd>${pct(r.margen_neto_pct)}</dd>
      <dt>Comparables</dt><dd>${nf.format(r.comparables_n || 0)} · ${NIVEL[r.mercado_nivel] || "—"}</dd>
      <dt>Modalidad</dt><dd>${MOD[r.modalidad] || r.modalidad}</dd>
      <dt>Subasta</dt><dd>${r.fecha_subasta || "—"}</dd>
      <dt>Ocupación</dt><dd>${OCUP[r.estado_ocupacion] || "—"}</dd>
      ${r.avaluo ? `<dt>Avalúo</dt><dd>${pesos(r.avaluo)}</dd>` : ""}
      ${r.matricula ? `<dt>Matrícula</dt><dd>${esc(r.matricula)}</dd>` : ""}
    </dl>${rev}
    <a href="${esc(r.url)}" target="_blank" rel="noopener">Ver en ${esc(FUENTE[r.fuente] || r.fuente)} ↗</a>${notaCisa}
  </div>`;
}

function crearMarcadores() {
  for (const r of datos) {
    if (r.lat == null || r.lon == null) continue;
    const m = L.marker([r.lat, r.lon], { icon: icono(r, false), title: r.titulo });
    m.bindPopup(() => ficha(r), { maxWidth: 300, autoPanPadding: [20, 20] });
    m.on("click", () => seleccionar(r.id, "mapa"));
    marcadores.set(r.id, m);
  }
}

function encuadrar() {
  if (E.area && AREAS[E.area]) {
    const pts = filtrados.filter((r) => r.lat != null).map((r) => [r.lat, r.lon]);
    if (pts.length) mapa.fitBounds(pts, { padding: [30, 30], maxZoom: 14 });
    else mapa.setView(AREAS[E.area].slice(0, 2), AREAS[E.area][2]);
  } else {
    mapa.fitBounds(COLOMBIA);
  }
}

function leyenda() {
  const c = L.control({ position: "bottomleft" });
  c.onAdd = () => {
    const d = L.DomUtil.create("div", "leyenda");
    d.innerHTML = `<div><span class="pin apartamento verde"></span>Margen ≥ 40%</div>
      <div><span class="pin apartamento amarillo"></span>30–40%</div>
      <div><span class="pin apartamento gris"></span>&lt; 30% o sin dato</div>
      <div><span class="pin apartamento gris"></span>Apartamento <span class="pin local gris" style="margin-left:8px"></span>Local</div>
      <div><span class="pin apartamento hueco gris"></span>Ubicación aproximada</div>
      <div class="ley-capa" hidden>$/m² por barrio: <span class="grad"></span> barato → caro</div>`;
    L.DomEvent.disableClickPropagation(d);
    return d;
  };
  c.addTo(mapa);
}

/* Capa opcional: mediana de $/m² por barrio (círculos en el centro de sus anuncios). */
async function actualizarCapa() {
  const ley = document.querySelector(".ley-capa");
  if (ley) ley.hidden = !E.capa;
  if (!E.capa) { if (capaBarrios) { mapa.removeLayer(capaBarrios); capaBarrios = null; } return; }
  if (!barriosData) {
    barriosData = await cargarJSON("barrios.json").catch(() => []);
  }
  if (capaBarrios) mapa.removeLayer(capaBarrios);
  const tipo = E.tipo || "apartamento";
  const lista = barriosData.filter((b) => b.tipo === tipo && (!E.area || b.area_metro === E.area));
  const vals = lista.map((b) => b.mediana_m2).sort((a, b) => a - b);
  const q = (p) => vals[Math.floor(p * (vals.length - 1))] || 0;
  const cortes = [q(0.2), q(0.4), q(0.6), q(0.8)];
  const paleta = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"];
  capaBarrios = L.layerGroup(lista.map((b) => {
    const i = cortes.filter((c) => b.mediana_m2 > c).length;
    return L.circleMarker([b.lat, b.lon], {
      radius: Math.min(22, 6 + Math.sqrt(b.n) * 1.5), color: "#555", weight: 1,
      fillColor: paleta[i], fillOpacity: 0.55, interactive: true,
    }).bindTooltip(`${esc(b.barrio)} (${esc(b.ciudad)})<br>${tipo === "local" ? "Locales" : "Aptos"}: ${pesos(b.mediana_m2)}/m² · ${b.n} anuncios`);
  }));
  capaBarrios.addTo(mapa);
  capaBarrios.eachLayer((l) => l.bringToBack());
}

/* ---------------- selección sincronizada ---------------- */
function seleccionar(id, origen) {
  const prev = seleccion;
  seleccion = id;
  for (const k of [prev, id]) {
    const r = porId.get(k), m = marcadores.get(k);
    if (r && m) m.setIcon(icono(r, k === id));
  }
  document.querySelectorAll("#tabla tbody tr.sel").forEach((tr) => tr.classList.remove("sel"));
  const r = porId.get(id);
  if (!r) return;
  if (origen === "mapa") {
    // resalta la fila (pintando hasta ella si aún no estaba cargada)
    const i = visiblesTabla.findIndex((x) => x.id === id);
    if (i >= 0) {
      pintarTanda(i + 1);
      const tr = $(`#tabla tbody tr[data-id="${CSS.escape(id)}"]`);
      if (tr) { tr.classList.add("sel"); tr.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    }
  } else {
    const tr = $(`#tabla tbody tr[data-id="${CSS.escape(id)}"]`);
    if (tr) tr.classList.add("sel");
    const m = marcadores.get(id);
    if (m) {
      if (esMovil()) cambiarVista("mapa");
      cluster.zoomToShowLayer(m, () => {
        mapa.panTo(m.getLatLng());
        m.openPopup();
      });
    }
  }
}

/* ---------------- celular ---------------- */
const esMovil = () => matchMedia("(max-width: 860px)").matches;
function cambiarVista(v) {
  E.vista = v;
  $("#vista").className = "vista ver-" + v;
  $("#tab-mapa").setAttribute("aria-selected", v === "mapa");
  $("#tab-tabla").setAttribute("aria-selected", v === "tabla");
  if (v === "mapa") setTimeout(() => mapa.invalidateSize(), 0);
  escribirURL();
}

/* ---------------- arranque ---------------- */
async function cargarJSON(nombre) {
  // publicado: data/ junto a la app; en el repo: ../data/
  for (const base of ["data/", "../data/"]) {
    try {
      const r = await fetch(base + nombre, { cache: "no-cache" });
      if (r.ok) return await r.json();
    } catch (e) { /* siguiente */ }
  }
  throw new Error("No se pudo cargar " + nombre);
}

function poblarFuentesYBarrios() {
  const fuentes = [...new Set(datos.map((r) => r.fuente))].sort();
  if (E.fuente == null) E.fuente = fuentes;
  $("#fuentes").innerHTML = fuentes.map((f) =>
    `<label class="chk"><input type="checkbox" name="fuente" value="${esc(f)}">${esc(FUENTE[f] || f)}</label>`).join("");
  actualizarBarrios();
}

function actualizarBarrios() {
  const bs = [...new Set(datos.filter((r) => r.barrio && (!E.area || r.area_metro === E.area)).map((r) => r.barrio))]
    .sort((a, b) => a.localeCompare(b, "es"));
  $("#barrios").innerHTML = bs.map((b) => `<option value="${esc(b)}">`).join("");
}

function eventos() {
  let t;
  const cambio = (moverMapa) => { formularioAEstado(); aplicar({ moverMapa }); };
  $("#filtros").addEventListener("input", (e) => {
    if (e.target.id === "f-margen") $("#o-margen").value = e.target.value + "%";
    clearTimeout(t);
    t = setTimeout(() => cambio(false), e.target.type === "number" || e.target.type === "search" ? 250 : 0);
  });
  $("#filtros").addEventListener("submit", (e) => e.preventDefault());
  $("#f-area").addEventListener("change", () => { formularioAEstado(); actualizarBarrios(); aplicar({ moverMapa: true }); });
  $("#b-limpiar").addEventListener("click", () => {
    const area = E.area, vista = E.vista;
    E = structuredClone(DEF); E.area = area; E.vista = vista;
    E.fuente = [...new Set(datos.map((r) => r.fuente))];
    estadoAFormulario(); aplicar();
  });
  document.querySelectorAll("thead th").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    if (E.orden === k) E.dir = E.dir === "asc" ? "desc" : "asc";
    else { E.orden = k; E.dir = ["tipo", "modalidad", "precio_compra", "precio_m2", "area_m2"].includes(k) ? "asc" : "desc"; }
    aplicar();
  }));
  $("#tabla tbody").addEventListener("click", (e) => {
    const tr = e.target.closest("tr");
    if (tr) seleccionar(tr.dataset.id, "tabla");
  });
  new IntersectionObserver((ent) => { if (ent[0].isIntersecting) pintarTanda(); },
    { root: $("#panel-tabla"), rootMargin: "400px" }).observe($("#mas"));
  mapa.on("moveend", () => { if (E.zona) actualizarTabla(); });
  $("#b-filtros").addEventListener("click", () => {
    const f = $("#filtros"), ab = f.classList.toggle("abierto");
    $("#b-filtros").setAttribute("aria-expanded", ab);
  });
  $("#tab-mapa").addEventListener("click", () => cambiarVista("mapa"));
  $("#tab-tabla").addEventListener("click", () => cambiarVista("tabla"));
}

async function iniciar() {
  const t0 = performance.now();
  leerURL();
  mapa = L.map("mapa", { preferCanvas: false, zoomControl: true }).fitBounds(COLOMBIA);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(mapa);
  cluster = L.markerClusterGroup({ chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: 50, spiderfyOnMaxZoom: true });
  mapa.addLayer(cluster);
  leyenda();
  try {
    datos = await cargarJSON("remates.json");
  } catch (e) {
    $("#cargando").textContent = "No se pudo cargar data/remates.json.";
    return;
  }
  datos.forEach((r) => porId.set(r.id, r));
  crearMarcadores();
  poblarFuentesYBarrios();
  estadoAFormulario();
  eventos();
  cambiarVista(E.vista);
  aplicar({ moverMapa: true });
  $("#cargando").hidden = true;
  console.info(`Radar: ${datos.length} inmuebles en ${Math.round(performance.now() - t0)} ms`);
}

iniciar();
