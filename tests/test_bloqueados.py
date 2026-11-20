# tests/test_bloqueados.py — python tests/test_bloqueados.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.bloqueados import esta_bloqueado

assert esta_bloqueado("51933098149")
assert esta_bloqueado("+51 933 098 149")
assert esta_bloqueado("933098149")
assert not esta_bloqueado("51933098148")
assert not esta_bloqueado("51996899924")
assert not esta_bloqueado("")
print("OK")
