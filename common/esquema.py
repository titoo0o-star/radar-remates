"""Esquema común de salida. Todos los scrapers devuelven dicts con estos campos."""
from datetime import date

CAMPOS = [
    "id", "fuente", "codigo", "matricula", "titulo", "tipo",
    "ciudad", "departamento", "barrio", "area_metro", "direccion",
    "lat", "lon", "precision_ubicacion",
    "area_m2", "precio_compra", "precio_m2",
    "precio_m2_mercado", "margen_pct", "margen_neto_pct", "comparables_n", "mercado_nivel",
    "revisar", "avaluo", "modalidad", "remate_judicial", "fecha_subasta", "estado_ocupacion",
    "url", "fecha_scrapeo",
]
# Campos extra frente al esquema pedido:
#   area_metro      -> área metropolitana (selector de ciudad de la app)
#   margen_neto_pct -> margen después de costos (config.yaml)
#   mercado_nivel   -> 'barrio' o 'ciudad' (si el barrio tenía < 5 anuncios)
#   remate_judicial -> True solo en remates judiciales (aplica impuesto_remate)
#   revisar         -> motivos para desconfiar del margen (pocos comparables, tamaño atípico…)

TIPOS = {"apartamento", "local"}
MODALIDADES = {"subasta", "puja_electronica", "venta_directa"}
OCUPACION = {"ocupado", "desocupado", "sin_dato"}
PRECISION = {"exacta", "barrio", "ciudad", None}


def fila(fuente: str, codigo: str, **kw) -> dict:
    r = {c: None for c in CAMPOS}
    r.update(fuente=fuente, codigo=str(codigo), id=f"{fuente}:{codigo}",
             comparables_n=0, estado_ocupacion="sin_dato", remate_judicial=False,
             fecha_scrapeo=date.today().isoformat())
    r.update(kw)
    if r["area_m2"] and r["precio_compra"]:
        r["precio_m2"] = int(round(r["precio_compra"] / r["area_m2"]))
    return r


def validar(r: dict) -> list[str]:
    """Lista de problemas (vacía si la fila es válida para guardarse)."""
    p = []
    if r.get("tipo") not in TIPOS:
        p.append(f"tipo inválido {r.get('tipo')!r}")
    if r.get("modalidad") not in MODALIDADES:
        p.append(f"modalidad inválida {r.get('modalidad')!r}")
    if r.get("estado_ocupacion") not in OCUPACION:
        p.append("estado_ocupacion inválido")
    if not r.get("ciudad"):
        p.append("sin ciudad")
    if not isinstance(r.get("precio_compra"), int) or r["precio_compra"] <= 0:
        p.append("sin precio_compra")
    if not r.get("url"):
        p.append("sin url")
    return p
