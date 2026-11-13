"""Anuncios de mercado de inmobiliariotu360.bancolombia.com (tienda VTEX).

Catálogo público:  GET /api/catalog_system/pub/products/search/venta/{categoria}?map=c,c
                   &fq=P:[min TO max]&_from=&_to=   (máx. 50 por petición, 2.500 por consulta)
El total de una consulta viene en el encabezado `resources: 0-49/TOTAL`; si pasa de 2.500
se parte el rango de precios en dos hasta que quepa.

Solo se usan inmuebles `Estado = Usado` (los proyectos nuevos de constructoras no son
comparables para reventa). El área sale del nombre del ítem: "(AP:101-AC:101)" =
área privada / área construida.
"""
import logging
import re
from urllib.parse import quote

from common.normalizar import a_float, clave, limpiar_barrio, tipo_inmueble, ubicar_municipio

log = logging.getLogger("mercado.tu360")

BASE = "https://inmobiliariotu360.bancolombia.com/api/catalog_system/pub/products/search/venta/{cat}"
CATEGORIAS = ["apartamentos", "apartaestudios", "locales"]
MAX_CONSULTA = 2500
PAGINA = 50
_AREA = re.compile(r"AP:\s*([\d.,]+)\s*-\s*AC:\s*([\d.,]+)", re.I)


def _url(cat, pmin, pmax, desde, hasta) -> str:
    # VTEX no acepta '+' como espacio en fq: hay que mandar %20
    fq = quote(f"P:[{pmin} TO {pmax}]", safe=":")
    return f"{BASE.format(cat=cat)}?map=c,c&fq={fq}&_from={desde}&_to={hasta}"


def _total(http, cat, pmin, pmax) -> int:
    r = http.get(_url(cat, pmin, pmax, 0, 0))
    return int((r.headers.get("resources") or "0/0").split("/")[-1])


def _rangos(http, cat, pmin=0, pmax=50_000_000_000):
    n = _total(http, cat, pmin, pmax)
    if n <= MAX_CONSULTA or pmax - pmin < 1_000_000:
        if n:
            yield pmin, pmax, n
        return
    mid = (pmin + pmax) // 2 if pmax < 50_000_000_000 else 1_000_000_000
    yield from _rangos(http, cat, pmin, mid)
    yield from _rangos(http, cat, mid + 1, pmax)


def _anuncio(p: dict) -> dict | None:
    def spec(k):
        v = p.get(k)
        return v[0] if isinstance(v, list) and v else None

    if clave(spec("Estado")) != "usado":
        return None
    # Los bienes propios del banco son oferta de remate (scrapers/bancolombia.py), no mercado
    if "142" in (p.get("productClusters") or {}) or re.match(r"^\s*c[oó]d(?:igo)?\.?\s*:?\s*\d{6,}",
                                                             p.get("description") or "", re.I):
        return None
    tipo = tipo_inmueble(" ".join(p.get("categories") or [])) or tipo_inmueble(p.get("productName"))
    if not tipo:
        return None
    u = ubicar_municipio(spec("Ciudad"), spec("Departamento"))
    if not u:
        return None
    item = (p.get("items") or [{}])[0]
    m = _AREA.search(item.get("name") or "")
    area = None
    if m:
        ap, ac = a_float(m.group(1)), a_float(m.group(2))
        area = ac or ap
    oferta = next((s["commertialOffer"] for s in item.get("sellers", []) if s.get("sellerDefault")),
                  (item.get("sellers") or [{}])[0].get("commertialOffer", {}))
    precio = oferta.get("Price") or oferta.get("ListPrice")
    if not (area and precio and oferta.get("IsAvailable", True)):
        return None
    return {
        "fuente": "tu360", "codigo": p.get("productReference"), "tipo": tipo,
        "ciudad": u[0], "area_metro": u[2],
        "barrio": limpiar_barrio(spec("Barrio")),
        "lat": a_float(spec("Latitud")), "lon": a_float(spec("Longitud")),
        "area_m2": area, "precio": int(precio), "url": p.get("link"),
    }


def _pagina(http, cat, pmin, pmax, desde) -> list[dict]:
    """Una página de 50; si el servidor falla (pasa con algunos productos), reintenta de a 10
    y salta solo los bloques que sigan fallando."""
    try:
        return http.get(_url(cat, pmin, pmax, desde, desde + PAGINA - 1)).json()
    except Exception:
        log.warning("tu360: página %s %s-%s falló; se reintenta de a 10", cat, desde, desde + PAGINA - 1)
    salida = []
    for d in range(desde, desde + PAGINA, 10):
        try:
            salida.extend(http.get(_url(cat, pmin, pmax, d, d + 9)).json())
        except Exception:
            log.warning("tu360: se omiten los anuncios %s %s-%s", cat, d, d + 9)
    return salida


def scrape(http, cfg) -> list[dict]:
    salida, vistos = [], set()
    for cat in CATEGORIAS:
        for pmin, pmax, n in _rangos(http, cat):
            for desde in range(0, min(n, MAX_CONSULTA), PAGINA):
                for p in _pagina(http, cat, pmin, pmax, desde):
                    if p.get("productId") in vistos:
                        continue
                    vistos.add(p.get("productId"))
                    a = _anuncio(p)
                    if a:
                        salida.append(a)
        log.info("tu360: %s -> %d anuncios acumulados en el alcance", cat, len(salida))
    return salida
