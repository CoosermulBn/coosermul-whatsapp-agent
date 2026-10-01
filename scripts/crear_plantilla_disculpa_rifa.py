# -*- coding: utf-8 -*-
"""Crea en Meta WhatsApp Business la plantilla de disculpas por el error
en la asignacion de telefonos del envio de 'Numeros Rifa Navidena 2026'."""
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
    "name": "disculpa_error_rifa_numeros",
    "language": "es",
    "category": "UTILITY",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Hola {{1}}, le pedimos disculpas: nuestro equipo de Sistemas "
                "cometió un error al asignar los números telefónicos en el "
                "envío de sus números de la Rifa Navideña 2026. Estamos "
                "haciendo la revisión correspondiente y le reenviaremos su "
                "información correcta en breve. Agradecemos su comprensión. "
                "— Coosermul BN"
            ),
            "example": {
                "body_text": [["Juan Pérez"]]
            },
        }
    ],
}

url = f"https://graph.facebook.com/v21.0/{waba_id}/message_templates"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

r = httpx.post(url, headers=headers, json=PLANTILLA, timeout=30)
print("status:", r.status_code)
print(r.text)
