# -*- coding: utf-8 -*-
"""Crea en Meta WhatsApp Business la plantilla de utilidad para informar a
cada socio sus 4 numeros asignados en la Rifa Navidena 2026."""
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
    "name": "numeros_rifa_navidad_2026",
    "language": "es",
    "category": "UTILITY",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Hola {{1}}, le confirmamos sus números asignados para la Gran "
                "Rifa Anual — Campaña Navideña 2026: {{2}} - {{3}} - {{4}} - "
                "{{5}}. ¡Mucha suerte! Cualquier consulta, escríbanos por este "
                "medio. — Coosermul BN"
            ),
            "example": {
                "body_text": [["Juan Pérez", "5648", "2535", "5678", "1453"]]
            },
        }
    ],
}

url = f"https://graph.facebook.com/v21.0/{waba_id}/message_templates"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

r = httpx.post(url, headers=headers, json=PLANTILLA, timeout=30)
print("status:", r.status_code)
print(r.text)
