"""BBVA — remates judiciales en los que BBVA Colombia es el acreedor.

El sitio del banco (www.bbva.com.co, con su "Sala de Ventas" de remates en PDF) bloquea las
peticiones desde servidores en la nube (403), y su perfil de vendedor en Fincaraíz no tiene
anuncios activos. La vía disponible es rematesjudiciales.click, que publica los avisos de
remate judicial y los etiqueta por acreedor ("Remates Judiciales Banco BBVA Colombia").

Ese sitio es de pago: sin membresía muestra tipo de bien, ciudad, base de licitación, fecha
y, a veces, el avalúo en el resumen. Solo se usa esa parte pública (no se intenta acceder al
contenido protegido). Sin área publicada no hay margen: la fila entra como pista con una
nota y ubicación aproximada (centro de la ciudad).
"""
import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from common.avisos import fecha_es, municipio_en
from common.esquema import fila
from common.normalizar import a_entero, tipo_inmueble, ubicar_municipio

log = logging.getLogger("bbva")

BASE = "https://rematesjudiciales.click/tag/bbva-colombia/"
MAX_PAGINAS = 20
NOTA = ("Remate judicial en el que BBVA es acreedor (publicado en rematesjudiciales.click). La dirección, "
        "el área y el juzgado no son públicos en ese sitio: consultar el aviso de remate o la membresía del sitio.")


def _articulos(http):
    for page in range(1, MAX_PAGINAS + 1):
        url = BASE if page == 1 else f"{BASE}page/{page}/"
        try:
            r = http.get(url)
        except Exception:
            break   # una página inexistente responde 404: fin del listado
        soup = BeautifulSoup(r.text, "lxml")
        arts = soup.find_all("article")
        if not arts:
            break
        for a in arts:
            link = a.find("a", href=True)
            titulo = (a.find(["h1", "h2", "h3"]) or a).get_text(" ", strip=True)
            yield {"titulo": titulo, "url": link["href"] if link else url, "texto": a.get_text(" ", strip=True)}


def _fila(art: dict, http) -> dict | None:
    t = art["titulo"]
    tipo = tipo_inmueble(t.split(" en ")[0])
    if not tipo:
        return None
    m = re.search(r"\ben\s+(.+?)(?:,?\s+Base\b|\.\s|$)", t, re.I)
    lugar = m.group(1) if m else ""
    partes = [p.strip(" .") for p in lugar.split(",")]
    u = ubicar_municipio(re.sub(r"(?i)\s*d\.?\s*c\.?$", "", partes[0]), partes[1] if len(partes) > 1 else None) \
        or municipio_en(t)
    if not u:
        return None
    ciudad, departamento, area_metro = u
    base = re.search(r"(?i)base\s+licitaci[oó]n\s*\$\s*([\d.,]+)", t)
    fecha = re.search(r"(?i)\bel\s+(\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4})", t)
    # el resumen público de la ficha a veces trae el avalúo
    avaluo = None
    try:
        det = BeautifulSoup(http.get(art["url"]).text, "lxml").get_text(" ", strip=True)
        a = re.search(r"(?i)aval[uú]o\s*:?\s*\$\s*([\d.,]{6,})", det)
        avaluo = a_entero(a.group(1)) if a else None
    except Exception as e:
        log.warning("bbva: ficha %s falló: %s", art["url"], e)
    slug = art["url"].rstrip("/").rsplit("/", 1)[-1]
    return fila(
        "bbva", slug[:80], titulo=t[:120], tipo=tipo,
        ciudad=ciudad, departamento=departamento, area_metro=area_metro,
        precio_compra=a_entero(base.group(1)) if base else None, avaluo=avaluo,
        modalidad="subasta", remate_judicial=True,
        fecha_subasta=fecha_es(fecha.group(1)) if fecha else None,
        nota=NOTA, url=art["url"],
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    filas, n, vistos = [], 0, set()
    for art in _articulos(http):
        if art["url"] in vistos:
            continue
        vistos.add(art["url"])
        n += 1
        r = _fila(art, http)
        if r and r["precio_compra"] and (not r["fecha_subasta"] or r["fecha_subasta"] >= date.today().isoformat()):
            filas.append(r)
            if limite and len(filas) >= limite:
                break
    log.info("BBVA: %d remates publicados con BBVA como acreedor, %d en el alcance", n, len(filas))
    return filas
