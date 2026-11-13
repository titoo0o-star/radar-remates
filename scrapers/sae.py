"""SAE — activosporcolombia.com (operador SAE).

La página de búsqueda es Next.js y trae los resultados como JSON incrustado
(`initialSearchData`). Aunque la interfaz no lo muestra, el buscador acepta por URL:
  property_type_ids=1,2,21  (apartaestudio, apartamento, local comercial)
  city_ids=11001,...        (códigos DANE de los municipios del alcance)
La ficha de detalle (`initialData`) trae dirección, coordenadas, barrio y ocupación.

Precios (campos etiquetados en el JSON de la ficha):
  precio_base_venta / valor_minimo_venta_unidad  -> precio_compra (precio base)
  valor_avaluo_comercial                          -> avaluo (solo referencia)
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from common.esquema import fila
from common.normalizar import (a_entero, a_float, matricula, ocupacion,
                               tipo_inmueble, ubicar_municipio)

from ._nextjs import flight, objeto_tras

log = logging.getLogger("sae")

BASE = "https://activosporcolombia.com"
BUSCAR = BASE + "/es/v2/buscar"
TIPOS_ID = {1: "apartamento", 2: "apartamento", 21: "local"}
POR_PAGINA = 48

# Estados que se pueden comprar hoy o pronto
ESTADOS_SUBASTA = {"SUBASTA", "PROXIMO_SUBASTA"}
ESTADOS_VENTA = {"VENTA", "PROXIMA_VENTA", "VENTA_ARRIENDO"}

_HREF = re.compile(r'href="/es/(inmueble|unidad-inmobiliaria)/(\d+)/([^"?#]+)"')
COL = timezone(timedelta(hours=-5))


def _buscar(http, page: int, city_ids: list[int] | None):
    params = {"operator_ids": 2, "property_type_ids": ",".join(map(str, TIPOS_ID)),
              "limit": POR_PAGINA, "page": page, "sort_by": "date_desc"}
    if city_ids:
        params["city_ids"] = ",".join(map(str, city_ids))
    html = http.get(BUSCAR, params=params).text
    f = flight(html)
    data = objeto_tras(f, '"initialSearchData":')
    filtros = objeto_tras(f, '"initialFilters":')
    hrefs = {(m[0], int(m[1])): f"{BASE}/es/{m[0]}/{m[1]}/{m[2]}" for m in _HREF.findall(html)}
    return data, filtros, hrefs


def _city_ids(filtros: dict) -> list[int]:
    """Códigos de los municipios del alcance según el catálogo de ubicaciones del portal."""
    ids = []
    for dep in filtros.get("locations", {}).get("departments", []):
        for c in dep.get("cities", []):
            if ubicar_municipio(c["name"], dep["name"]):
                ids.append(c["id"])
    return sorted(set(ids))


def _fecha(iso: str | None) -> str | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(COL).date().isoformat()


def _detalle(http, url: str) -> dict | None:
    f = flight(http.get(url).text)
    d = objeto_tras(f, '"initialData":')
    return (d or {}).get("data")


def _fila(card: dict, url: str, det: dict) -> dict | None:
    es_unidad = card.get("item_type") == "UNIDAD_INMOBILIARIA"
    # En una unidad (apto + garajes) el inmueble principal da área, ubicación y ocupación;
    # el precio es el de la unidad completa.
    p = det
    if es_unidad:
        p = det.get("inmueble_padre") or next(
            (x for x in det.get("inmuebles", []) if x.get("es_padre")), None) or {}

    tid = p.get("tipo_inmueble_id") or (p.get("tipo_inmueble") or {}).get("id_tipo_inmueble")
    tipo = TIPOS_ID.get(tid) or tipo_inmueble((p.get("tipo_inmueble") or {}).get("tipo_inmueble"))
    if not tipo:
        return None

    loc = p.get("location") or {}
    mpio = (loc.get("city") or {}).get("name") or p.get("city_name")
    depto = (loc.get("department") or {}).get("name")
    u = ubicar_municipio(mpio, depto)
    if not u:
        return None
    ciudad, departamento, area_metro = u

    dirs = p.get("addresses") or det.get("addresses") or []
    d0 = next((a for a in dirs if a.get("is_main_address")), dirs[0] if dirs else {})
    lat, lon = a_float(d0.get("latitude")), a_float(d0.get("longitude"))
    if not (lat and lon and -5 < lat < 14 and -82 < lon < -66):
        lat = lon = None

    estado = (card.get("state") or {}).get("code")
    sub = det.get("subasta") or {}
    if estado in ESTADOS_SUBASTA or sub:
        modalidad, fecha = "subasta", _fecha(sub.get("fecha_inicio") or (card.get("auction") or {}).get("fecha_inicio"))
    else:
        modalidad, fecha = "venta_directa", None

    if es_unidad:
        precio = ((p.get("grupo") or {}).get("valor_minimo_venta_unidad")
                  or sub.get("valor_inicial") or card.get("base_sale_price"))
    else:
        precio = det.get("precio_base_venta") or sub.get("valor_inicial") or card.get("base_sale_price")

    area = a_float(p.get("area_construida")) or a_float(p.get("area_privada"))
    if not area and not es_unidad:
        area = a_float(card.get("built_area"))

    return fila(
        "sae", card.get("code") or det.get("codigo"),
        matricula=matricula(p.get("numero_matricula") or card.get("matricula_number")),
        titulo=card.get("reference") or det.get("referencia") or det.get("nombre"),
        tipo=tipo, ciudad=ciudad, departamento=departamento, area_metro=area_metro,
        barrio=p.get("neighborhood_name") or (loc.get("neighborhood") or {}).get("name"),
        direccion=(d0.get("free_text_address") or "").strip() or None,
        lat=lat, lon=lon, precision_ubicacion="exacta" if lat else None,
        area_m2=area or None,
        precio_compra=a_entero(precio),
        avaluo=a_entero(card.get("commercial_appraisal") or det.get("valor_avaluo_comercial")),
        modalidad=modalidad, fecha_subasta=fecha,
        estado_ocupacion=ocupacion(p.get("estado_habitado")),
        url=url,
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    data, filtros, hrefs = _buscar(http, 1, None)
    city_ids = _city_ids(filtros or {})
    log.info("SAE: %d municipios del alcance en el catálogo", len(city_ids))
    if not city_ids:
        raise RuntimeError("No se encontraron municipios del alcance en el catálogo de la SAE")

    filas, vistos, page, total_pages = [], set(), 1, 1
    while page <= total_pages:
        data, _, hrefs = _buscar(http, page, city_ids)
        total_pages = data.get("total_pages") or 1
        if page == 1:
            log.info("SAE: %s resultados (aptos+locales en el alcance), %s páginas",
                     data.get("total"), total_pages)
        for card in data.get("properties", []):
            estado = (card.get("state") or {}).get("code")
            if estado not in ESTADOS_SUBASTA | ESTADOS_VENTA:
                continue
            ruta = "unidad-inmobiliaria" if card.get("item_type") == "UNIDAD_INMOBILIARIA" else "inmueble"
            url = hrefs.get((ruta, card["id"]))
            if not url or (ruta, card["id"]) in vistos:
                continue
            vistos.add((ruta, card["id"]))
            try:
                det = _detalle(http, url)
                r = _fila(card, url, det or {})
            except Exception as e:  # una ficha mala no tumba la fuente
                log.warning("SAE: ficha %s falló: %s", url, e)
                continue
            if r:
                filas.append(r)
            if limite and len(filas) >= limite:
                return filas
        page += 1
    return filas
