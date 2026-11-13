"""Busca el precio/m² de mercado de un inmueble y calcula margen y margen neto."""
import json

from common.config import DATA
from common.normalizar import clave


def cargar_mercado(path=None) -> dict | None:
    p = path or DATA / "mercado.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def referencia(mercado: dict, ciudad: str, barrio: str | None, tipo: str, min_n: int):
    """(mediana_m2, n, nivel) con la regla: barrio si tiene ≥ min_n anuncios, si no la ciudad."""
    if barrio:
        b = mercado.get("barrios", {}).get(f"{clave(ciudad)}|{clave(barrio)}|{tipo}")
        if b and b["n"] >= min_n:
            return b["mediana_m2"], b["n"], "barrio"
    c = mercado.get("ciudades", {}).get(f"{clave(ciudad)}|{tipo}")
    if c:
        return c["mediana_m2"], c["n"], "ciudad"
    return None, 0, None


def margen_neto(precio: int, valor_mercado: float, judicial: bool, costos: dict) -> float:
    """1 − costo_total ÷ ingreso_neto_venta.

    costo_total   = precio + escritura/registro (+ impuesto de remate si es judicial)
                    + remodelación + tenencia (sobre el valor de mercado)
    ingreso_neto  = valor_mercado × (1 − descuento_cierre) × (1 − comisión_venta)
    Es el análogo neto de margen_pct = 1 − precio ÷ valor_mercado.
    """
    c = costos
    compra = precio * (1 + c["escritura_registro"] + (c["impuesto_remate"] if judicial else 0))
    obra = valor_mercado * c["remodelacion"]
    tenencia = valor_mercado * c["tenencia_costo_mensual"] * c["tenencia_meses"]
    ingreso = valor_mercado * (1 - c["descuento_cierre"]) * (1 - c["comision_venta"])
    return 1 - (compra + obra + tenencia) / ingreso


def aplicar(filas: list[dict], mercado: dict | None, cfg: dict) -> None:
    min_n = cfg["mercado"]["min_comparables_barrio"]
    for r in filas:
        r.update(precio_m2_mercado=None, margen_pct=None, margen_neto_pct=None,
                 comparables_n=0, mercado_nivel=None)
        if not mercado or not r.get("ciudad"):
            continue
        med, n, nivel = referencia(mercado, r["ciudad"], r.get("barrio"), r["tipo"], min_n)
        r["comparables_n"], r["mercado_nivel"] = n, nivel
        if not med:
            continue
        r["precio_m2_mercado"] = int(round(med))
        if r.get("precio_m2"):
            r["margen_pct"] = round(1 - r["precio_m2"] / med, 4)
            vm = med * r["area_m2"]
            r["margen_neto_pct"] = round(
                margen_neto(r["precio_compra"], vm, r.get("remate_judicial"), cfg["costos"]), 4)
