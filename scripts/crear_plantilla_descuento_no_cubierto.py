# -*- coding: utf-8 -*-
"""Crea en Meta WhatsApp Business la plantilla de recordatorio de pago
para cuotas enviadas a descuento por planilla que no se cubrieron en su
totalidad (saldo pendiente)."""
import os
import sys
import httpx
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

token = os.getenv("META_ACCESS_TOKEN")
waba_id = os.getenv("META_WABA_ID")

if not token or not waba_id:
    print("Faltan META_ACCESS_TOKEN o META_WABA_ID en .env")
    sys.exit(1)

PLANTILLA = {
    "name": "descuento_no_cubierto",
    "language": "es",
    "category": "UTILITY",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Hola {{1}}, su cuota del mes enviada a descuento por planilla no se "
                "cubrió en su totalidad. Le recordamos que tiene hasta el 30 del "
                "presente mes para cancelar la suma de S/ {{2}}. Cualquier consulta, "
                "escríbanos por este medio. — Coosermul BN"
            ),
            "example": {
                "body_text": [["Juan Pérez", "85.00"]]
            },
        }
    ],
}

url = f"https://graph.facebook.com/v21.0/{waba_id}/message_templates"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

r = httpx.post(url, headers=headers, json=PLANTILLA, timeout=30)
print("status:", r.status_code)
print(r.text)
