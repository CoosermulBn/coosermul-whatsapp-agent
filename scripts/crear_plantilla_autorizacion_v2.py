# -*- coding: utf-8 -*-
"""Recrea limpia la plantilla 'Autorizacion de info (no socios BN)'.

La version actualmente aprobada en Meta (autorizacion_info_coosermul)
quedo en un estado roto -- probablemente editada a mano en el WhatsApp
Manager -- con un HEADER de texto que literalmente muestra el nombre
interno de la plantilla, una comilla suelta al inicio del cuerpo, y un
componente CALL_PERMISSION_REQUEST (solicitud de permiso para llamar)
que nunca se pidio. Eso es consistente con el reporte de que Meta acepta
el envio (200 OK) pero el mensaje nunca le llega al destinatario.

No se puede editar una plantilla aprobada -- se crea una nueva, limpia,
con otro nombre, y luego se actualiza admin.py para usarla.
"""
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
    "name": "autorizacion_info_coosermul_v2",
    "language": "es_PE",
    "category": "MARKETING",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Hola {{1}}, te escribimos de Coosermul BN, la Cooperativa de "
                "Servicios Múltiples de los Trabajadores del Banco de la Nación. "
                "Nos gustaría compartirte información sobre los beneficios de "
                "asociarte (créditos, bazar, previsión social y más). Si te "
                "interesa recibir esta información, respóndenos SÍ."
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
