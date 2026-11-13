"""Contraloría General de la República — remates de cobro coactivo (judiciales).

La página "Remates de la CGR › Inmuebles" enlaza un aviso por remate ("Remate: Apartamento en
Bogotá el 19 de noviembre"). Cada aviso trae, con etiquetas fijas: fecha, tipo de inmueble,
matrícula, dirección, ciudad, porcentaje a rematar, área, avalúo y valor mínimo para postura
(70% del avalúo). Volumen bajo (unos pocos por mes).

Es remate judicial: aplica impuesto_remate en el margen neto. Si se remata menos del 100% del
inmueble (cuota parte), se descarta, igual que en CISA y Davivienda.
"""
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common.avisos import area_m2, campo, fecha_es, matricula_en, pesos, porcentaje
from common.esquema import fila
from common.normalizar import tipo_inmueble, ubicar_municipio

log = logging.getLogger("contraloria")

LISTA = ("https://www.contraloria.gov.co/control-fiscal/responsabilidad-fiscal/"
         "jurisdiccion-coactiva/remates-cgr/inmuebles")


def _avisos(http) -> list[tuple[str, str]]:
    soup = BeautifulSoup(http.get(LISTA).text, "lxml")
    vistos, out = set(), []
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if re.match(r"(?i)^remate\s*:", t):
            url = urljoin(LISTA, a["href"]).split("?")[0]
            if url not in vistos:
                vistos.add(url)
                out.append((t, url))
    return out


def _fila(titulo: str, url: str, texto: str) -> dict | None:
    tipo = tipo_inmueble(campo(texto, r"Predio", r"Tipo de inmueble")) or tipo_inmueble(titulo)
    if not tipo:
        return None
    pct = porcentaje(campo(texto, r"Porcentaje a rematar"))
    if pct is not None and pct < 100:
        log.info("Contraloría: se omite %s (remata el %s%%)", titulo, pct)
        return None
    ciudad_txt = campo(texto, r"Ciudad", r"Municipio")
    depto = campo(texto, r"Departamento")
    u = ubicar_municipio(ciudad_txt, depto) or ubicar_municipio(re.sub(r"[,(].*", "", ciudad_txt or ""))
    if not u:
        return None
    ciudad, departamento, area_metro = u
    # el número del proceso va en el encabezado del aviso ("AVISO DE REMATES PCC J-1028");
    # el menú lateral menciona otros procesos, por eso se busca primero "PCC"
    proceso = re.search(r"PCC\s*([A-Z]-?\d{2,6})", texto) or re.search(r"Proceso\s*([A-Z]-?\d{2,6})", texto)
    codigo = proceso.group(1) if proceso else url.rstrip("/").rsplit("/", 1)[-1][:60]
    return fila(
        "contraloria", codigo,
        matricula=matricula_en(texto), titulo=titulo.replace("Remate:", "").strip(),
        tipo=tipo, ciudad=ciudad, departamento=departamento, area_metro=area_metro,
        direccion=campo(texto, r"Direcci[oó]n Registrada", r"Direcci[oó]n"),
        area_m2=area_m2(texto),
        precio_compra=pesos(campo(texto, r"Valor m[ií]nimo para postura[^:$]*")),
        avaluo=pesos(campo(texto, r"Valor aval[uú]o[^:$]*")),
        modalidad="subasta", remate_judicial=True,
        fecha_subasta=fecha_es(campo(texto, r"Fecha del Remate")),
        url=url,
    )


def scrape(http, cfg, limite: int | None = None) -> list[dict]:
    filas = []
    avisos = _avisos(http)
    log.info("Contraloría: %d avisos de remate de inmuebles publicados", len(avisos))
    for titulo, url in avisos:
        texto = BeautifulSoup(http.get(url).text, "lxml").get_text("\n", strip=True)
        r = _fila(titulo, url, texto)
        if r:
            filas.append(r)
            if limite and len(filas) >= limite:
                break
    return filas
