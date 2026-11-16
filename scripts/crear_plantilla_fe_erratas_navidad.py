# -*- coding: utf-8 -*-
"""Crea en Meta la plantilla 'fe_erratas_bolsa_navidena_2026': pide disculpas
por el error de la lamina de la Campaña Navideña (la Bolsa Navideña decia
4 bolsas de azucar Dulfina y son 2) y adjunta la lamina corregida como IMAGEN
en el encabezado.

Categoria UTILITY: es una correccion de informacion ya enviada al socio.
La imagen de la plantilla es solo el ejemplo que Meta revisa; al enviar se
adjunta la lamina real (data/plantillas_media/lamina_bolsa_navidena_corregida.jpg).
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
IMAGEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "plantillas_media", "lamina_bolsa_navidena_corregida.jpg")

app_id = httpx.get(f"{API}/debug_token", params={"input_token": token, "access_token": token}, timeout=30).json()["data"]["app_id"]

contenido = open(IMAGEN, "rb").read()
r = httpx.post(
    f"{API}/{app_id}/uploads",
    params={"file_name": "lamina_bolsa_navidena_corregida.jpg", "file_length": len(contenido),
            "file_type": "image/jpeg", "access_token": token},
    timeout=30,
)
sesion = r.json()["id"]
r = httpx.post(f"{API}/{sesion}", headers={"Authorization": f"OAuth {token}", "file_offset": "0"},
               content=contenido, timeout=120)
handle = r.json()["h"]
print("imagen de ejemplo subida")

PLANTILLA = {
    "name": "fe_erratas_bolsa_navidena_2026",
    "language": "es",
    "category": "UTILITY",
    "components": [
        {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": [handle]}},
        {
            "type": "BODY",
            "text": (
                "Estimado socio: le pedimos disculpas. En la lámina de la Campaña "
                "Navideña 2026 que le enviamos, la Bolsa Navideña indicaba 4 bolsas "
                "de azúcar Dulfina de 1 kg, cuando lo correcto es 2 bolsas. Adjuntamos "
                "la lámina corregida. Agradecemos su comprensión. — Coosermul BN"
            ),
        },
    ],
}
r = httpx.post(f"{API}/{waba_id}/message_templates",
               headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
               json=PLANTILLA, timeout=30)
print("plantilla:", r.status_code, r.text)
