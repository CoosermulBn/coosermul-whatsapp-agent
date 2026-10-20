# tests/test_flujo_pagos.py — python tests/test_flujo_pagos.py
# Simula mensajes entrantes (proveedor falso, base temporal, sin llamar a Claude
# ni a Meta) y verifica cuándo se envían automáticamente las cuentas de abono.
import asyncio
import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
os.chdir(RAIZ)
sys.path.insert(0, RAIZ)

from fastapi.testclient import TestClient

from agent import main, memory
from agent.providers.base import MensajeEntrante

CUENTAS = "Cuentas de Abono - Coosermul BN.pdf"


class ProveedorFalso:
    def __init__(self):
        self.entrante = []
        self.enviados = []

    async def parsear_webhook(self, request):
        return self.entrante

    async def validar_webhook(self, request):
        return None

    async def enviar_mensaje(self, tel, texto):
        self.enviados.append(("texto", texto))
        return True

    async def enviar_documento(self, tel, ruta, nombre, caption=""):
        self.enviados.append(("doc", nombre))
        return True

    async def enviar_botones(self, *a, **k):
        return True

    async def enviar_lista(self, *a, **k):
        return True


async def _claude_falso(texto, historial):
    return {"texto": "RESPUESTA_DE_CLAUDE", "documentos": [], "escalar": False,
            "motivo_escalamiento": "", "botones": None, "lista": None}


prov = ProveedorFalso()
main.proveedor = prov
main.generar_respuesta = _claude_falso
cliente = TestClient(main.app)
asyncio.run(memory.inicializar_db())


def guardar(tel, role, contenido):
    asyncio.run(memory.guardar_mensaje(tel, role, contenido))


def escribe(tel, texto):
    prov.enviados.clear()
    prov.entrante = [MensajeEntrante(telefono=tel, texto=texto, mensaje_id="x", es_propio=False, tipo="text")]
    assert cliente.post("/webhook", json={}).status_code == 200
    return list(prov.enviados)


def docs(enviados):
    return [n for k, n in enviados if k == "doc"]


def textos(enviados):
    return [n for k, n in enviados if k == "texto"]


def probar():
    fallos = []

    def check(nombre, cond):
        if not cond:
            fallos.append(nombre)

    # 1) conversación normal: pide el número de cuenta
    r = escribe("51900000001", "Me puede dar el número de cuenta?")
    check("1 envia las cuentas", docs(r) == [CUENTAS])
    check("1 mensaje automatico", textos(r) == [main.MENSAJE_CUENTAS_ABONO_AUTOMATICO])
    # 2) insiste enseguida: no se reenvía, sigue el flujo normal (Claude)
    r = escribe("51900000001", "y donde deposito")
    check("2 no reenvia el pdf", docs(r) == [])
    check("2 responde Claude", textos(r) == ["RESPUESTA_DE_CLAUDE"])
    # 3) mensaje sin relación: no dispara
    r = escribe("51900000002", "Buenas tardes, quiero información de créditos")
    check("3 no envia cuentas", docs(r) == [] and textos(r) == ["RESPUESTA_DE_CLAUDE"])
    # 4) dice que ya pagó: no dispara
    r = escribe("51900000003", "ya pagué ayer")
    check("4 ya pago no dispara", docs(r) == [])

    # 5) respuesta al aviso de morosidad
    reg = "[plantilla enviada: Aviso de morosidad (cuota no cubierta)] Juan | setiembre | 85.00"
    guardar("51900000004", "humano", reg)
    r = escribe("51900000004", "buenas, de qué se trata")
    check("5 morosidad sin pago: solo asesores", docs(r) == [] and textos(r) == [main.MENSAJE_MOROSIDAD_DERIVACION])
    guardar("51900000005", "humano", reg)
    r = escribe("51900000005", "adonde deposito?")
    check("5b morosidad con pago: cuentas + links", docs(r) == [CUENTAS] and textos(r) == [main.MENSAJE_CUENTAS_ABONO_AUTOMATICO])

    # 6) respuesta a Campaña Navidad
    reg = "[plantilla enviada: Campaña Navidad 2026] "
    guardar("51900000006", "humano", reg)
    r = escribe("51900000006", "Sí")
    check("6 navidad sin pago: 3 laminas, sin cuentas", len(docs(r)) == 3 and CUENTAS not in docs(r))
    guardar("51900000007", "humano", reg)
    r = escribe("51900000007", "como pago la bolsa?")
    check("6b navidad con pago: laminas + cuentas",
          len(docs(r)) == 4 and CUENTAS in docs(r)
          and textos(r) == [main.MENSAJE_NAVIDAD_SI, main.MENSAJE_CUENTAS_ABONO_VOUCHER])

    # 7) respuesta a recordatorio de pago diciendo que va a abonar
    guardar("51900000008", "humano", "[plantilla enviada: Recordatorio de pago] Ana | 50 | 30/10")
    r = escribe("51900000008", "mañana estaré abonando")
    check("7 recordatorio + intencion: cuentas", docs(r) == [CUENTAS] and textos(r) == [main.MENSAJE_CUENTAS_ABONO_RECORDATORIO])

    return fallos


def test_flujo_pagos():
    assert probar() == []


if __name__ == "__main__":
    fallos = probar()
    for f in fallos:
        print("FALLA:", f)
    print("todo ok" if not fallos else f"{len(fallos)} con problemas")
    sys.exit(1 if fallos else 0)
