# tests/test_identidad.py — python tests/test_identidad.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.identidad import con_identidad, INICIO, CIERRE

t = con_identidad("Hola, te cuento del crédito.")
assert t.startswith(INICIO) and t.endswith(CIERRE) and "Hola, te cuento" in t

# No duplica el inicio si ya se presenta
t = con_identidad("¡Hola! Soy Soporte Coosermul, el asistente virtual de Coosermul BN.")
assert t.count("asistente virtual") == 1 and t.endswith(CIERRE)

# No duplica contactos
t = con_identidad("Escríbenos: https://wa.me/51996899924 o https://wa.me/51996899927")
assert t.startswith(INICIO) and t.count("wa.me/51996899924") == 1
t = con_identidad("Mayor información al N° 996899924 ó N° 996899927.")
assert t.count("996899924") == 1

# Sin cierre (mensajes con botones de contacto)
t = con_identidad("Toca el botón.", con_cierre=False)
assert t.startswith(INICIO) and "wa.me" not in t

# Vacío se queda vacío; idempotente
assert con_identidad("") == ""
assert con_identidad(con_identidad("Hola")) == con_identidad("Hola")
print("OK")
