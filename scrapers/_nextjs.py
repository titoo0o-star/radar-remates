"""Utilidades para leer los datos que Next.js incrusta en el HTML (self.__next_f)."""
import json
import re

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)


def flight(html: str) -> str:
    return "".join(json.loads('"' + c + '"') for c in _PUSH.findall(html))


def objeto_tras(texto: str, marcador: str, desde: int = 0):
    """Decodifica el objeto/array JSON que empieza justo después de `marcador`."""
    i = texto.find(marcador, desde)
    if i < 0:
        return None
    j = i + len(marcador)
    while texto[j] not in "[{":
        j += 1
    obj, _ = json.JSONDecoder().raw_decode(texto[j:])
    return obj
