# -*- coding: utf-8 -*-
"""Crea en Meta la plantilla de utilidad 'aviso_morosidad_cuota': notificacion
de fin de mes a socios cuya cuota enviada a descuento por planilla no se
cubrio y vencio el plazo (intereses, notificaciones, cartas notariales,
posible cobranza judicial)."""
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
    "name": "aviso_morosidad_cuota",
    "language": "es",
    "category": "UTILITY",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Hola {{1}}, su cuota del mes de {{2}} enviada a descuento por planilla "
                "no se cubrió en su totalidad. Le indicamos que tenía hasta el 30 del "
                "presente mes para cancelar la suma de S/ {{3}}; sin embargo, no cumplió "
                "con pagar. Le recordamos que este hecho lo perjudica económicamente por "
                "los intereses por morosidad, costo de notificaciones, cartas notariales "
                "y posible inicio de un proceso judicial de cobranza. Para una mejor "
                "información escriba directamente a nuestros asesores: "
                "https://wa.me/51996899924 o https://wa.me/51996899927"
            ),
            "example": {"body_text": [["Juan Pérez", "setiembre", "85.00"]]},
        }
    ],
}

r = httpx.post(
    f"https://graph.facebook.com/v21.0/{waba_id}/message_templates",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    json=PLANTILLA,
    timeout=30,
)
print("status:", r.status_code)
print(r.text)
