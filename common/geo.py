"""Ubicación de inmuebles con Nominatim (OpenStreetMap), con caché en data/geocache.json.

Nominatim no conoce las placas colombianas: con "Calle 19 # 13A-12" devuelve un tramo
cualquiera de la Calle 19. Pero la nomenclatura dice dónde está: sobre la Calle 19, en el
cruce con la Carrera 13A. Por eso se piden las geometrías de las dos vías y se calcula su
intersección (precisión ≈ una cuadra) -> precision_ubicacion = "exacta".

Respaldo: centro del barrio ("barrio") y, si tampoco, centro de la ciudad ("ciudad").
Máximo 1 petición por segundo (política de uso de Nominatim).
"""
import json
import logging
import math
import re
import time

import requests

from .config import DATA, load_config
from .normalizar import clave

log = logging.getLogger("geo")

URL = "https://nominatim.openstreetmap.org/search"
UA = "radar-remates/0.1 (geocodificacion de inmuebles; uso personal)"
CACHE = DATA / "geocache.json"
MAX_CRUCE_M = 80        # distancia máxima entre las dos vías para aceptar el cruce
MAX_PAGINAS_VIA = 5    # hasta 200 tramos por vía
MAX_CIUDAD_KM = 45      # un punto a más de esto del centro del área no es de esa ciudad

_TIPOS = [  # (regex, nombre en OSM, tipo de vía que la cruza)
    (r"AV(?:ENIDA)?\.?\s*(?:CALLE|CL)|AC", "Avenida Calle", "Carrera"),
    (r"AV(?:ENIDA)?\.?\s*(?:CARRERA|KR|CR|CRA)|AK", "Avenida Carrera", "Calle"),
    (r"CALLE|CLL|CL", "Calle", "Carrera"),
    (r"CARRERA|KRA|CRA|KR|CR|K", "Carrera", "Calle"),
    (r"DIAGONAL|DG|DIAG", "Diagonal", "Transversal"),
    (r"AVENIDA|AV", "Avenida", "Calle"),
    (r"TRANSVERSAL|TV|TR|TRANSV", "Transversal", "Diagonal"),
]
_NUM = r"(\d{1,3}\s?[A-H]?(?:\s?BIS)?(?:\s?[A-H])?)"
_CARD = r"(?:\s+(SUR|ESTE|NORTE|NORT|NTE|OESTE))?"


def _num(s: str) -> str:
    s = re.sub(r"\s+", "", s.upper())
    s = s.replace("BIS", " Bis ")
    return re.sub(r"\s+", " ", s).strip()


def parsear(direccion: str):
    """'CL 22 A 72 B - 48 Apto 305' -> ('Calle 22A', ['Carrera 72B', 'Transversal 72B'])."""
    d = clave(direccion).upper()
    d = re.sub(r"(\d)N\b", r"\1 NORTE", d)          # Cali: 54N -> 54 NORTE
    d = re.sub(r"\b(NO|NRO|NUM)\b", " ", d)
    d = re.sub(r"\bN\b(?=\s*\d)", " ", d)           # "N 15-88" (número), no "3 N" (norte)
    d = re.sub(r"(\d)\s+N\b", r"\1 NORTE", d)
    for rx, nombre, cruce in _TIPOS:
        # el cardinal de la vía que cruza puede ir antes o después de la placa:
        # "54 NORTE 55" (Cali) o "38 27 SUR" (Bogotá)
        m = re.match(rf"^\s*(?:{rx})\s+{_NUM}{_CARD}\s+{_NUM}{_CARD}\s+\d{{1,3}}{_CARD}\b", d)
        if not m:
            continue
        card = {"NORT": "Norte", "NTE": "Norte"}
        c1 = card.get(m.group(2), (m.group(2) or "").title())
        g4 = m.group(4) or m.group(5)
        c2 = card.get(g4, (g4 or "").title())
        via = f"{nombre} {_num(m.group(1))}" + (f" {c1}" if c1 else "")
        sufijo = f" {c2}" if c2 else ""
        tc = "Carrera" if cruce in ("Carrera", "Transversal") else "Calle"
        alt = "Transversal" if tc == "Carrera" else "Diagonal"
        n = _num(m.group(3))
        return via, [f"{tc} {n}{sufijo}", f"{alt} {n}{sufijo}"]
    return None


