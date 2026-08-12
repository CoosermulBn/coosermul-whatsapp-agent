"""Crea las plantillas de mensaje (message templates) en Meta WhatsApp Business."""
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

PLANTILLAS = [
    {
        "name": "recordatorio_pago",
        "language": "es",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hola {{1}}, te recordamos que tienes una cuota pendiente de S/ {{2}} "
                    "con vencimiento el {{3}}. Si ya realizaste el pago, puedes ignorar este "
                    "mensaje. Cualquier consulta, escribenos por este medio. — Coosermul BN"
                ),
                "example": {
                    "body_text": [["Juan Perez", "150.00", "20/08/2026"]]
                },
            }
        ],
    },
    {
        "name": "tramite_aprobado",
        "language": "es",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hola {{1}}, te informamos que tu {{2}} ha sido aprobado(a). Nuestro "
                    "equipo se pondra en contacto contigo para los siguientes pasos. "
                    "Cualquier consulta, escribenos por este medio. — Coosermul BN"
                ),
                "example": {
                    "body_text": [["Juan Perez", "solicitud de credito"]]
                },
            }
        ],
    },
]

url = f"https://graph.facebook.com/v21.0/{waba_id}/message_templates"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

for plantilla in PLANTILLAS:
    r = httpx.post(url, headers=headers, json=plantilla, timeout=30)
    print(f"--- {plantilla['name']} ---")
    print("status:", r.status_code)
    print(r.text)
    print()
