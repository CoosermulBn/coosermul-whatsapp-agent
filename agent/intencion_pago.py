# agent/intencion_pago.py — Detecta si un mensaje expresa intención de pago

"""
Detecta, con reglas simples (sin IA, para que sea predecible), si el
mensaje de un socio pide los datos para pagar o expresa que quiere pagar:
número de cuenta, cuentas de abono, dónde depositar, cómo pagar, "quiero
pagar mi deuda", etc. Cuando es así, el bot le envía automáticamente el PDF
de las cuentas de abono.

Se evita disparar cuando el socio:
- afirma que YA pagó o que está pagando ("ya pagué", "estoy abonando"),
- niega ("no voy a pagar"),
- da SU PROPIA cuenta ("mi número de cuenta es ...", "depositen en mi cuenta"),
- habla de otra cosa con la misma palabra ("buen pagador", "cancelar mi
  afiliación", "formas de pago" de un producto del bazar).
"""

import re
import unicodedata

_PALABRAS_PAGO = (
    "abono|abonos|abonar|pago|pagos|pagar|deposito|depositos|depositar|"
    "transferencia|transferencias|transferir|transfiero|cancelo"
)
_VERBOS_PAGO = "pago|pagar|deposito|depositar|abono|abonar|transfiero|transferir|cancelo"
_DEUDA = (
    "cuota|cuotas|deuda|saldo|prestamo|credito|sobregiro|monto|total|"
    "pendiente|descuento|mensualidad|aporte|aportes"
)

# "cuenta(s)" junto a una palabra de pago/banco
_CUENTA_Y_PAGO = re.compile(
    rf"\bcuentas?\b.*\b(?:{_PALABRAS_PAGO}|bancaria|bancarias|interbancaria|cci|bcp|bbva|interbank|scotiabank)\b"
    rf"|\b(?:{_PALABRAS_PAGO}|bancaria|bancarias|interbancaria|cci|bcp|bbva|interbank|scotiabank)\b.*\bcuentas?\b"
)
_NUMERO_DE_CUENTA = re.compile(r"\b(?:numero|numeros|nro|num|n)\s+de\s+cuentas?\b")
_PREGUNTA_CUENTA = re.compile(
    r"\b(?:a|en)\s+(?:que|cual|cuales)\s+cuentas?\b"
    r"|\bcual(?:es)?\s+(?:es|son)\s+(?:la|las|el|los)\s+(?:cuentas?|numeros?\s+de\s+cuentas?)\b"
    r"|\bcuentas?\s+bancarias?\b"
)
_MEDIOS = re.compile(r"\b(?:cci|interbancaria|yape|yapear|yapeo|plin)\b")
_CUENTA_PROPIA = re.compile(r"\bmi\s+(?:numero\s+de\s+|nro\s+de\s+|n\s+de\s+)?cuentas?\b|\b(?:en|a)\s+mi\s+cuenta\b")
_NUMERO_LARGO = re.compile(r"\d{10,}")

_DONDE = re.compile(rf"\b(?:donde|adonde|a\s+donde|en\s+donde|por\s+donde)\b(?:\s+\w+){{0,6}}?\s+(?:{_VERBOS_PAGO})\b")
_COMO = re.compile(rf"\bcomo\b(?:\s+\w+){{0,4}}?\s+(?:{_VERBOS_PAGO}|regularizo|regularizar)\b")
_COMO_CANCELAR = re.compile(rf"\bcomo\b(?:\s+\w+){{0,3}}?\s+cancelar\b(?:\s+\w+){{0,3}}?\s+(?:{_DEUDA})\b")

_YA_PAGO = re.compile(
    r"\bya\s+(?:\w+\s+)?(?:pague|pago|deposite|deposito|cancele|cancelo|transferi|abone|abono|hice|realice|efectue|envie|cumpli)\b"
    r"|\b(?:pague|deposite|cancele|transferi|abone|efectue|realice)\b"
    r"|\b(?:estoy|vengo|sigo|estamos)\s+(?:pagando|abonando|depositando|cancelando)\b"
)
_NIEGA = re.compile(r"\bno\s+(?:me\s+)?(?:quiero|voy|puedo|pienso|deseo|debo|tengo|podre|alcanza)\b")

_INTENCION = [
    # "quiero / voy a / necesito / puedo ... pagar / depositar / abonar / transferir"
    re.compile(
        r"\b(?:quiero|quisiera|queria|deseo|voy\s+a|vamos\s+a|iba\s+a|necesito|necesitamos|puedo|podria|"
        r"podemos|debo|tengo\s+que|me\s+gustaria|ire\s+a|procedo\s+a|para|favor)\b(?:\s+\w+){0,3}?\s+"
        r"(?:pagar|depositar|abonar|transferir|regularizar)\b"
    ),
    # "hacer / realizar / efectuar el pago | depósito | abono | transferencia" (también conjugado)
    re.compile(
        r"\b(?:hacer|realizar|efectuar|hago|realizo|efectuo|hare|realizare|efectuare)\b"
        r"(?:\s+\w+){0,2}?\s+(?:pago|deposito|abono|transferencia)\b"
    ),
    # "mañana estaré abonando", "debo estar cancelando la deuda", "estaré poniéndome al día"
    re.compile(
        r"\b(?:estare|estaremos|estaria|debo\s+estar|voy\s+a\s+estar|vamos\s+a\s+estar)\s+"
        r"(?:pagando|abonando|depositando|cancelando|regularizando|poniendome)\b"
    ),
    # "pagar / depositar / abonar / transferir" seguido de algo que se debe
    re.compile(rf"\b(?:pagar|depositar|abonar|transferir)\b(?:\s+\w+){{0,3}}?\s+(?:{_DEUDA}|inscripcion|bolsa|ticket|rifa|rifas|pavo|canasta)\b"),
    # cancelar (= pagar) solo si se refiere a una deuda; "cancelar mi afiliación" no cuenta
    re.compile(rf"\bcancelar\b(?:\s+\w+){{0,3}}?\s+(?:{_DEUDA})\b"),
    re.compile(r"\bponerme\s+al\s+(?:dia|corriente)\b"),
    # el infinitivo suelto ("¿puedo pagar con yape?", "para depositar")
    re.compile(r"\b(?:pagar|depositar|abonar|transferir)\b"),
]


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _pide_cuentas(t: str) -> bool:
    if _MEDIOS.search(t) and not _NUMERO_LARGO.search(t):
        return True
    if _CUENTA_PROPIA.search(t) or _NUMERO_LARGO.search(t):
        return False
    return bool(_CUENTA_Y_PAGO.search(t) or _NUMERO_DE_CUENTA.search(t) or _PREGUNTA_CUENTA.search(t))


def expresa_intencion_de_pago(texto: str) -> bool:
    """True si el mensaje pide datos para pagar o dice que quiere pagar."""
    t = _normalizar(texto)
    if not t:
        return False
    if _pide_cuentas(t) or _DONDE.search(t) or _COMO.search(t) or _COMO_CANCELAR.search(t):
        return True
    if _YA_PAGO.search(t) or _NIEGA.search(t):
        return False
    return any(p.search(t) for p in _INTENCION)