class Geocoder:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self._t = 0.0
        self.cache = {}
        if CACHE.exists():
            with open(CACHE, encoding="utf-8") as f:
                self.cache = json.load(f)
        self.nuevas = 0

    def guardar(self):
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False)

    def _get(self, params):
        espera = 1.1 - (time.monotonic() - self._t)
        if espera > 0:
            time.sleep(espera)
        try:
            r = self.s.get(URL, params={**params, "format": "jsonv2", "countrycodes": "co"}, timeout=40)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("Nominatim falló (%s): %s", params.get("q"), e)
            return None
        finally:
            self._t = time.monotonic()

    def _centro_area(self, area):
        return self.cfg["areas_metropolitanas"][area]["centro"]

    def _cerca(self, lat, lon, area):
        c = self._centro_area(area)
        return _m((lat, lon), tuple(c)) / 1000 <= MAX_CIUDAD_KM

    def _via(self, nombre, ciudad):
        """Lista de polilíneas [(lat, lon), ...] de la vía en la ciudad (con caché)."""
        k = f"via|{clave(ciudad)}|{clave(nombre)}"
        if k in self.cache:
            return self.cache[k]
        # Nominatim devuelve máx. 40 tramos por consulta: se pagina excluyendo los ya vistos
        j, vistos = [], []
        for _ in range(MAX_PAGINAS_VIA):
            params = {"q": f"{nombre}, {ciudad}", "limit": 40, "dedupe": 0,
                      "polygon_geojson": 1, "polygon_threshold": 0.00003}
            if vistos:
                params["exclude_place_ids"] = ",".join(vistos)
            pag = self._get(params)
            if pag is None:
                return []       # error de red: no se guarda en caché
            j += pag
            vistos += [str(x["place_id"]) for x in pag]
            if len(pag) < 40:
                break
        objetivo = clave(nombre)
        lineas = []
        for x in j:
            if x.get("category") != "highway" or not _mismo_nombre(clave(x.get("name")), objetivo):
                continue
            g = x.get("geojson") or {}
            if g.get("type") == "LineString":
                lineas.append([(round(p[1], 6), round(p[0], 6)) for p in g["coordinates"]])
            elif g.get("type") == "MultiLineString":
                lineas += [[(round(p[1], 6), round(p[0], 6)) for p in l] for l in g["coordinates"]]
        self.cache[k] = lineas
        self.nuevas += 1
        return lineas

    def _variantes(self, nombre, ciudad):
        """Tramos de 'Calle 19' + 'Avenida Calle 19' (en OSM el tramo arterial suele llamarse así)."""
        base = nombre.replace("Avenida ", "") if nombre.startswith("Avenida C") else nombre
        lineas = list(self._via(base, ciudad))
        if base.startswith(("Calle ", "Carrera ")):
            lineas += self._via("Avenida " + base, ciudad)
        return lineas

    def _cruce(self, via, cruces, ciudad, area):
        A = self._variantes(via, ciudad)
        if not A:
            return None
        for c in cruces:
            B = self._variantes(c, ciudad)
            mejor = None
            for la in A:
                for lb in B:
                    for i in range(len(la) - 1):
                        for j in range(len(lb) - 1):
                            d, p = _dist_seg(la[i], la[i + 1], lb[j], lb[j + 1])
                            if mejor is None or d < mejor[0]:
                                mejor = (d, p)
            if mejor and mejor[0] <= MAX_CRUCE_M and self._cerca(*mejor[1], area):
                return mejor[1]
        return None

    def _lugar(self, texto):
        k = f"lugar|{clave(texto)}"
        if k in self.cache:
            return self.cache[k]
        j = self._get({"q": texto, "limit": 1})
        if j is None:
            return None
        v = (float(j[0]["lat"]), float(j[0]["lon"])) if j else None
        self.cache[k] = v
        self.nuevas += 1
        return v

    def ubicar(self, r: dict) -> None:
        """Completa lat, lon y precision_ubicacion de una fila (in place)."""
        area, ciudad = r.get("area_metro"), r.get("ciudad")
        if not area:
            return
        if r.get("lat") and r.get("lon") and self._cerca(r["lat"], r["lon"], area):
            r["precision_ubicacion"] = r.get("precision_ubicacion") or "exacta"
            return
        r["lat"] = r["lon"] = None
        p = parsear(r["direccion"]) if r.get("direccion") else None
        if p:
            k = f"dir|{clave(ciudad)}|{clave(p[0])}|{clave(p[1][0])}"
            if k in self.cache:
                pt = self.cache[k]
            else:
                pt = self._cruce(p[0], p[1], ciudad, area)
                self.cache[k] = pt
            if pt:
                r["lat"], r["lon"], r["precision_ubicacion"] = pt[0], pt[1], "exacta"
                return
        if r.get("barrio"):
            pt = self._lugar(f"{r['barrio']}, {ciudad}")
            if pt and self._cerca(*pt, area):
                r["lat"], r["lon"], r["precision_ubicacion"] = pt[0], pt[1], "barrio"
                return
        pt = self._lugar(f"{ciudad}, {r.get('departamento') or ''}")
        if not (pt and self._cerca(*pt, area)):
            pt = tuple(self._centro_area(area))
        r["lat"], r["lon"], r["precision_ubicacion"] = pt[0], pt[1], "ciudad"


