"""Anuncios de mercado de metrocuadrado.com, enfocados donde están los remates.

La página de resultados (Next.js) trae los anuncios en el flujo de datos incrustado
(`self.__next_f`), con precio, área, barrio, coordenadas y estado Usado/Nuevo. Cada URL
devuelve solo los primeros ~65 resultados y la paginación no se puede pedir por URL, así que
en vez de recorrer la ciudad entera se piden muchas URLs pequeñas:
  - cada ciudad núcleo y sus sectores principales, y
  - cada barrio donde hay un inmueble en remate (data/remates.json), buscado con el selector
    de ubicaciones del sitio (/api/rest-selector-option/selector/locations?location=…).
Así los comparables se refuerzan justo donde hacen falta. Solo inmuebles usados.
"""
import json
import logging

from common.config import DATA
from common.normalizar import a_float, clave, limpiar_barrio, ubicar_municipio
from scrapers._nextjs import flight

log = logging.getLogger("mercado.metrocuadrado")

BASE = "https://www.metrocuadrado.com"
SELECTOR = BASE + "/api/rest-selector-option/selector/locations"
TIPOS = {"apartamentos": "apartamento", "locales": "local"}
MIN_OFERTA = 5   # un barrio con menos anuncios no vale la pena pedirlo


def _ubicaciones(http, termino: str) -> dict:
    try:
        return http.get(SELECTOR, params={"location": termino}).json()
    except Exception as e:
        log.warning("metrocuadrado: selector %r falló: %s", termino, e)
        return {}


def _fragmentos(http, cfg) -> list[str]:
    """URLs a pedir: ciudades núcleo + sus sectores + barrios con remates."""
    frags = []
    for area in cfg["areas_metropolitanas"]:
        j = _ubicaciones(http, clave(area))
        for k in ("cities", "sectors"):
            for x in j.get(k, []):
                u = ubicar_municipio(x.get("city"), x.get("region"))
                if u and u[2] == area and (x.get("ofertaTotal") or 0) >= MIN_OFERTA:
                    frags.append(x["urlFragment"])
    try:
        with open(DATA / "remates.json", encoding="utf-8") as f:
            remates = json.load(f)
    except FileNotFoundError:
        remates = []
    barrios = sorted({(r["ciudad"], r["barrio"]) for r in remates if r.get("barrio")})
    for ciudad, barrio in barrios:
        j = _ubicaciones(http, clave(barrio))
        cands = [x for x in j.get("neighborhoods", []) + j.get("sectors", [])
                 if (u := ubicar_municipio(x.get("city"), x.get("region"))) and u[0] == ciudad
                 and (x.get("ofertaTotal") or 0) >= MIN_OFERTA]
        exactos = [x for x in cands if clave(x.get("location")) == clave(barrio)]
        mejor = max(exactos or cands, key=lambda x: x.get("ofertaTotal") or 0, default=None)
        if mejor:
            frags.append(mejor["urlFragment"])
    return list(dict.fromkeys(frags))


def _resultados(html: str) -> list[dict]:
    f = flight(html)
    i = f.find('"totalHits"')
    if i < 0:
        return []
    d, _ = json.JSONDecoder().raw_decode(f[f.rfind("{", 0, i):])
    return (d.get("results") or []) + (d.get("highlights") or [])


def _anuncio(x: dict, tipo: str) -> dict | None:
    if clave(x.get("mestadoinmueble")) != "usado" or clave(x.get("mtiponegocio")) != "venta":
        return None
    u = ubicar_municipio((x.get("mciudad") or {}).get("nombre"))
    if not u:
        return None
    precio, area = x.get("mvalorventa"), a_float(x.get("mareac")) or a_float(x.get("marea"))
    if not (precio and area):
        return None
    loc = x.get("localizacion") or {}
    aprox = x.get("ubicacionaproximada") == "S"
    return {
        "fuente": "metrocuadrado", "codigo": x.get("midinmueble"), "tipo": tipo,
        "ciudad": u[0], "area_metro": u[2],
        "barrio": limpiar_barrio(x.get("mnombrecomunbarrio") or x.get("mbarrio")),
        "lat": None if aprox else a_float(loc.get("lat")),
        "lon": None if aprox else a_float(loc.get("lon")),
        "area_m2": area, "precio": int(precio),
        "url": BASE + (x.get("link") or ""),
    }


def scrape(http, cfg) -> list[dict]:
    frags = _fragmentos(http, cfg)
    log.info("metrocuadrado: %d ciudades, sectores y barrios a consultar", len(frags))
    salida, vistos = [], set()
    for frag in frags:
        for seg, tipo in TIPOS.items():
            try:
                res = _resultados(http.get(f"{BASE}/{seg}/venta/{frag}/").text)
            except Exception as e:
                log.warning("metrocuadrado: %s/%s falló: %s", seg, frag, e)
                continue
            for x in res:
                if x.get("midinmueble") in vistos:
                    continue
                vistos.add(x.get("midinmueble"))
                a = _anuncio(x, tipo)
                if a:
                    salida.append(a)
    log.info("metrocuadrado: %d anuncios usados en el alcance", len(salida))
    return salida
