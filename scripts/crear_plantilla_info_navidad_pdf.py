# -*- coding: utf-8 -*-
"""Crea en Meta la plantilla 'info_campana_navidad_pdf_2026': lleva el PDF
de la Campana Navidena 2026 como DOCUMENTO en el encabezado, de modo que se
entrega al socio sin que tenga que haber escrito antes (fuera de la
ventana de 24h solo se pueden entregar archivos dentro de una plantilla).

Pasos de Meta: 1) subir el PDF de ejemplo con la API de carga reanudable
para obtener un 'header_handle'; 2) crear la plantilla con ese handle.
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
PDF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "plantillas_media", "campana_navidena_2026.pdf")

# app_id del token (la carga reanudable se hace contra la app, no contra la WABA)
r = httpx.get(f"{API}/debug_token", params={"input_token": token, "access_token": token}, timeout=30)
app_id = r.json()["data"]["app_id"]

contenido = open(PDF, "rb").read()
r = httpx.post(
    f"{API}/{app_id}/uploads",
    params={"file_name": "campana_navidena_2026.pdf", "file_length": len(contenido),
            "file_type": "application/pdf", "access_token": token},
    timeout=30,
)
print("sesion de carga:", r.status_code, r.text)
sesion = r.json()["id"]

r = httpx.post(
    f"{API}/{sesion}",
    headers={"Authorization": f"OAuth {token}", "file_offset": "0"},
    content=contenido,
    timeout=120,
)
print("carga del archivo:", r.status_code, r.text[:200])
handle = r.json()["h"]

PLANTILLA = {
    "name": "info_campana_navidad_pdf_2026",
    "language": "es",
    "category": "MARKETING",
    "components": [
        {"type": "HEADER", "format": "DOCUMENT", "example": {"header_handle": [handle]}},
        {
            "type": "BODY",
            "text": (
                "Coosermul BN le comparte la información de la Campaña Navideña 2026: "
                "Bolsa Navideña, Gran Rifa Anual y Sorteo Gratuito \"El Buen Pagador\". "
                "Revise el documento adjunto. Para inscribirse o consultar, escriba "
                "directamente a nuestros asesores: https://wa.me/51996899924 o "
                "https://wa.me/51996899927"
            ),
        },
    ],
}
r = httpx.post(f"{API}/{waba_id}/message_templates",
               headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
               json=PLANTILLA, timeout=30)
print("plantilla:", r.status_code, r.text)
