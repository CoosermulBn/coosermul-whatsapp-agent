"""Números bloqueados: el bot NO les responde ni guarda sus mensajes, y el
panel no les envía plantillas masivas.

La lista vive en config/numeros_bloqueados.txt (un número por línea; se
admiten comentarios con # y cualquier formato: +51 933 098 149, 51933098149,
933098149). Para bloquear a otro, agregue su línea y despliegue. También se
puede sumar números sin tocar el repo con la variable de entorno
NUMEROS_BLOQUEADOS (separados por coma)."""
import os
import re
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "config" / "numeros_bloqueados.txt"


def _clave(numero: str) -> str:
    """Compara por los últimos 9 dígitos (ignora el prefijo de país)."""
    return re.sub(r"\D", "", numero or "")[-9:]


def _cargar() -> set[str]:
    claves = set()
    try:
        for linea in RUTA.read_text(encoding="utf-8").splitlines():
            linea = linea.split("#", 1)[0].strip()
            if linea and _clave(linea):
                claves.add(_clave(linea))
    except FileNotFoundError:
        pass
    for n in os.getenv("NUMEROS_BLOQUEADOS", "").split(","):
        if _clave(n):
            claves.add(_clave(n))
    return claves


def esta_bloqueado(telefono: str) -> bool:
    clave = _clave(telefono)
    return len(clave) == 9 and clave in _cargar()
