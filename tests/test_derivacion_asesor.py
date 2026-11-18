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

from urllib.parse import quote

LINKS = ("https://wa.me/51996899924", "https://wa.me/51996899927")


class ProveedorFalso:
    def __init__(self):
        self.entrante = []
        self.enviados = []
        self.url_botones = []
        self.falla_boton_url = False

    async def parsear_webhook(self, request):
        return self.entrante

    async def enviar_mensaje(self, tel, texto):
        self.enviados.append(texto)
        return True

    async def enviar_documento(self, *a, **k):
        return True

    async def enviar_botones(self, *a, **k):
        return True

    async def enviar_boton_url(self, tel, texto, titulo, url):
        self.url_botones.append((titulo, url))
        return not self.falla_boton_url

    async def enviar_lista(self, *a, **k):
        return True


class ClienteFalso:
    """Claude pide usar escalar_a_humano ante cualquier mensaje."""

    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        bloque = SimpleNamespace(type="tool_use", name="escalar_a_humano", id="t1",
                                 input={"motivo": "pide ayuda económica urgente",
                                       "mensaje_para_asesor": "Hola, necesito ayuda urgente para mi medicina"})
        return SimpleNamespace(stop_reason="tool_use", content=[bloque],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))


prov = ProveedorFalso()
main.proveedor = prov
brain.client = ClienteFalso()
cliente = TestClient(main.app)
asyncio.run(memory.inicializar_db())


def recibe(tel, texto, **kw):
    prov.enviados.clear()
    prov.url_botones.clear()
    prov.entrante = [MensajeEntrante(telefono=tel, texto=texto, mensaje_id="x", es_propio=False, **kw)]
    assert cliente.post("/webhook", json={}).status_code == 200
    return list(prov.enviados)


def botones_ok(esperado_texto):
    """Dos botones (uno por asesor), hacia wa.me, con la consulta ya escrita."""
    b = prov.url_botones
    return (
        len(b) == 2
        and [t for t, _ in b] == ["Hablar con Asesor 1", "Hablar con Asesor 2"]
        and all(u.startswith(l + "?text=" + quote(esperado_texto, safe="")) for (_, u), l in zip(b, LINKS))
    )


def probar():
    fallos = []

    def check(nombre, cond):
        if not cond:
            fallos.append(nombre)

    # 1) tema no autorizado: Claude escala -> botones de los dos asesores (sin URL
    #    larga a la vista), sin modo humano
    r = recibe("51900000101", "Por favor ayúdeme necesito urgente para mi medicina")
    check("1 deriva con dos botones y la consulta escrita",
          botones_ok("Hola, necesito ayuda urgente para mi medicina"))
    check("1 no muestra links en texto", not any("wa.me" in t for t in r))
    check("1 no queda en modo humano", not asyncio.run(memory.esta_en_modo_humano("51900000101")))
    # 2) sigue escribiendo: el bot sigue respondiendo (no queda mudo)
    recibe("51900000101", "Sin efectivo")
    check("2 vuelve a derivar", len(prov.url_botones) == 2)
    # 3) botón "Sí, hablar con un asesor": botones y sin modo humano
    r = recibe("51900000102", "Sí", tipo="boton", boton_id="asesor_si")
    check("3 boton asesor: dos botones", len(prov.url_botones) == 2)
    check("3 boton asesor: sin modo humano", not asyncio.run(memory.esta_en_modo_humano("51900000102")))
    # 4) botón con la consulta en el id: el link lleva ese texto ya escrito
    frase = "Hola, quiero información sobre mi Crédito a Cuenta de Gratificaciones"
    recibe("51900000103", "Sí", tipo="boton", boton_id="asesor_si|" + frase)
    check("4 link con la consulta del botón", botones_ok(frase))
    # 5) botón viejo (sin consulta): usa lo último que escribió el socio
    asyncio.run(memory.guardar_mensaje("51900000104", "user", "Quiero información del crédito para la gratificación"))
    asyncio.run(memory.guardar_mensaje("51900000104", "assistant", "Antes de enviarte los documentos..."))
    recibe("51900000104", "Sí", tipo="boton", boton_id="asesor_si")
    check("5 botón viejo: cita lo último que escribió",
          botones_ok("Hola, necesito atención de un asesor. Mi consulta: Quiero información del crédito para la gratificación"))
    # 6) la herramienta de pedir boleta ya no muestra un link: el botón Sí lleva la consulta
    res = brain._ejecutar_herramienta("pedir_boleta_y_ofrecer_asesor", {"tramite": "tu Crédito a Cuenta de Gratificaciones"})
    ids = [o["id"] for o in res["botones"]["opciones"]]
    check("6 id del botón con la consulta", ids[0] == "asesor_si|Hola, quiero información sobre mi Crédito a Cuenta de Gratificaciones")
    check("6 el mensaje no trae URL", "http" not in res["botones"]["mensaje"])
    # 7) si WhatsApp rechaza el botón, el socio recibe igual el link en texto
    prov.falla_boton_url = True
    r = recibe("51900000105", "Estoy de vacaciones")
    prov.falla_boton_url = False
    check("7 respaldo: links en texto", len(r) == 2 and all(l in " ".join(r) for l in LINKS))
    return fallos


def test_derivacion_asesor():
    assert probar() == []


if __name__ == "__main__":
    fallos = probar()
    for f in fallos:
        print("FALLA:", f)
    print("todo ok" if not fallos else f"{len(fallos)} con problemas")
    sys.exit(1 if fallos else 0)
