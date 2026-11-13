"""Rama Judicial — avisos de remate de los juzgados, desde el portal central de Publicaciones
Procesales (publicacionesprocesales.ramajudicial.gov.co), que desde el 14 de mayo de 2024
reemplaza las secciones "Remates" de los micrositios de cada juzgado.

Flujo:
  1. Lista la categoría "Remates" (idStructure=6098997) por departamento y ventana de fechas
     de publicación, 75 por página (parámetros cur/delta).
  2. Se queda con las publicaciones de municipios del alcance (nomMuni del enlace).
  3. Abre cada publicación: campos estructurados (fecha de remate, radicación), resumen y
     los PDF adjuntos más útiles (auto que señala fecha, aviso publicado, avalúo).
  4. Del texto saca tipo de bien, matrícula, área, dirección, avalúo y postura mínima.
     Si no se publica la postura se usa el 70% del avalúo (base de la primera licitación,
     art. 448 C.G.P.). Descarta casas, lotes, cuotas partes y remates ya pasados.
Cada publicación procesada queda en data/cache/rama.json para no volver a abrirla.
Son remates judiciales: aplica impuesto_remate en el margen neto.
"""
import json
import logging
import re
import subprocess
import tempfile
from datetime import date, timedelta
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from common.avisos import area_m2, fecha_es, matricula_en, municipio_en
from common.config import DATA
from common.esquema import fila
from common.normalizar import a_entero, clave, tipo_inmueble, ubicar_municipio

log = logging.getLogger("rama")

BASE = "https://publicacionesprocesales.ramajudicial.gov.co"
URL = BASE + "/web/publicaciones-procesales/inicio"
PORTLET = "co_com_avanti_efectosProcesales_PublicacionesEfectosProcesalesPortletV2_INSTANCE_BIyXQFHVaYaq"
P = f"_{PORTLET}_"
REMATES = 6098997
DEPTOS = {"11": "Bogotá", "25": "Cundinamarca", "05": "Antioquia", "76": "Valle del Cauca",
          "08": "Atlántico", "13": "Bolívar", "68": "Santander"}
DIAS_ATRAS = 90
VENTANA = 30          # días por consulta (las consultas muy grandes a veces vuelven vacías)
POR_PAGINA = 75
MAX_PDF = 4
CACHE = DATA / "cache" / "rama.json"

# Publicaciones que solo son el calendario del juzgado (proceso, partes, hora), sin describir bienes
_CALENDARIO = re.compile(r"(?i)^\s*\d?\.?\s*remates?\s+\d{1,2}\s+de\s+[a-z]+|^(?:enero|febrero|marzo|abril|mayo|junio|julio|"
                         r"agosto|septiembre|octubre|noviembre|diciembre)[\s_-]+\d{4}(?:\s+remates|$)|^remates\s+juzgado")
_PDF_UTIL = re.compile(r"(?i)remate|aviso|publicaci|se[ñn]al|fecha|aval[uú]o|licitaci|memorial|dictamen|peritaj|"
                       r"certificad|tradici|secuestro|auto")
_PDF_INUTIL = re.compile(r"(?i)admite|demanda|poder|notific|traslado|recurso|tutela|acta.*desiert|liquidaci")
_BIEN = re.compile(r"(?i)(bien(?:es)?\s+(?:materia|objeto)\s+de(?:l)?\s+(?:remate|licitaci[oó]n)|bien a rematar|"
                   r"inmueble identificado|identificado con (?:el )?folio)")
_CLASE = re.compile(r"(?i)\b(apartaestudio|apartamento|apto\.?|local(?:\s+comercial)?|casa|lote|finca|predio rural|"
                    r"parqueadero|garaje|bodega|oficina|veh[ií]culo|establecimiento de comercio|derechos|cuota)\b")
