# agent/identidad.py — Deja claro que quien responde es un asistente virtual.

"""
Algunos usuarios no entienden que están hablando con un asistente virtual.
Toda respuesta de TEXTO del bot se envía:

  - empezando con "Soy un asistente virtual." y
  - terminando con "Para mayor información contáctanos a: <links de WhatsApp>".

Se hace en código (no en el prompt) para que salga siempre igual, y se guarda
en el historial el texto SIN estos añadidos para que el modelo no los imite.
"""

INICIO = "🤖 *Soy un asistente virtual.*"
LINKS = "https://wa.me/51996899924 o https://wa.me/51996899927"
CIERRE = f"Para mayor información contáctanos a: {LINKS}"


def _ya_dice_asistente(texto: str) -> bool:
    return "asistente virtual" in texto[:150].lower()


def _ya_trae_contacto(texto: str) -> bool:
    t = texto.lower()
    return "wa.me/" in t or "996899924" in t or "996 899 924" in t


def con_identidad(texto: str, con_cierre: bool = True) -> str:
    """Devuelve el texto con el inicio y el cierre obligatorios.

    No duplica nada si el texto ya se presenta como asistente virtual o ya
    incluye los contactos de los asesores. `con_cierre=False` es para mensajes
    que van acompañados de botones de contacto (los botones hacen de cierre).
    """
    texto = (texto or "").strip()
    if not texto:
        return texto
    partes = []
    if not _ya_dice_asistente(texto):
        partes.append(INICIO)
    partes.append(texto)
    if con_cierre and not _ya_trae_contacto(texto):
        partes.append(CIERRE)
    return "\n\n".join(partes)
