# -*- coding: utf-8 -*-
"""Crea en Meta la plantilla 'saludo_aniversario_49_coosermul': lleva la
tarjeta de saludo por el 49 aniversario como IMAGEN en el encabezado.

Categoria MARKETING: Meta solo acepta UTILITY para avisos transaccionales
(un pago, un tramite, un dato de la cuenta del cliente); un saludo
institucional no lo es y seria rechazado o recategorizado a marketing.

La imagen de la plantilla es solo el ejemplo que Meta revisa; al enviar se
adjunta la tarjeta real (data/plantillas_media/tarjeta_aniversario_49.jpg).
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

API = "https://graph.facebook.com/v21.0"
IMAGEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "plantillas_media", "tarjeta_aniversario_49.jpg")

app_id = httpx.get(f"{API}/debug_token", params={"input_token": token, "access_token": token}, timeout=30).json()["data"]["app_id"]

contenido = open(IMAGEN, "rb").read()
r = httpx.post(
    f"{API}/{app_id}/uploads",
    params={"file_name": "tarjeta_aniversario_49.jpg", "file_length": len(contenido),
            "file_type": "image/jpeg", "access_token": token},
    timeout=30,
)
sesion = r.json()["id"]
r = httpx.post(f"{API}/{sesion}", headers={"Authorization": f"OAuth {token}", "file_offset": "0"},
               content=contenido, timeout=120)
handle = r.json()["h"]
print("imagen de ejemplo subida")

PLANTILLA = {
    "name": "saludo_aniversario_49_coosermul",
    "language": "es",
    "category": "MARKETING",
    "components": [
        {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": [handle]}},
        {
            "type": "BODY",
            "text": (
                "Estimado socio: Coosermul BN Ltda. cumple 49 años de creación y queremos "
                "compartir este saludo con usted. ¡Gracias por ser parte de nuestra "
                "cooperativa! — Gerencia General, Coosermul BN"
            ),
        },
    ],
}
r = httpx.post(f"{API}/{waba_id}/message_templates",
               headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
               json=PLANTILLA, timeout=30)
print("plantilla:", r.status_code, r.text)
