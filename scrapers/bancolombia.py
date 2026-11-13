"""Bancolombia — bienes propios del banco (BRP: bienes recibidos en pago) en el portal
inmobiliariotu360.bancolombia.com.

Ese portal (tienda VTEX) es un marketplace: mezcla los bienes del banco con anuncios de
inmobiliarias aliadas (AR Soluciones, Valor Tierra…) y proyectos nuevos de constructoras.
Los del banco se reconocen por dos marcas, que se combinan:
  - están en la colección "Landing Inmuebles BRP" (productClusterIds:142), y/o
  - su descripción empieza con el código interno del banco ("Cod: 50201008").
Se recorre el catálogo de apartamentos, apartaestudios y locales con las mismas consultas por
rango de precio que mercado/tu360.py, y se quedan solo los que tienen alguna de las dos marcas.

Venta directa, sin avalúo ni matrícula publicados.
"""
import logging
import re

from common.esquema import fila
from common.normalizar import a_float, clave, limpiar_barrio, ocupacion, tipo_inmueble, ubicar_municipio
from mercado import tu360

log = logging.getLogger("bancolombia")

COLECCION_BRP = "142"
_COD = re.compile(r"^\s*c[oó]d(?:igo)?\.?\s*:?\s*(\d{6,})", re.I)
_OCUP = re.compile(r"\b(desocupad[oa]|ocupad[oa]|arrendad[oa])\b", re.I)


def es_del_banco(p: dict) -> bool:
    return COLECCION_BRP in (p.get("productClusters") or {}) or bool(_COD.match(p.get("description") or ""))


def _spec(p, k):
    v = p.get(k)
    return v[0] if isinstance(v, list) and v else None


def _fila(p: dict) -> dict | None:
    if not es_del_banco(p):
        return None
    tipo = tipo_inmueble(" ".join(p.get("categories") or [])) or tipo_inmueble(p.get("productName"))
    if not tipo:
        return None
    u = ubicar_municipio(_spec(p, "Ciudad"), _spec(p, "Departamento"))
    if not u:
        return None
    ciudad, departamento, area_metro = u
    item = (p.get("items") or [{}])[0]
    m = tu360._AREA.search(item.get("name") or "")
    area = (a_float(m.group(2)) or a_float(m.group(1))) if m else None
    oferta = next((s["commertialOffer"] for s in item.get("sellers", []) if s.get("sellerDefault")),
                  (item.get("sellers") or [{}])[0].get("commertialOffer", {}))
    if not oferta.get("IsAvailable", True):
        return None
    precio = oferta.get("Price") or oferta.get("ListPrice")

    desc = p.get("description") or ""
    cod = _COD.match(desc)
    lat, lon = a_float(_spec(p, "Latitud")), a_float(_spec(p, "Longitud"))
    if not (lat and lon and -5 < lat < 14 and -82 < lon < -66):
        lat = lon = None
    direccion = (_spec(p, "Dirección") or "").strip() or None
    occ = _OCUP.search(desc)
    barrio = limpiar_barrio(_spec(p, "Barrio"))
    if barrio and clave(barrio) == clave(ciudad):
        barrio = None
    return fila(
        "bancolombia", cod.group(1) if cod else p.get("productReference"),
        titulo=p.get("productName"), tipo=tipo,
        ciudad=ciudad, departamento=departamento, area_metro=area_metro, barrio=barrio,
        direccion=direccion, lat=lat, lon=lon, precision_ubicacion="exacta" if lat else None,
        area_m2=area, precio_compra=int(precio) if precio else None,
        modalidad="venta_directa",
        estado_ocupacion=ocupacion(occ.group(1)) if occ else "sin_dato",
        url=p.get("link"),
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    filas, vistos, del_banco = [], set(), 0
    for cat in tu360.CATEGORIAS:
        for pmin, pmax, n in tu360._rangos(http, cat):
            for desde in range(0, min(n, tu360.MAX_CONSULTA), tu360.PAGINA):
                for p in tu360._pagina(http, cat, pmin, pmax, desde):
                    if p.get("productId") in vistos:
                        continue
                    vistos.add(p.get("productId"))
                    del_banco += es_del_banco(p)
                    r = _fila(p)
                    if r:
                        filas.append(r)
                        if limite and len(filas) >= limite:
                            return filas
    log.info("Bancolombia: %d productos revisados, %d del banco, %d en el alcance",
             len(vistos), del_banco, len(filas))
    return filas
