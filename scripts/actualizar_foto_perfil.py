"""Actualiza la foto de perfil del WhatsApp Business (Cloud API)."""
import os
import sys
import httpx
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

token = os.getenv("META_ACCESS_TOKEN")
phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
app_id = "1108245793833671"  # app_id obtenido antes via debug_token
ruta_imagen = r"D:\whatsapp-agentkit\knowledge\logo_perfil_coosermul.png"

if not token or not phone_number_id:
    print("Faltan META_ACCESS_TOKEN o META_PHONE_NUMBER_ID en .env")
    sys.exit(1)

with open(ruta_imagen, "rb") as f:
    contenido = f.read()

print(f"Tamaño de la imagen: {len(contenido)} bytes")

# Paso 1: crear sesión de carga (resumable upload)
url_sesion = f"https://graph.facebook.com/v21.0/{app_id}/uploads"
params = {
    "file_length": len(contenido),
    "file_type": "image/png",
    "access_token": token,
}
r1 = httpx.post(url_sesion, params=params, timeout=30)
print("Paso 1 (crear sesión):", r1.status_code, r1.text)
if r1.status_code != 200:
    sys.exit(1)
session_id = r1.json()["id"]

# Paso 2: subir los bytes del archivo
url_subida = f"https://graph.facebook.com/v21.0/{session_id}"
headers = {
    "Authorization": f"OAuth {token}",
    "file_offset": "0",
}
r2 = httpx.post(url_subida, headers=headers, content=contenido, timeout=60)
print("Paso 2 (subir archivo):", r2.status_code, r2.text)
if r2.status_code != 200:
    sys.exit(1)
handle = r2.json()["h"]

# Paso 3: asignar el handle como foto de perfil del negocio
url_perfil = f"https://graph.facebook.com/v21.0/{phone_number_id}/whatsapp_business_profile"
headers2 = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
payload = {"messaging_product": "whatsapp", "profile_picture_handle": handle}
r3 = httpx.post(url_perfil, headers=headers2, json=payload, timeout=30)
print("Paso 3 (asignar foto de perfil):", r3.status_code, r3.text)
