"""Obtiene el WhatsApp Business Account ID (WABA) a partir del Phone Number ID en .env."""
import os
import sys
import httpx
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

token = os.getenv("META_ACCESS_TOKEN")
phone_number_id = os.getenv("META_PHONE_NUMBER_ID")

if not token or not phone_number_id:
    print("Faltan META_ACCESS_TOKEN o META_PHONE_NUMBER_ID en .env")
    sys.exit(1)

url = f"https://graph.facebook.com/v21.0/{phone_number_id}"
params = {"fields": "id,display_phone_number,whatsapp_business_account"}
headers = {"Authorization": f"Bearer {token}"}

r = httpx.get(url, params=params, headers=headers, timeout=30)
print("status:", r.status_code)
print(r.text)
