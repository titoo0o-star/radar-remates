"""Lectura de avisos de remate en texto libre (Contraloría, Banco Agrario, El Martillo)."""
import re

from .normalizar import a_entero, a_float, matricula

MESES = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}
MESES["setiembre"] = 9


def fecha_es(texto: str | None) -> str | None:
    """'jueves 19 de noviembre de 2026' / '13 de agosto 2024' / '2026-11-20 14:30' -> AAAA-MM-DD."""
    if not texto:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:de(?:l)?\s+)?(\d{4})", texto, re.I)
    if m and m.group(2).lower() in MESES:
        return f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def campo(texto: str, *etiquetas: str, hasta: str = r"\n") -> str | None:
    """Valor tras 'Etiqueta:' en un aviso (primera etiqueta que aparezca)."""
    for e in etiquetas:
        # la etiqueta debe empezar una línea (evita "Ciudad" dentro de "ciudadanía")
        m = re.search(rf"(?:^|\n)[ \t]*{e}\s*:?\s*(.+?)(?:{hasta}|$)", texto, re.I | re.S)
        if m and m.group(1).strip(" .:"):
            return m.group(1).strip(" .:")
    return None


def area_m2(texto: str) -> float | None:
    """Área construida o privada mencionada en el texto ('Área privada: 78.10 m²', '120 m2')."""
    for rx in (r"[áa]rea\s+(?:construida|privada|total construida)[^\d]{0,25}([\d.,]+)\s*m",
               r"([\d.,]+)\s*(?:m2|m²|mts2|metros cuadrados)"):
        m = re.search(rx, texto, re.I)
        if m:
            v = a_float(m.group(1))
            if v and 5 <= v <= 20000:
                return v
    return None


def matricula_en(texto: str) -> str | None:
    m = re.search(r"(?:matr[íi]cula(?:\s+inmobiliaria)?|M\.?\s?I\.?|FMI|folio)\s*(?:No\.?|N[°º]\.?|número)?\s*:?\s*"
                  r"(\d{2,3}[A-Z]?\s?-\s?\d{3,9})", texto, re.I)
    return matricula(m.group(1).replace(" ", "")) if m else None


def pesos(texto: str | None) -> int | None:
    if not texto:
        return None
    m = re.search(r"\$\s*([\d.,]{5,})", texto)
    return a_entero(m.group(1)) if m else a_entero(texto)


def porcentaje(texto: str | None) -> float | None:
    m = re.search(r"([\d.,]+)\s*%", texto or "")
    return a_float(m.group(1)) if m else None


def municipio_en(texto: str):
    """Busca en texto libre un municipio del alcance ('…municipio de Envigado, Antioquia…').
    Prefiere el que sigue a 'municipio de' / 'ciudad de'; si no, el primero que aparezca.
    Devuelve (ciudad, departamento, area_metro) o None."""
    from .normalizar import _indice, clave, ubicar_municipio
    t = clave(texto)
    m = re.search(r"\b(?:municipio|ciudad|distrito) de ([a-z ]{3,40}?)(?: departamento| d c|$| (?:antioquia|cundinamarca|"
                  r"valle|atlantico|bolivar|santander)\b)", t)
    if m:
        u = ubicar_municipio(m.group(1).strip())
        if u:
            return u
    mejor = None
    for k, cands in _indice().items():
        i = t.find(" " + k + " ")
        if i >= 0 and (mejor is None or i < mejor[0]):
            mejor = (i, cands[0])
    return mejor[1] if mejor else None
