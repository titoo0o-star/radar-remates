#!/usr/bin/env python3
"""Corre todas las fuentes, normaliza, quita duplicados, calcula márgenes y valida.

Uso:
  python run_all.py                       # todas las fuentes de config.yaml
  python run_all.py --fuentes sae --limite 20 --prueba
      --prueba escribe en data/prueba/ y no toca remates.json ni el historial
  python run_all.py --solo-margenes
      recalcula márgenes de data/remates.json con el mercado.json y config.yaml actuales
"""
import argparse
import csv
import importlib
import json
import logging
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from common.config import DATA, LOGS, load_config
from common.esquema import CAMPOS, validar
from common.geo import Geocoder
from common.http import Http
from mercado.actualizar import cargar_anuncios
from mercado.referencia import aplicar, cargar_mercado

log = logging.getLogger("run_all")


def configurar_logs():
    LOGS.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stderr),
              logging.FileHandler(LOGS / f"run_{date.today().isoformat()}.log", encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)


def correr_fuente(nombre: str, cfg: dict, limite: int | None) -> list[dict]:
    t0 = time.time()
    mod = importlib.import_module(f"scrapers.{nombre}")
    filas = mod.scrape(Http(cfg), cfg, limite=limite)
    log.info("%s: %d filas en %.0f s", nombre, len(filas), time.time() - t0)
    return filas


def quitar_duplicados(filas: list[dict]) -> list[dict]:
    """Únicos por id y por matrícula (se queda el de menor precio; anota las otras fuentes)."""
    por_id = {}
    for r in filas:
        por_id.setdefault(r["id"], r)
    por_mat, salida = {}, []
    for r in por_id.values():
        m = r.get("matricula")
        if not m:
            salida.append(r)
            continue
        if m in por_mat:
            otro = por_mat[m]
            pr = lambda x: x["precio_compra"] or float("inf")   # sin precio publicado pierde el empate
            mejor, peor = (r, otro) if pr(r) < pr(otro) else (otro, r)
            mejor.setdefault("tambien_en", [])
            mejor["tambien_en"].append(peor["id"])
            por_mat[m] = mejor
            log.info("Duplicado por matrícula %s: %s y %s", m, r["id"], otro["id"])
        else:
            por_mat[m] = r
    return salida + list(por_mat.values())


def ubicar(filas: list[dict], cfg: dict) -> None:
    """Coordenadas para las filas que no las traen (cruce de vías -> barrio -> ciudad)."""
    g = Geocoder(cfg)
    faltan = [r for r in filas if not (r.get("lat") and r.get("precision_ubicacion") == "exacta")]
    log.info("Ubicando %d inmuebles sin coordenadas exactas", len(faltan))
    for i, r in enumerate(filas):
        g.ubicar(r)
        if g.nuevas and g.nuevas % 50 == 0:
            g.guardar()
    g.guardar()


def conteo_anterior(fuente: str) -> int | None:
    p = DATA / "remates.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        prev = json.load(f)
    return sum(1 for r in prev if r["fuente"] == fuente)


def marcar_novedades(filas: list[dict], previas: list[dict] | None, fuentes_corridas: set[str]) -> dict:
    """Compara con la corrida anterior: marca `nuevo` y `primera_vista` en cada fila y guarda en
    data/salidos.json los inmuebles que desaparecieron (vendidos o retirados) de las fuentes que
    sí corrieron hoy. Devuelve un resumen por fuente."""
    hoy = date.today().isoformat()
    prev = {r["id"]: r for r in (previas or [])}
    resumen = {}
    for r in filas:
        p = prev.get(r["id"])
        if p:
            r["primera_vista"] = p.get("primera_vista") or p.get("fecha_scrapeo") or hoy
            # sigue siendo "nuevo" si apareció en los últimos 7 días
            r["nuevo"] = r["primera_vista"] >= (date.today() - timedelta(days=7)).isoformat() and bool(p.get("nuevo"))
        else:
            r["primera_vista"] = hoy
            r["nuevo"] = bool(prev)          # en la primera corrida no hay con qué comparar
        if r["nuevo"]:
            resumen.setdefault(r["fuente"], {"nuevos": 0, "salidos": 0})["nuevos"] += 1
    actuales = {r["id"] for r in filas}
    salidos = [dict(p, fecha_salida=hoy) for k, p in prev.items()
               if k not in actuales and p["fuente"] in fuentes_corridas]
    for p in salidos:
        resumen.setdefault(p["fuente"], {"nuevos": 0, "salidos": 0})["salidos"] += 1
    ruta = DATA / "salidos.json"
    historico = []
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            historico = json.load(f)
    limite = (date.today() - timedelta(days=90)).isoformat()
    historico = [x for x in historico if x.get("fecha_salida", "") >= limite] + salidos
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=1)
    with open(DATA / "novedades.json", "w", encoding="utf-8") as f:
        json.dump({"fecha": hoy, "nuevos": sum(v["nuevos"] for v in resumen.values()),
                   "salidos": len(salidos), "por_fuente": resumen}, f, ensure_ascii=False, indent=1)
    return resumen


