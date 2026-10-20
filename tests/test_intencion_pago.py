# tests/test_intencion_pago.py — python tests/test_intencion_pago.py  (o pytest)
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.intencion_pago import expresa_intencion_de_pago as f

DEBE_DISPARAR = [
    "Me puede dar el número de cuenta?",
    "Numero de cuenta para pagar",
    "nro de cuenta por favor",
    "cuáles son las cuentas de abono",
    "cuentas de pago",
    "necesito la cuenta para depositar",
    "A qué cuenta deposito?",
    "en que cuenta pago mi cuota",
    "Adonde deposito",
    "donde puedo depositar",
    "Dónde pago mi cuota?",
    "a donde tengo que hacer el pago",
    "Cómo pago?",
    "como puedo pagar mi deuda",
    "como hago para depositar",
    "como cancelo mi deuda",
    "como puedo cancelar la deuda total",
    "Quiero pagar",
    "quiero pagar mi cuota",
    "voy a pagar mañana",
    "Voy a depositar hoy",
    "necesito regularizar mi cuota",
    "quisiera cancelar mi deuda",
    "deseo ponerme al día",
    "puedo pagar con yape?",
    "tienen yape o plin",
    "me pasa el CCI",
    "cuenta interbancaria",
    "cuenta bancaria para el pago",
    "cuenta del BCP",
    "voy a hacer el depósito",
    "quiero realizar el pago",
    "para pagar la bolsa navideña",
    "tickets: quiero pagar mi rifa",
    "CUENTAS DE ABONO",
    "como pago la inscripcion",
    "Perfecto mañana estaré abonando",
    "Apenas lo hagan realizo el deposito",
    "debo estar cancelando la deuda total",
    "Si apenas me abonen estaré poniéndome al día",
    "hoy realizo el pago",
    "mañana hago el depósito",
]

NO_DEBE_DISPARAR = [
    "hola",
    "Sí",
    "No",
    "gracias",
    "Buenas tardes",
    "Ya pagué",
    "ya pague el mes pasado",
    "ya deposité ayer",
    "ya cancelé mi deuda",
    "este mes estoy abonando esa cantidad",
    "estoy pagando mis cuotas",
    "ya hice el pago, les envié el voucher",
    "ya estoy pagando",
    "Pago sobregiro",
    "no voy a pagar",
    "no puedo pagar este mes",
    "no quiero pagar eso",
    "mi número de cuenta es 00219300123456789012",
    "depositen en mi cuenta por favor",
    "mi cuenta del banco de la nación es 04-123-456789",
    "quiero cancelar mi afiliación",
    "quiero cancelar mi inscripción al fondo",
    "sorteo el buen pagador",
    "soy buen pagador, participo?",
    "cuál es el precio de cada rifa?",
    "formas de pago del televisor",
    "quiero saber de los créditos",
    "necesito un préstamo",
    "cuál es el horario de atención",
    "quiero mi estado de cuenta",
    "me interesa la bolsa navideña",
    "Gracias por comunicarte con Carlos Morante Agente Inmobiliario",
    "Como afiliado tengo que escoger un numero del sorteo?",
    "necesito el pagaré",
    "dónde queda la oficina",
    "como me inscribo",
    "",
]


def probar():
    fallos = []
    for t in DEBE_DISPARAR:
        if not f(t):
            fallos.append(("DEBIA disparar", t))
    for t in NO_DEBE_DISPARAR:
        if f(t):
            fallos.append(("NO debia disparar", t))
    return fallos


def test_intencion_de_pago():
    assert probar() == []


if __name__ == "__main__":
    fallos = probar()
    for tipo, t in fallos:
        print(f"{tipo}: {t!r}")
    print(f"{len(DEBE_DISPARAR) + len(NO_DEBE_DISPARAR) - len(fallos)} ok, {len(fallos)} con problemas")
    sys.exit(1 if fallos else 0)