_DIR = re.compile(r"(?i)\b((?:carrera|calle|avenida|diagonal|transversal|kr|cra|cl|ak|ac|dg|tv)\.?\s*\d{1,3}\s*[a-h]?"
                  r"(?:\s*bis)?(?:\s*[a-h])?(?:\s*(?:sur|este|norte))?\s*(?:n[o°º]\.?|#|n[uú]mero)?\s*\d{1,3}\s*[a-h]?"
                  r"\s*-\s*\d{1,3}(?:\s*(?:sur|este))?)")
_DIR_INV = re.compile(r"(?i)n[uú]mero\s+(\d{1,3}\s*[a-h]?\s*-\s*\d{1,3})\s+de\s+la\s+"
                      r"((?:carrera|calle|avenida|diagonal|transversal)\s+\d{1,3}\s*[a-h]?(?:\s*bis)?(?:\s*(?:sur|este))?)")


def _cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _guardar_cache(c):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False)


def _listar(http, depto: str, ini: date, fin: date):
    cur = 1
    while True:
        params = {"p_p_id": PORTLET, "p_p_lifecycle": 0, "p_p_state": "normal", "p_p_mode": "view",
                  P + "idStructure": REMATES, P + "action": "filterStructures", P + "idDepto": depto,
                  P + "fechaInicio": ini.isoformat(), P + "fechaFin": fin.isoformat(),
                  P + "delta": POR_PAGINA, P + "cur": cur, P + "resetCur": "false"}
        soup = None
        for _ in range(2):   # la consulta a veces vuelve vacía: se reintenta una vez
            soup = BeautifulSoup(http.get(URL, params=params).text, "lxml")
            if re.search(r"Mostrando el intervalo", soup.get_text(" ")):
                break
        m = re.search(r"Mostrando el intervalo (\d+) - (\d+) de (\d+)", soup.get_text(" "))
        for a in soup.find_all("a", href=True):
            if "detail.jsp" in a["href"] and a.get_text(strip=True) != "Ver detalle":
                q = parse_qs(urlparse(a["href"]).query)
                g = lambda k: (q.get(P + k) or [""])[0]
                yield {"id": g("articleId"), "municipio": g("nomMuni"), "depto": g("nomDepto"),
                       "despacho": g("nomDespacho"), "titulo": a.get_text(" ", strip=True), "url": a["href"]}
        if not m or int(m.group(2)) >= int(m.group(3)):
            break
        cur += 1