def _mismo_nombre(nombre: str, objetivo: str) -> bool:
    """'calle 57 bolivia' sirve para 'calle 57'; 'calle 57 sur' o 'calle 57a' no."""
    if nombre == objetivo:
        return True
    if not nombre.startswith(objetivo + " "):
        return False
    resto = nombre[len(objetivo) + 1:].split()[0]
    return resto not in {"sur", "este", "norte", "oeste", "bis", "n"} and not re.fullmatch(r"[a-h]|\d+", resto)


def _m(a, b):
    """Distancia aproximada en metros (plano local)."""
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])))


def _dist_seg(p1, p2, q1, q2):
    """Distancia mínima (m) entre dos segmentos y el punto medio del par más cercano."""
    lat0 = p1[0]
    kx = 111320 * math.cos(math.radians(lat0))
    P1, P2 = (p1[1] * kx, p1[0] * 111320), (p2[1] * kx, p2[0] * 111320)
    Q1, Q2 = (q1[1] * kx, q1[0] * 111320), (q2[1] * kx, q2[0] * 111320)
    # descarte rápido por caja
    if (max(P1[0], P2[0]) + MAX_CRUCE_M < min(Q1[0], Q2[0]) or max(Q1[0], Q2[0]) + MAX_CRUCE_M < min(P1[0], P2[0])
            or max(P1[1], P2[1]) + MAX_CRUCE_M < min(Q1[1], Q2[1]) or max(Q1[1], Q2[1]) + MAX_CRUCE_M < min(P1[1], P2[1])):
        return float("inf"), None
    x = _interseccion(P1, P2, Q1, Q2)
    if x:
        return 0.0, (x[1] / 111320, x[0] / kx)
    cands = [(_pt_seg(P1, Q1, Q2)), (_pt_seg(P2, Q1, Q2)), (_pt_seg(Q1, P1, P2)), (_pt_seg(Q2, P1, P2))]
    d, a, b = min(cands, key=lambda c: c[0])
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    return d, (my / 111320, mx / kx)


def _pt_seg(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    L = ax * ax + ay * ay
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L))
    c = (a[0] + t * ax, a[1] + t * ay)
    return math.hypot(p[0] - c[0], p[1] - c[1]), p, c


def _interseccion(p1, p2, q1, q2):
    r = (p2[0] - p1[0], p2[1] - p1[1])
    s = (q2[0] - q1[0], q2[1] - q1[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((q1[0] - p1[0]) * s[1] - (q1[1] - p1[1]) * s[0]) / den
    u = ((q1[0] - p1[0]) * r[1] - (q1[1] - p1[1]) * r[0]) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (p1[0] + t * r[0], p1[1] + t * r[1])
    return None
