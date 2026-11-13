#!/usr/bin/env python3
"""Descarga anuncios de mercado y calcula medianas de precio/m².

Uso:
  python -m mercado.actualizar                 # todas las fuentes de mercado
  python -m mercado.actualizar --fuentes tu360
  python -m mercado.actualizar --solo-medianas # recalcula con los anuncios ya guardados

Salidas:
  data/anuncios/{fuente}.json  anuncios crudos normalizados (uno por fuente)
  data/mercado.json            medianas por ciudad+tipo y ciudad+barrio+tipo, con n
"""
import argparse
import importlib
import json
import logging
import statistics
from collections import defaultdict
from datetime import date

from common.config import DATA, load_config
from common.http import Http
from common.normalizar import clave

log = logging.getLogger("mercado")
ANUNCIOS = DATA / "anuncios"
FUENTES_MERCADO = ["tu360"]  # luego: fincaraiz, metrocuadrado

# Rangos plausibles de precio/m² (COP) y área para descartar errores de digitación
LIMITES = {"apartamento": (800_000, 35_000_000, 18, 1500),
           "local": (500_000, 60_000_000, 4, 5000)}


def plausible(a: dict) -> bool:
    lo, hi, amin, amax = LIMITES[a["tipo"]]
    return amin <= a["area_m2"] <= amax and lo <= a["precio"] / a["area_m2"] <= hi


def cargar_anuncios() -> list[dict]:
    todos = []
    for f in sorted(ANUNCIOS.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            todos.extend(json.load(fh))
    # mismo inmueble publicado en dos portales: se deja uno (ciudad, tipo, área, precio)
    unicos = {}
    for a in todos:
        unicos.setdefault((a["ciudad"], a["tipo"], round(a["area_m2"]), a["precio"]), a)
    return [a for a in unicos.values() if plausible(a)]


def medianas(anuncios: list[dict]) -> dict:
    ciudades, barrios = defaultdict(list), defaultdict(list)
    nombres = {}
    for a in anuncios:
        m2 = a["precio"] / a["area_m2"]
        kc = f"{clave(a['ciudad'])}|{a['tipo']}"
        ciudades[kc].append(m2)
        nombres[kc] = {"ciudad": a["ciudad"], "tipo": a["tipo"], "area_metro": a["area_metro"]}
        if a.get("barrio"):
            kb = f"{clave(a['ciudad'])}|{clave(a['barrio'])}|{a['tipo']}"
            barrios[kb].append(m2)
            nombres[kb] = {"ciudad": a["ciudad"], "barrio": a["barrio"], "tipo": a["tipo"],
                           "area_metro": a["area_metro"]}

    def resumen(grupos):
        return {k: {**nombres[k], "mediana_m2": int(statistics.median(v)), "n": len(v)}
                for k, v in sorted(grupos.items())}

    return {
        "generado": date.today().isoformat(),
        "anuncios_total": len(anuncios),
        "por_fuente": dict(sorted(_contar(anuncios, "fuente").items())),
        "ciudades": resumen(ciudades),
        "barrios": resumen(barrios),
    }


def _contar(xs, k):
    c = defaultdict(int)
    for x in xs:
        c[x[k]] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuentes")
    ap.add_argument("--solo-medianas", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    if not args.solo_medianas:
        ANUNCIOS.mkdir(parents=True, exist_ok=True)
        for nombre in (args.fuentes.split(",") if args.fuentes else FUENTES_MERCADO):
            try:
                filas = importlib.import_module(f"mercado.{nombre}").scrape(Http(cfg), cfg)
            except Exception:
                log.exception("Fuente de mercado %s falló", nombre)
                continue
            if not filas:
                log.error("%s no trajo anuncios; se conserva el archivo anterior", nombre)
                continue
            with open(ANUNCIOS / f"{nombre}.json", "w", encoding="utf-8") as f:
                json.dump(filas, f, ensure_ascii=False)
            log.info("%s: %d anuncios guardados", nombre, len(filas))

    anuncios = cargar_anuncios()
    if not anuncios:
        log.error("No hay anuncios de mercado; data/mercado.json no se modifica")
        return
    m = medianas(anuncios)
    with open(DATA / "mercado.json", "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    log.info("mercado.json: %d anuncios válidos, %d grupos de ciudad, %d de barrio",
             len(anuncios), len(m["ciudades"]), len(m["barrios"]))
    for k, v in m["ciudades"].items():
        print(f"  {v['ciudad']:15s} {v['tipo']:12s} mediana {v['mediana_m2']:>12,} $/m²  n={v['n']}")


if __name__ == "__main__":
    main()