def _texto_pdf(http, url: str) -> str:
    try:
        contenido = http.get(urljoin(BASE, url)).content
    except Exception as e:
        log.warning("rama: PDF %s falló: %s", url[:80], e)
        return ""
    if not contenido.startswith(b"%PDF"):
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(contenido)
        f.flush()
        r = subprocess.run(["pdftotext", "-l", "4", f.name, "-"], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", "ignore")


def _detalle(http, pub: dict) -> dict:
    soup = BeautifulSoup(http.get(pub["url"]).text, "lxml")
    texto = soup.get_text("\n", strip=True)
    i = texto.find("Datos de la Publicación")
    j = texto.find("Volver al resultado")
    cuerpo = texto[i:j if j > i else None]

    def campo(etq):
        m = re.search(rf"\n{etq}\n([^\n]+)", cuerpo, re.I)
        return m.group(1).strip() if m else None

    pdfs = [(a.get_text(" ", strip=True), a["href"]) for a in soup.find_all("a", href=True)
            if "document_library/get_file" in a["href"]]
    utiles = [p for p in pdfs if _PDF_UTIL.search(p[0]) and not _PDF_INUTIL.search(p[0])]
    prioridad = lambda p: (0 if re.search(r"(?i)aviso|publicaci|aval[uú]o|dictamen|peritaj", p[0]) else
                           1 if re.search(r"(?i)se[ñn]al|fecha|remate|licitaci", p[0]) else
                           2 if re.search(r"(?i)certificad|tradici", p[0]) else 3)
    utiles.sort(key=prioridad)
    textos = [cuerpo] + [_texto_pdf(http, u) for _, u in utiles[:MAX_PDF]]
    return {"fecha_remate": fecha_es(campo("Fecha remate")), "radicacion": campo(r"N[uú]mero de Radicaci[oó]n"),
            "texto": "\n".join(textos)}


_TIPO_BIEN = re.compile(r"(?i)\b(apartaestudio|apartamento|apto\.?|local\s+comercial|local|casa(?:\s+lote)?|lote|finca|"
                        r"predio\s+rural|parqueadero|garaje|dep[oó]sito|bodega|oficina|consultorio|"
                        r"cuota\s+parte|derechos\s+de\s+cuota)\b")
_RUIDO = re.compile(r"(?i)circulaci[oó]n|radiodifusora|y nacional|tel[eé]fono|telefax|correo|e-?mail|apoderad|abogad|"
                    r"T\.\s?P\.|direcci[oó]n\s*:|notificaci|domicilio|oficina\s+de\s+(?:registro|instrumentos|apoyo)|"
                    r"dep[oó]sitos?\s+judicial|oficina\s+judicial|oficina\s+de\s+ejecuci")
_DESCRIBE = re.compile(r"(?i)materia\s+de(?:l)?\s+(?:remate|licitaci)|objeto\s+de(?:l)?\s+remate|bien\s+a\s+rematar|"
                       r"consistente\s+en|corresponde\s+a|se\s+trata\s+de|direcci[oó]n\s+del\s+inmueble|"
                       r"inmueble\s+(?:ubicado|denominado|distinguido|identificado)|ubicad[oa]|distinguid[oa]|"
                       r"tipo\s+(?:de\s+)?(?:predio|inmueble)|(?:^|\W)(?:un|una)\s*$")


def _tipo_bien(t: str):
    """Tipo del bien subastado y el pasaje que lo describe. Recorre todas las menciones de una
    clase de inmueble y se queda con la que tiene contexto descriptivo, saltando ruido como
    'circulación local' o la dirección del abogado."""
    primero = None
    for m in _TIPO_BIEN.finditer(t):
        antes, despues = t[max(0, m.start() - 90): m.start()], t[m.end(): m.end() + 60]
        if _RUIDO.search(antes[-45:] + despues[:25]):
            continue
        clase = re.sub(r"\s+", " ", m.group(1).lower()).rstrip(".")
        if _DESCRIBE.search(antes) or re.match(r"(?i)\s*(?:no\.?|n[uú]mero|#)?\s*\d", despues) \
                or re.match(r"(?i)[\s,]*(?:ubicad|distinguid|identificad|situad|que hace parte|del edificio|"
                             r"del conjunto|con matr)", despues):
            seg = t[max(0, m.start() - 200): m.end() + 600]
            if clase in ("cuota parte", "derechos de cuota"):
                return None, seg
            return tipo_inmueble("apartamento" if clase == "apto" else clase), seg
        primero = primero or m
    return None, ""


def _pesos_tras(texto: str, rx: str) -> int | None:
    m = re.search(rx + r"[^$\d]{0,80}\$\s*([\d.,]{6,})", texto, re.I | re.S)
    return a_entero(m.group(1)) if m else None


def _analizar(pub: dict, det: dict) -> dict | None:
    """Fila del esquema o None si el bien no está en el alcance."""
    t = re.sub(r"[ \t]+", " ", det["texto"])
    hoy = date.today().isoformat()
    fecha = det["fecha_remate"]
    if not fecha:
        m = re.search(r"(?i)(?:fecha y hora|se señala|para el d[ií]a|del d[ií]a)[^\n]{0,80}?(\d{1,2}\s+de\s+[a-z]+\s+(?:de\s+)?\d{4})", t)
        fecha = fecha_es(m.group(1)) if m else None
    if fecha and fecha < hoy:
        return None

    tipo, seg = _tipo_bien(t)
    if not tipo:
        return None
    if re.search(r"(?i)cuota\s+parte|derechos\s+(?:de\s+)?(?:cuota|propiedad)", seg):
        return None

    u = ubicar_municipio(pub["municipio"], pub["depto"])
    um = municipio_en(seg)
    if um and (not u or um[2] == u[2]):
        u = um          # el bien puede estar en otro municipio del área (juzgado de Bogotá, bien en Soacha)
    if not u:
        return None
    ciudad, departamento, area_metro = u

    avaluo = _pesos_tras(t, r"aval[uú]ad[oa]\s+en|aval[uú]o\s+(?:comercial|total|del inmueble)?|valor del aval[uú]o")
    postura = _pesos_tras(t, r"(?:valor\s+)?(?:70|setenta)\s*%\s*(?:de\s+)?postura|postura (?:admisible|m[ií]nima)|"
                             r"base (?:de|para) (?:la )?licitaci[oó]n|base del remate")
    if not postura and avaluo:
        pct = re.search(r"(?i)(?:postura|base)[^.%]{0,80}?(\d{2,3})\s*%\s*del (?:valor del )?aval[uú]o", t)
        postura = int(avaluo * (int(pct.group(1)) if pct else 70) / 100)
    if postura and avaluo and not (0.3 * avaluo <= postura <= avaluo):
        postura = int(avaluo * 0.7)   # cifra mal leída: se vuelve a la base legal

    d = _DIR.search(seg) or _DIR.search(t)
    if d:
        direccion = re.sub(r"\s+", " ", d.group(1)).strip()
    else:
        inv = _DIR_INV.search(t)
        direccion = f"{inv.group(2).title()} # {inv.group(1)}" if inv else None

    radic = re.sub(r"\D", "", det.get("radicacion") or "") or None
    codigo = radic or pub["id"]
    return fila(
        "rama", codigo, matricula=matricula_en(seg) or matricula_en(t),
        titulo=f"{tipo.title()} – {pub['despacho'].title()}"[:120],
        tipo=tipo, ciudad=ciudad, departamento=departamento, area_metro=area_metro,
        direccion=direccion, area_m2=area_m2(seg) or area_m2(t),
        precio_compra=postura, avaluo=avaluo,
        modalidad="subasta", remate_judicial=True, fecha_subasta=fecha,
        nota=None if postura else "Precio no publicado en el aviso: ver el avalúo y la postura en los documentos del juzgado.",
        url=pub["url"],
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    cache = _cache()
    hoy = date.today()
    pubs = {}
    for depto in DEPTOS:
        fin = hoy
        while fin > hoy - timedelta(days=DIAS_ATRAS):
            ini = fin - timedelta(days=VENTANA)
            for pub in _listar(http, depto, ini, fin):
                if ubicar_municipio(pub["municipio"], pub["depto"]):
                    pubs[pub["id"]] = pub
            fin = ini - timedelta(days=1)
    log.info("Rama Judicial: %d publicaciones de remate en municipios del alcance (%d ya revisadas)",
             len(pubs), sum(1 for k in pubs if k in cache))

    filas, nuevas = [], 0
    for k, pub in pubs.items():
        if k not in cache and _CALENDARIO.search(pub["titulo"]):
            cache[k] = None
        if k not in cache:
            try:
                det = _detalle(http, pub)
                r = _analizar(pub, det)
            except Exception as e:
                log.warning("rama: publicación %s falló: %s", k, e)
                continue
            cache[k] = r
            nuevas += 1
            if nuevas % 25 == 0:
                _guardar_cache(cache)
        r = cache[k]
        if r and (not r.get("fecha_subasta") or r["fecha_subasta"] >= hoy.isoformat()):
            filas.append(r)
            if limite and len(filas) >= limite:
                break
    _guardar_cache(cache)
    log.info("Rama Judicial: %d publicaciones nuevas revisadas; %d inmuebles en el alcance", nuevas, len(filas))
    return filas
