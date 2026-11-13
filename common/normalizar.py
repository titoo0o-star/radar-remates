"""Normalización de ciudades, tipos, números y matrículas."""
import re
import unicodedata
from functools import lru_cache

from .config import load_config


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def clave(s: str | None) -> str:
    """Texto comparable: sin tildes, minúsculas, solo letras/números y espacios."""
    if not s:
        return ""
    s = sin_tildes(str(s)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Alias de departamentos que publican los portales
_ALIAS_DEPTO = {
    "bogota": "bogota d c", "bogota d c": "bogota d c", "distrito capital": "bogota d c",
    "bogota dc": "bogota d c", "cundinamarca": "cundinamarca", "antioquia": "antioquia",
    "valle": "valle del cauca", "valle del cauca": "valle del cauca", "atlantico": "atlantico",
    "bolivar": "bolivar", "santander": "santander",
}
# Alias de municipios
_ALIAS_MPIO = {
    "santiago de cali": "cali", "cartagena de indias": "cartagena", "bogota d c": "bogota",
    "bogota dc": "bogota", "san juan de giron": "giron", "itagui": "itagui",
    "san jose de cucuta": "cucuta",
}


@lru_cache(maxsize=1)
def _indice():
    """clave(municipio) -> lista de (ciudad, departamento, area_metro)."""
    idx: dict[str, list[tuple[str, str, str]]] = {}
    for area, info in load_config()["areas_metropolitanas"].items():
        for m in info["municipios"]:
            idx.setdefault(clave(m["nombre"]), []).append((m["nombre"], m["departamento"], area))
    return idx


def ubicar_municipio(municipio: str | None, departamento: str | None = None):
    """Devuelve (ciudad, departamento, area_metro) si el municipio está en el alcance, si no None.

    Si se conoce el departamento, debe coincidir (evita confundir Caldas-Antioquia con el
    departamento de Caldas, Mosquera-Nariño con Mosquera-Cundinamarca, etc.).
    """
    k = clave(municipio)
    k = _ALIAS_MPIO.get(k, k)
    cands = _indice().get(k)
    if not cands:
        return None
    if departamento:
        kd = clave(departamento)
        kd = _ALIAS_DEPTO.get(kd, kd)
        for c in cands:
            if clave(c[1]) == kd:
                return c
        # Bogotá a veces viene con depto "Cundinamarca"
        if k == "bogota":
            return cands[0]
        return None
    return cands[0]


def tipo_inmueble(texto: str | None) -> str | None:
    """'apartamento', 'local' o None (fuera del alcance)."""
    t = clave(texto)
    if not t:
        return None
    if re.search(r"\b(apartaestudio|apartamento|apto|apartamentos|penthouse|duplex)\b", t):
        return "apartamento"
    if re.search(r"\blocal(es)?\b", t) and "lote" not in t.split()[:1]:
        return "local"
    return None


def a_entero(v) -> int | None:
    """'$ 1.234.567,89' / 1234567.89 -> 1234568."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(round(v)) if v == v else None
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    # formato colombiano: puntos de miles, coma decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.search(r"\.\d{3}$", s):
        s = s.replace(".", "")
    elif "," in s:
        s = s.replace(",", "." if re.search(r",\d{1,2}$", s) else "")
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def a_float(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    s = re.sub(r"[^\d,.]", "", str(v))
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def matricula(v: str | None) -> str | None:
    if not v:
        return None
    s = re.sub(r"\s+", "", str(v)).upper()
    return s or None


def ocupacion(v: str | None) -> str:
    k = clave(v)
    if not k:
        return "sin_dato"
    if "desocup" in k or k in ("no", "libre"):
        return "desocupado"
    if "ocup" in k or "habitado" in k or "arrend" in k:
        return "ocupado"
    return "sin_dato"


_CORTE_BARRIO = re.compile(
    r"\s+(?:-\s|GJ\b|GARAJE|GARAJES|DEP\b|DEPOSITO|DEPÓSITO|PARQ|PARQUEADERO|LOCAL\b|OFICINA|"
    r"MZ\b|MANZANA|AP\b|APTO|APARTAMENTO|INT\b|INTERIOR|TORRE|ETAPA|SECT|SECTOR|CONJUNTO|"
    r"EDIFICIO|EDIF\b|URBANIZACI|AGRUPACI|P\.?\s?H\b|UBICAD|SOBRE|ENTRE|CON\b)|\s*\d|[,;_/.()]",
    re.I)


_PREFIJO_BARRIO = re.compile(
    r"^(?:barrio|br|b/|urbanizaci[oó]n|urb|ub|conjunto|conj|sector|sect|ciudadela|cdla)\.?\s+", re.I)


def limpiar_barrio(s: str | None) -> str | None:
    """'MIRAMAR GARAJE T3-503' -> 'Miramar'; 'CAPELLANIA - FONTIBON GJ 375' -> 'Capellania'."""
    if not s:
        return None
    s = _PREFIJO_BARRIO.sub("", s.strip())
    s = _CORTE_BARRIO.split(" " + s, maxsplit=1)[0].strip(" -")
    if len(s) < 3:
        return None
    return re.sub(r"\b(Ii{0,2}|Iv|Vi{0,3})\b", lambda m: m.group(0).upper(), s.title())
