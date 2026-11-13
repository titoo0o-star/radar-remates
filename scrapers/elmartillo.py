"""El Martillo (Banco Popular) — subastas de bienes de la SAE, la DIAN, liquidaciones y otros.

El portal (Liferay) llena sus pestañas con un endpoint JSON público, sin necesidad de sesión:
  POST /inicio?p_p_id=ZonaPublicaPublicacionLotes&p_p_lifecycle=2...
       _ZonaPublicaPublicacionLotes_cmd=<pestaña>&..._seleccionBE=<pestaña>&..._pageToLoadBE=<n>
Pestañas: 913/914/918 (ventas virtuales, presenciales, sobre cerrado), Directa, Remates,
Inmuebles. La mayoría de lotes son vehículos y chatarra: se filtra por tipo con la descripción
y por ciudad con el municipio mencionado en el texto. Registrarse solo hace falta para ofertar.

Las fichas de detalle se abren con la sesión del navegador, sin URL fija: `url` apunta al
portal y el número de lote va en el título.
"""
import logging
import re

from common.avisos import area_m2, matricula_en, municipio_en
from common.esquema import fila
from common.normalizar import a_entero, clave, tipo_inmueble, ubicar_municipio

log = logging.getLogger("elmartillo")

BASE = "https://www.elmartillo.com.co"
API = (BASE + "/inicio?p_p_id=ZonaPublicaPublicacionLotes&p_p_lifecycle=2&p_p_state=normal"
       "&p_p_mode=view&p_p_cacheability=cacheLevelPage")
P = "_ZonaPublicaPublicacionLotes_"
PESTANAS = ["913", "914", "918", "Directa", "Remates", "Inmuebles"]
MAX_PAGINAS = 60
_NO_INMUEBLE = re.compile(r"(?i)^(un )?lote (de|compuesto|conformado) (muebles|residuos|chatarra|equipos|aparatos)")


def _lotes(http):
    http.get(BASE + "/inicio")  # cookie de sesión de Liferay
    for cmd in PESTANAS:
        page = 0
        while page < MAX_PAGINAS:
            j = http.post(API, data={P + "cmd": cmd, P + "seleccionBE": cmd, P + "pageToLoadBE": page}).json()
            pl = j.get("payload") or {}
            items = pl.get("items") or []
            for it in items:
                yield cmd, it
            page += 1
            if not items or page >= (pl.get("totalPages") or 0):
                break


def _fila(cmd: str, it: dict) -> dict | None:
    desc = re.sub(r"<[^>]+>", " ", it.get("description") or "")
    if it.get("retiredAuction") or "LOTE RETIRADO" in desc.upper() or _NO_INMUEBLE.search(desc.strip()):
        return None
    tipo = tipo_inmueble(it.get("type")) or tipo_inmueble(desc[:120])
    if not tipo:
        return None
    u = (ubicar_municipio(it.get("cityName"), it.get("stateName")) if it.get("cityName") else None) \
        or municipio_en(desc) or ubicar_municipio(it.get("cellarCityName"), it.get("cellarStateName"))
    if not u:
        return None
    ciudad, departamento, area_metro = u
    precio = a_entero(it.get("baseValue"))
    if precio is not None and precio < 1_000_000:   # valores de relleno ("5") = sin precio publicado
        precio = None
    tipo_subasta = clave(it.get("auctionTypeName"))
    if cmd == "Directa" or "directa" in tipo_subasta:
        modalidad = "venta_directa"
    elif "virtual" in tipo_subasta:
        modalidad = "puja_electronica"
    else:
        modalidad = "subasta"
    dir_m = re.search(r"ubicad[oa]s? en (?:la |el )?((?:carrera|calle|avenida|diagonal|transversal|kr|cl|cra|ak|ac)"
                      r"[^,;]{3,60})", desc, re.I)
    codigo = it.get("stockNumber") or f"inm-{it.get('id')}"
    lote = it.get("lotCode")
    return fila(
        "martillo", codigo,
        matricula=matricula_en(desc),
        titulo=(f"Lote {lote}: " if lote else "") + desc.strip()[:90],
        tipo=tipo, ciudad=ciudad, departamento=departamento, area_metro=area_metro,
        direccion=(it.get("address") or (dir_m.group(1) if dir_m else None)),
        area_m2=area_m2(it.get("buildingArea") or "") or area_m2(desc),
        precio_compra=precio, modalidad=modalidad,
        remate_judicial=bool(re.search(r"(?i)remate judicial|juzgado", desc + " " + (it.get("sellerName") or ""))),
        fecha_subasta=(it.get("endDate") or "")[:10] or None,
        url=BASE + "/inicio",
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    filas, vistos, n = [], set(), 0
    for cmd, it in _lotes(http):
        n += 1
        k = it.get("stockNumber") or it.get("id")
        if k in vistos:
            continue
        vistos.add(k)
        r = _fila(cmd, it)
        if r:
            filas.append(r)
            if limite and len(filas) >= limite:
                break
    sin_precio = sum(1 for r in filas if not r["precio_compra"])
    log.info("El Martillo: %d lotes revisados, %d inmuebles en alcance (%d sin precio publicado)",
             n, len(filas), sin_precio)
    return [r for r in filas if r["precio_compra"]]
