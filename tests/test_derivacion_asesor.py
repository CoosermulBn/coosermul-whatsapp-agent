# tests/test_derivacion_asesor.py — python tests/test_derivacion_asesor.py
# Cuando el bot no puede (o no está autorizado a) responder, deriva al socio
# a los links de WhatsApp de los asesores y NO se queda mudo (sin modo humano).
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
os.chdir(RAIZ)
sys.path.insert(0, RAIZ)

from fastapi.testclient import TestClient

from agent import brain, main, memory
from agent.providers.base import MensajeEntrante

LINKS = ("https://wa.me/51996899924", "https://wa.me/51996899927")


class ProveedorFalso:
    def __init__(self):
        self.entrante = []
        self.enviados = []

    async def parsear_webhook(self, request):
        return self.entrante

    async def enviar_mensaje(self, tel, texto):
        self.enviados.append(texto)
        return True

    async def enviar_documento(self, *a, **k):
        return True

    async def enviar_botones(self, *a, **k):
        return True

    async def enviar_lista(self, *a, **k):
        return True


class ClienteFalso:
    """Claude pide usar escalar_a_humano ante cualquier mensaje."""

    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        bloque = SimpleNamespace(type="tool_use", name="escalar_a_humano", id="t1",
                                 input={"motivo": "pide ayuda económica urgente"})
        return SimpleNamespace(stop_reason="tool_use", content=[bloque],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))


prov = ProveedorFalso()
main.proveedor = prov
brain.client = ClienteFalso()
cliente = TestClient(main.app)
asyncio.run(memory.inicializar_db())


def recibe(tel, texto, **kw):
    prov.enviados.clear()
    prov.entrante = [MensajeEntrante(telefono=tel, texto=texto, mensaje_id="x", es_propio=False, **kw)]
    assert cliente.post("/webhook", json={}).status_code == 200
    return list(prov.enviados)


def probar():
    fallos = []

    def check(nombre, cond):
        if not cond:
            fallos.append(nombre)

    # 1) tema no autorizado: Claude escala -> links de los dos asesores, sin modo humano
    r = recibe("51900000101", "Por favor ayúdeme necesito urgente para mi medicina")
    check("1 deriva con los dos links", len(r) == 1 and all(l in r[0] for l in LINKS))
    check("1 no queda en modo humano", not asyncio.run(memory.esta_en_modo_humano("51900000101")))
    # 2) sigue escribiendo: el bot sigue respondiendo (no queda mudo)
    r = recibe("51900000101", "Sin efectivo")
    check("2 vuelve a derivar", len(r) == 1 and all(l in r[0] for l in LINKS))
    # 3) botón "Sí, hablar con un asesor": links y sin modo humano
    r = recibe("51900000102", "Sí", tipo="boton", boton_id="asesor_si")
    check("3 boton asesor: links", len(r) == 1 and all(l in r[0] for l in LINKS))
    check("3 boton asesor: sin modo humano", not asyncio.run(memory.esta_en_modo_humano("51900000102")))
    return fallos


def test_derivacion_asesor():
    assert probar() == []


if __name__ == "__main__":
    fallos = probar()
    for f in fallos:
        print("FALLA:", f)
    print("todo ok" if not fallos else f"{len(fallos)} con problemas")
    sys.exit(1 if fallos else 0)
