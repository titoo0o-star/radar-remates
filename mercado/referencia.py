"""Busca el precio/m² de mercado de un inmueble y calcula margen y margen neto.

Niveles, en orden (`mercado_nivel`):
  barrio  -> mediana de anuncios del mismo barrio, ciudad y tipo (si hay ≥ min_comparables)
  radio   -> mediana de anuncios del mismo tipo a ≤ radio_km del inmueble (si hay ≥ min)
  radio2  -> igual, a ≤ 2 × radio_km
  ciudad  -> mediana de la ciudad y tipo (respaldo; se marca)
"""
import json
import math
import statistics
from collections import defaultdict

from common.config import DATA
from common.normalizar import clave


def cargar_mercado(path=None) -> dict | None:
    p = path or DATA / "mercado.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class IndiceRadio:
    """Anuncios con coordenadas en una grilla de ~1 km para buscar vecinos rápido."""
    CELDA = 0.01  # grados ≈ 1,1 km

    def __init__(self, anuncios: list[dict]):
        self.g = defaultdict(list)
        for a in anuncios:
            if a.get("lat") and a.get("lon"):
                self.g[(a["tipo"], int(a["lat"] / self.CELDA), int(a["lon"] / self.CELDA))].append(
                    (a["lat"], a["lon"], a["precio"] / a["area_m2"], a["area_m2"]))

    def vecinos(self, tipo, lat, lon, radio_km, area=None, min_n=5) -> list[float]:
        """$/m² de los anuncios a ≤ radio_km. Si hay suficientes de tamaño parecido
        (0,5× a 2× el área), solo esos: el $/m² cambia mucho con el tamaño, sobre todo en locales."""
        todos = self._vecinos(tipo, lat, lon, radio_km)
        if area:
            parecidos = [m2 for m2, a in todos if area / 2 <= a <= area * 2]
            if len(parecidos) >= min_n:
                return parecidos
        return [m2 for m2, _ in todos]

    def _vecinos(self, tipo, lat, lon, radio_km):
        r = math.ceil(radio_km / 1.1)
        ci, cj = int(lat / self.CELDA), int(lon / self.CELDA)
        out = []
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                for la, lo, m2, a in self.g.get((tipo, i, j), ()):
                    if _km(lat, lon, la, lo) <= radio_km:
                        out.append((m2, a))
        return out


def _km(a1, o1, a2, o2):
    p = math.pi / 180
    h = (math.sin((a2 - a1) * p / 2) ** 2
         + math.cos(a1 * p) * math.cos(a2 * p) * math.sin((o2 - o1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def referencia(mercado, r: dict, min_n: int, indice: IndiceRadio | None, radio_km: float):
    """(mediana_m2, n, nivel)."""
    ciudad, barrio, tipo = r["ciudad"], r.get("barrio"), r["tipo"]
    if barrio:
        b = mercado.get("barrios", {}).get(f"{clave(ciudad)}|{clave(barrio)}|{tipo}")
        if b and b["n"] >= min_n:
            return b["mediana_m2"], b["n"], "barrio"
    if indice and radio_km and r.get("lat") and r.get("precision_ubicacion") == "exacta":
        for rk in (radio_km, 2 * radio_km):   # primero 1 km; si no alcanza, 2 km
            v = indice.vecinos(tipo, r["lat"], r["lon"], rk, r.get("area_m2"), min_n)
            if len(v) >= min_n:
                return statistics.median(v), len(v), "radio" if rk == radio_km else "radio2"
    c = mercado.get("ciudades", {}).get(f"{clave(ciudad)}|{tipo}")
    if c:
        return c["mediana_m2"], c["n"], "ciudad"
    return None, 0, None


def _alertas(r, n, nivel) -> list[str]:
    """Motivos para desconfiar del margen (se muestran en la ficha de la app)."""
    out = []
    if nivel == "ciudad":
        out.append("comparado con la mediana de la ciudad")
    elif n < 10:
        out.append(f"solo {n} comparables")
    a = r.get("area_m2")
    if a and (a > 1000 or a < 15):
        out.append("tamaño atípico frente a los anuncios")
    if r.get("precio_m2") and r["precio_m2"] / max(1, r.get("precio_m2_mercado") or 1) < 0.3:
        out.append("precio menor al 30% del mercado: verificar en el portal")
    return out


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


def aplicar(filas: list[dict], mercado: dict | None, cfg: dict, anuncios: list[dict] | None = None) -> None:
    mc = cfg["mercado"]
    min_n, radio = mc["min_comparables_barrio"], mc.get("radio_km", 0)
    indice = IndiceRadio(anuncios) if anuncios and radio else None
    for r in filas:
        r.update(precio_m2_mercado=None, margen_pct=None, margen_neto_pct=None,
                 comparables_n=0, mercado_nivel=None, revisar=[])
        if not mercado or not r.get("ciudad"):
            continue
        med, n, nivel = referencia(mercado, r, min_n, indice, radio)
        r["comparables_n"], r["mercado_nivel"] = n, nivel
        if not med:
            continue
        r["precio_m2_mercado"] = int(round(med))
        r["revisar"] = _alertas(r, n, nivel)
        if r.get("precio_m2"):
            r["margen_pct"] = round(1 - r["precio_m2"] / med, 4)
            vm = med * r["area_m2"]
            r["margen_neto_pct"] = round(
                margen_neto(r["precio_compra"], vm, r.get("remate_judicial"), cfg["costos"]), 4)
