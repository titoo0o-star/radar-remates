"""CISA — inmuebles.cisa.gov.co (Central de Inversiones; incluye DIAN, ICBF, SAE y otras entidades).

El portal (Angular) consume una API JSON propia:
  GET  /PortalComercializacion/config.json  -> usuario/clave públicos que usa el propio portal
  POST /ws/login/                           -> token JWT
  POST /ws/filtroinmuebles/ {per_page, page, tipo_compra} -> resultados paginados
Toda la oferta es puja electrónica. No hay URL individual por inmueble (la ficha abre en un
modal), así que `url` apunta al portal con el código para buscarlo.
"""
import logging
import re

from common.esquema import fila
from common.normalizar import a_entero, a_float, limpiar_barrio, matricula, ocupacion, tipo_inmueble, ubicar_municipio

log = logging.getLogger("cisa")

BASE = "https://inmuebles.cisa.gov.co"
PORTAL = BASE + "/PortalComercializacion/#/landing"
POR_PAGINA = 100
ESTADOS_VALIDOS = {"en venta", "en puja", "proximo en venta"}
_BARRIO = re.compile(r"\bBARRIO\s+([A-ZÁÉÍÓÚÑ0-9 .]+?)(?:\s+(?:SOBRE|EN|DE LA|CON|UBICAD|ENTRE)\b|[,;_/.]|$)", re.I)


def _login(http):
    c = http.get(BASE + "/PortalComercializacion/config.json").json()
    t = http.post(BASE + "/ws/login/", json={"username": c["username"], "password": c["password"]}).json()
    http.s.headers["Authorization"] = "Bearer " + t["access_token"]


def _todos(http):
    page, num_pages = 1, 1
    while page <= num_pages:
        r = http.post(BASE + "/ws/filtroinmuebles/",
                      json={"per_page": POR_PAGINA, "page": page, "tipo_compra": "Puja_Electronica"}).json()
        num_pages = r.get("num_pages") or 1
        if page == 1:
            log.info("CISA: %s inmuebles en total, %s páginas", r.get("count"), num_pages)
        yield from r.get("results", [])
        page += 1


def _sin_tilde(s):
    from common.normalizar import clave
    return clave(s)


def _fila(x: dict) -> dict | None:
    if _sin_tilde(x.get("tipobien_nombre")) != "inmueble":
        return None
    if _sin_tilde(x.get("estado")) not in ESTADOS_VALIDOS or not x.get("servicio_venta", True):
        return None
    # Cuotas parciales (p. ej. 0,31% de un apartamento): el precio es solo de la fracción y
    # no se puede flipear. Solo se aceptan inmuebles completos.
    pct = a_float(x.get("porcentaje_propiedad"))
    if pct is not None and pct < 100:
        return None
    tipo = tipo_inmueble(x.get("subtipobien_nombre"))
    if not tipo:
        return None
    u = ubicar_municipio(x.get("nombre_municipio"), x.get("nombre_departamento"))
    if not u:
        return None
    ciudad, departamento, area_metro = u

    desc = x.get("descripcion") or ""
    m = _BARRIO.search(desc)
    barrio = limpiar_barrio(m.group(1)) if m else None

    codigo = str(x.get("inmueble_id"))
    entidad = x.get("entidad_nombre") or ""
    return fila(
        "cisa", codigo,
        matricula=matricula(x.get("numero_inmobiliario")),
        titulo=f"{x.get('subtipobien_nombre')} en {x.get('nombre_municipio')} ({entidad})".strip(),
        tipo=tipo, ciudad=ciudad, departamento=departamento, area_metro=area_metro,
        barrio=barrio, direccion=(x.get("direccion") or "").strip() or None,
        area_m2=a_float(x.get("area_construida")) or a_float(x.get("area")) or None,
        precio_compra=a_entero(x.get("precio_base_venta") or x.get("valor_referencia_de_venta")),
        avaluo=None,
        modalidad="puja_electronica",
        fecha_subasta=(x.get("fecha_inicial_puja") or "")[:10] or None,
        estado_ocupacion=ocupacion(x.get("estado_ocupacion")),
        url=f"{PORTAL}?codigo={codigo}",
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    _login(http)
    filas = []
    for x in _todos(http):
        r = _fila(x)
        if r:
            filas.append(r)
            if limite and len(filas) >= limite:
                break
    return filas