def guardar(filas: list[dict], carpeta: Path, historial: bool):
    carpeta.mkdir(parents=True, exist_ok=True)
    filas = sorted(filas, key=lambda r: (r["margen_pct"] is None, -(r["margen_pct"] or 0)))
    with open(carpeta / "remates.json", "w", encoding="utf-8") as f:
        json.dump(filas, f, ensure_ascii=False, indent=1)
    campos = CAMPOS + ["tambien_en"]
    with open(carpeta / "remates.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in filas:
            w.writerow({**r, "tambien_en": ";".join(r.get("tambien_en", [])),
                        "revisar": "; ".join(r.get("revisar") or [])})
    if historial:
        h = DATA / "historial"
        h.mkdir(exist_ok=True)
        with open(h / f"remates_{date.today().isoformat()}.json", "w", encoding="utf-8") as f:
            json.dump(filas, f, ensure_ascii=False)


def resumen(filas: list[dict]) -> str:
    def pct(n, d):
        return f"{100 * n / d:.0f}%" if d else "-"
    out = []
    for fuente in sorted({r["fuente"] for r in filas}):
        fs = [r for r in filas if r["fuente"] == fuente]
        n = len(fs)
        vacios = [c for c in CAMPOS if c not in ("margen_neto_pct",) and all(r.get(c) in (None, "") for r in fs)]
        out.append(
            f"{fuente:12s} total={n:5d}  área={pct(sum(1 for r in fs if r['area_m2']), n)}  "
            f"margen={pct(sum(1 for r in fs if r['margen_pct'] is not None), n)}  "
            f"margen5+={pct(sum(1 for r in fs if r['margen_pct'] is not None and r['comparables_n'] >= 5), n)}  "
            f"dirección={pct(sum(1 for r in fs if r['direccion']), n)}  "
            f"coords={pct(sum(1 for r in fs if r['lat']), n)}\n"
            f"{'':12s} sin extraer: {', '.join(vacios) or 'ninguno'}"
        )
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuentes", help="lista separada por comas (por defecto, las de config.yaml)")
    ap.add_argument("--limite", type=int, help="máximo de inmuebles por fuente (pruebas)")
    ap.add_argument("--prueba", action="store_true", help="escribe en data/prueba/")
    ap.add_argument("--solo-margenes", action="store_true",
                    help="no scrapea: recalcula márgenes sobre data/remates.json")
    args = ap.parse_args()

    configurar_logs()
    cfg = load_config()

    if args.solo_margenes:
        with open(DATA / "remates.json", encoding="utf-8") as f:
            filas = json.load(f)
        ubicar(filas, cfg)
        aplicar(filas, cargar_mercado(), cfg, cargar_anuncios())
        guardar(filas, DATA, historial=False)
        print(resumen(filas))
        return
    fuentes = args.fuentes.split(",") if args.fuentes else cfg["fuentes"]

    todas, ok = [], set()
    for nombre in fuentes:
        try:
            filas = correr_fuente(nombre, cfg, args.limite)
        except Exception:
            log.exception("La fuente %s falló; las demás siguen", nombre)
            continue
        ok.add(nombre)
        if not args.prueba and not args.limite:
            prev = conteo_anterior(nombre)
            if prev and len(filas) < prev / 2:
                log.warning("ALERTA %s: trajo %d filas, menos de la mitad de la corrida anterior (%d)",
                            nombre, len(filas), prev)
        todas.extend(filas)

    # Se conservan las filas de la corrida anterior de las fuentes que no corrieron hoy
    # (o que fallaron), con su fecha_scrapeo original.
    if not args.prueba and (DATA / "remates.json").exists():
        with open(DATA / "remates.json", encoding="utf-8") as f:
            previas = [r for r in json.load(f) if r["fuente"] not in ok]
        if previas:
            log.info("Se conservan %d filas anteriores de: %s", len(previas),
                     ", ".join(sorted({r["fuente"] for r in previas})))
            todas.extend(previas)

    validas = []
    for r in todas:
        problemas = validar(r)
        if problemas:
            log.warning("Fila descartada %s: %s", r.get("id"), "; ".join(problemas))
        else:
            validas.append(r)

    validas = quitar_duplicados(validas)
    ubicar(validas, cfg)
    aplicar(validas, cargar_mercado(), cfg, cargar_anuncios())

    destino = DATA / "prueba" if args.prueba else DATA
    if not args.prueba:
        previas = None
        if (DATA / "remates.json").exists():
            with open(DATA / "remates.json", encoding="utf-8") as f:
                previas = json.load(f)
        res = marcar_novedades(validas, previas, ok)
        for fuente, v in sorted(res.items()):
            log.info("Novedades %s: %d nuevos, %d salidos", fuente, v["nuevos"], v["salidos"])
    guardar(validas, destino, historial=not args.prueba)
    log.info("Guardadas %d filas en %s", len(validas), destino)
    print(resumen(validas))
    tipos = Counter((r["area_metro"], r["tipo"]) for r in validas)
    print("Por área y tipo:", dict(tipos))


if __name__ == "__main__":
    main()
