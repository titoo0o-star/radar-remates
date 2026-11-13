"""Davivienda — bienesalalcancedetodos.davivienda.com (bienes recibidos en dación en pago).

El sitio (Astro) busca con  POST /search {page, limit, category, subcategory, ...}
y devuelve JSON con precio, área, dirección y coordenadas, sin necesidad de abrir cada ficha.
Las categorías se leen del propio sitio (props `searchItems` de la página de inicio);
se recorren todas las de inmuebles y se filtra por tipo con la URL/título de cada bien.

Modalidad: venta por oferta (venta_directa), salvo las categorías de subastas.
`participation` es el % del inmueble que vende el banco: si es < 100% se anota en el título.
"""
import html
import json
import logging
import re

from common.esquema import fila
from common.normalizar import a_entero, a_float, clave, limpiar_barrio, tipo_inmueble, ubicar_municipio

log = logging.getLogger("davivienda")

BASE = "https://bienesalalcancedetodos.davivienda.com"
POR_PAGINA = 90
_NO_INMUEBLE = re.compile(r"vehiculo|maquinaria|casas de descanso", re.I)
_BARRIO = re.compile(r"\bBARRIO\s+(.+?)(?:\s{2,}|$)", re.I)


def _astro(v):
    """Decodifica el formato serializado de props de Astro: [0, valor] / [1, [lista]]."""
    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int):
        t, x = v
        if t == 1:
            return [_astro(y) for y in x]
        return {k: _astro(y) for k, y in x.items()} if isinstance(x, dict) else x
    if isinstance(v, dict):
        return {k: _astro(y) for k, y in v.items()}
    return v


def _categorias(http) -> list[dict]:
    r = http.get(BASE + "/inmuebles-de-vivienda")
    s = r.content.decode("utf-8")
    for p in re.findall(r'props="([^"]{300,})"', s):
        d = _astro(json.loads(html.unescape(p)))
        items = (d.get("data") or {}).get("searchItems") if isinstance(d, dict) else None
        if items:
            return [{"slug": i["slug"], "nombre": i["name"]} for i in items
                    if not _NO_INMUEBLE.search(clave(i["name"]))]
    raise RuntimeError("No se encontró la lista de categorías de Davivienda")


def _buscar(http, cat: str):
    page, pages = 1, 1
    while page <= pages:
        r = http.post(BASE + "/search", json={
            "page": page, "limit": POR_PAGINA, "category": cat, "subcategory": "all",
            "order": "more-recent", "pricemin": "", "pricemax": "", "presale": False,
            "characteristics": []})
        j = json.loads(r.content.decode("utf-8"))
        pages = (j.get("pagination") or {}).get("pageCount") or 1
        yield from j.get("result") or []
        page += 1


def _caracteristica(x, *titulos):
    for c in x.get("characteristics") or []:
        if clave(c.get("title")) in titulos:
            return c.get("value")
    return None


def _fila(x: dict, categoria: str) -> dict | None:
    if x.get("isSold") or x.get("isForRent"):
        return None
    sub = x["url"].strip("/").split("/")[-1].rsplit("-", 1)[0]  # apartamentos, locales, subcategory-3…
    tipo = tipo_inmueble(sub) or tipo_inmueble(x.get("title"))
    if not tipo:
        return None
    mpio, _, depto = (x.get("location") or "").partition(" - ")
    u = ubicar_municipio(mpio, depto)
    if not u:
        return None
    ciudad, departamento, area_metro = u

    addr = x.get("address") or {}
    direccion = re.sub(r"\s+", " ", addr.get("value") or "").strip() or None
    m = _BARRIO.search(direccion or "")
    barrio = limpiar_barrio(m.group(1)) if m else None
    co = addr.get("coordinates") or {}
    lat, lon = a_float(co.get("latitude")), a_float(co.get("longitude"))
    if not (lat and lon and -5 < lat < 14 and -82 < lon < -66):
        lat = lon = None

    # participation = % del inmueble que vende el banco. Cuotas parciales no se pueden flipear.
    # (0% aparece en bienes sin el dato cargado: se conservan)
    part = a_float(x.get("participation"))
    if part is not None and 0 < part < 100:
        return None
    titulo = x.get("title") or ""

    es_subasta = "subasta" in clave(categoria)
    return fila(
        "davivienda", x["code"],
        titulo=titulo, tipo=tipo, ciudad=ciudad, departamento=departamento,
        area_metro=area_metro, barrio=barrio, direccion=direccion,
        lat=lat, lon=lon, precision_ubicacion="exacta" if lat else None,
        area_m2=a_float(_caracteristica(x, "area")) or None,
        precio_compra=a_entero(x.get("value")),
        modalidad="subasta" if es_subasta else "venta_directa",
        url=BASE + x["url"],
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    filas, vistos = [], set()
    for cat in _categorias(http):
        n0 = len(filas)
        for x in _buscar(http, cat["slug"]):
            if x.get("code") in vistos:
                continue
            vistos.add(x.get("code"))
            r = _fila(x, cat["nombre"])
            if r:
                filas.append(r)
                if limite and len(filas) >= limite:
                    return filas
        log.info("Davivienda: categoría %s -> %d en alcance", cat["nombre"], len(filas) - n0)
    return filas
