"""Banco Agrario — remates judiciales publicados en bancoagrario.gov.co/remates-judiciales.

Cada aviso trae avalúo, postura (valor mínimo), fecha, juzgado, radicación y la descripción
del bien (con su matrícula "M.I. No. …"). Casi todo es rural (prioridad baja): se filtra por
tipo y por municipio del alcance mencionado en la descripción. Se omiten remates ya pasados.

La venta de bienes en dación de pago se publica en PDFs por convocatoria; la última cerró en
febrero de 2025, así que no se procesa.
"""
import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from common.avisos import area_m2, campo, fecha_es, matricula_en, municipio_en, pesos
from common.esquema import fila
from common.normalizar import tipo_inmueble

log = logging.getLogger("agrario")

URL = "https://www.bancoagrario.gov.co/remates-judiciales"
MAX_PAGINAS = 20
_SEP = re.compile(r"PERMITE INFORMAR A QUIEN INTERESE", re.I)


def _avisos(http):
    vistos = set()
    for page in range(MAX_PAGINAS):
        html = http.get(URL, params={"page": page}).text
        texto = BeautifulSoup(html, "lxml").get_text("\n", strip=True)
        bloques = [b for b in _SEP.split(texto)[1:] if "remate" in b.lower()]
        nuevos = [b for b in bloques if b[:300] not in vistos]
        if not nuevos:
            break
        for b in nuevos:
            vistos.add(b[:300])
            yield page, b
        if f"page={page + 1}" not in html:
            break


def _fila(page: int, b: str) -> dict | None:
    bien = campo(b, r"BIEN A REMATAR", hasta=r"\n(?:[A-ZÁÉÍÓÚ ]{6,}:|apartment|$)") or b
    tipo = tipo_inmueble(bien[:200])
    if not tipo:
        return None
    u = municipio_en(bien)
    if not u:
        return None
    ciudad, departamento, area_metro = u
    # formatos: "Fecha de remate\n19/11/2026" o un rótulo vacío y luego "FECHA REMATE: 13 de agosto 2024"
    m = re.search(r"FECHA (?:DE(?:L)? )?REMATE\s*:\s*([^\n]+)", b, re.I)
    fecha = fecha_es(m.group(1)) if m else fecha_es(campo(b, r"Fecha de remate"))
    if fecha and fecha < date.today().isoformat():
        return None
    radic = campo(b, r"RADICACI[OÓ]N")
    juzgado = campo(b, r"JUZGADO")
    return fila(
        "agrario", re.sub(r"\s+", "", radic or bien[:40]),
        matricula=matricula_en(bien), titulo=f"{tipo.title()} – {juzgado or 'remate judicial'}"[:120],
        tipo=tipo, ciudad=ciudad, departamento=departamento, area_metro=area_metro,
        direccion=None, area_m2=area_m2(bien),
        precio_compra=pesos(campo(b, r"Postura")), avaluo=pesos(campo(b, r"Aval[uú]o")),
        modalidad="subasta", remate_judicial=True, fecha_subasta=fecha,
        url=f"{URL}?page={page}",
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    filas, n = [], 0
    for page, b in _avisos(http):
        n += 1
        r = _fila(page, b)
        if r:
            filas.append(r)
            if limite and len(filas) >= limite:
                break
    log.info("Banco Agrario: %d avisos revisados, %d en el alcance", n, len(filas))
    return filas
