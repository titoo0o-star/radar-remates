"""Anuncios de mercado de fincaraiz.com.co.

Las páginas de resultados traen un bloque JSON-LD (schema.org ItemList) con precio, área,
coordenadas y el nombre "Apartamento en Venta en {Barrio}, {Ciudad}" de cada anuncio.
URL:  /venta/{apartamentos|locales}/{municipio}/{departamento}[/paginaN]   (21 por página)
Se recorre cada municipio del alcance hasta `mercado.fincaraiz_max_paginas` (config.yaml)
o hasta que una página llegue vacía o repetida.
"""
import json
import logging
import re

from common.normalizar import a_float, clave, limpiar_barrio, ubicar_municipio

log = logging.getLogger("mercado.fincaraiz")

BASE = "https://www.fincaraiz.com.co/venta"
TIPOS = {"apartamentos": "apartamento", "locales": "local"}
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_NOMBRE = re.compile(r"\ben venta en (.+?),\s*([^,]+)$", re.I)


def _slug(s: str) -> str:
    return clave(s).replace(" ", "-")


def _ruta(municipio: str, departamento: str) -> str:
    if clave(municipio) == "bogota":
        return "bogota-dc"
    return f"{_slug(municipio)}/{_slug(departamento)}"


def _items(html: str):
    for bloque in _LD.findall(html):
        try:
            d = json.loads(bloque)
        except json.JSONDecodeError:
            continue
        if d.get("@type") == "CollectionPage":
            return d.get("name", ""), d.get("mainEntity", {}).get("itemListElement", [])
    return "", []


def _anuncio(it: dict, tipo: str, municipio: str, departamento: str) -> dict | None:
    ent = it.get("mainEntity") or {}
    precio = (it.get("offers") or {}).get("price")
    area = a_float((ent.get("floorSize") or {}).get("value"))
    if not (precio and area):
        return None
    m = _NOMBRE.search(it.get("name") or "")
    barrio = ciudad_txt = None
    if m:
        barrio, ciudad_txt = m.group(1), m.group(2)
    else:
        ciudad_txt = (ent.get("address") or {}).get("addressLocality")
    # el anuncio debe ser del municipio consultado (los portales mezclan cercanos)
    u = ubicar_municipio(ciudad_txt or municipio, departamento)
    if not u or clave(u[0]) != clave(municipio):
        return None
    if barrio and clave(barrio) == clave(municipio):
        barrio = None
    geo = ent.get("geo") or {}
    return {
        "fuente": "fincaraiz", "codigo": (it.get("url") or "").rsplit("/", 1)[-1],
        "tipo": tipo, "ciudad": u[0], "area_metro": u[2],
        "barrio": limpiar_barrio(barrio),
        "lat": a_float(geo.get("latitude")), "lon": a_float(geo.get("longitude")),
        "area_m2": area, "precio": int(precio), "url": it.get("url"),
    }


def scrape(http, cfg) -> list[dict]:
    max_pag = cfg["mercado"].get("fincaraiz_max_paginas", 150)
    salida = []
    for area, info in cfg["areas_metropolitanas"].items():
        for m in info["municipios"]:
            for seg, tipo in TIPOS.items():
                base = f"{BASE}/{seg}/{_ruta(m['nombre'], m['departamento'])}"
                vistos, n0 = set(), len(salida)
                for pag in range(1, max_pag + 1):
                    url = base if pag == 1 else f"{base}/pagina{pag}"
                    try:
                        r = http.get(url)
                    except Exception as e:
                        log.warning("fincaraiz: %s falló: %s", url, e)
                        break
                    titulo, items = _items(r.text)
                    if pag == 1 and clave(m["nombre"]) not in clave(titulo):
                        log.warning("fincaraiz: %s no corresponde a %s (%r)", url, m["nombre"], titulo)
                        break
                    nuevos = [it for it in items if it.get("url") not in vistos]
                    if not nuevos:
                        break
                    for it in nuevos:
                        vistos.add(it.get("url"))
                        a = _anuncio(it, tipo, m["nombre"], m["departamento"])
                        if a:
                            salida.append(a)
                    if len(items) < 21:
                        break
                log.info("fincaraiz: %s %s -> %d anuncios", m["nombre"], seg, len(salida) - n0)
    return salida
