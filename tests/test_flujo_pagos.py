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

    fallar_documentos = False

    async def enviar_documento(self, tel, ruta, nombre, caption=""):
        if self.fallar_documentos:
            return False
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

    # 8) caso real del 20/10: respuesta a "Descuento no cubierto" pidiendo la cuenta
    #    (con errata). Debe salir el PDF y quedar registrado en el chat.
    guardar("51900000009", "humano",
            "[plantilla enviada: Descuento no cubierto (saldo pendiente)] Lazo Salcedo Jeancarlo Manuel | 8201.88")
    r = escribe("51900000009", "Pasmae la cuenta para abonar por favor")
    check("8 envia el pdf de cuentas", docs(r) == [CUENTAS])
    historial = asyncio.run(memory.obtener_historial("51900000009"))
    check("8 queda registro visible del envio automatico",
          any(m["role"] == "assistant" and "enviadas automáticamente" in m["content"] and CUENTAS in m["content"]
              for m in historial))

    # 9) si Meta/la red rechaza el PDF: queda alerta visible y NO se registra como enviado
    prov.fallar_documentos = True
    escribe("51900000010", "pasame el numero de cuenta")
    prov.fallar_documentos = False
    historial = asyncio.run(memory.obtener_historial("51900000010"))
    check("9 alerta de fallo visible", any(m["role"] == "sistema" and "No se pudo enviar" in m["content"] for m in historial))
    check("9 no dice enviado", not any("enviadas automáticamente" in m["content"] for m in historial))

    # 10) saludo de aniversario: felicitaciones -> agradecimiento fijo; preguntas -> Claude;
    #     pedir pagar -> cuentas de abono
    reg = "[plantilla enviada: Saludo 49 aniversario (tarjeta)] "
    guardar("51900000011", "humano", reg)
    r = escribe("51900000011", "¡Felicidades por su aniversario! Que Dios los bendiga")
    check("10 felicitacion: agradecimiento fijo", textos(r) == [main.MENSAJE_AGRADECIMIENTO_ANIVERSARIO] and docs(r) == [])
    guardar("51900000012", "humano", reg)
    r = escribe("51900000012", "gracias, cuándo es el sorteo?")
    check("10b pregunta: la atiende Claude", textos(r) == ["RESPUESTA_DE_CLAUDE"])
    guardar("51900000013", "humano", reg)
    r = escribe("51900000013", "gracias, quiero pagar mi cuota, donde deposito")
    check("10c pide pagar: cuentas", docs(r) == [CUENTAS])

    return fallos


def test_flujo_pagos():
    assert probar() == []


if __name__ == "__main__":
    fallos = probar()
    for f in fallos:
        print("FALLA:", f)
    print("todo ok" if not fallos else f"{len(fallos)} con problemas")
    sys.exit(1 if fallos else 0)
