# agent/providers/meta.py — Adaptador para Meta WhatsApp Cloud API
# Generado por AgentKit

import os
import json
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando la API oficial de Meta (Cloud API)."""

    def __init__(self):
        self.access_token = os.getenv("META_ACCESS_TOKEN")
        self.phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        self.verify_token = os.getenv("META_VERIFY_TOKEN", "agentkit-verify")
        self.api_version = "v21.0"

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Meta requiere verificación GET con hub.verify_token."""
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and token == self.verify_token:
            # Meta espera el challenge como respuesta en texto plano
            return int(challenge)
        return None

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload anidado de Meta Cloud API."""
        body = await request.json()
        if os.getenv("DEBUG_WEBHOOK_PAYLOAD", "").lower() == "true":
            logger.info(f"Webhook payload crudo de Meta: {json.dumps(body, ensure_ascii=False)}")
        mensajes = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    # Meta identifica al remitente con "from" (número de
                    # teléfono clásico) en la mayoría de casos, pero en
                    # algunos flujos nuevos (ej. identidad "opaca" por
                    # privacidad) usa "from_user_id" en su lugar.
                    remitente = msg.get("from") or msg.get("from_user_id", "")
                    tipo_msg = msg.get("type")
                    if tipo_msg == "text":
                        mensajes.append(MensajeEntrante(
                            telefono=remitente,
                            texto=msg.get("text", {}).get("body", ""),
                            mensaje_id=msg.get("id", ""),
                            es_propio=False,  # Meta solo envía mensajes entrantes
                            tipo="text",
                        ))
                    elif tipo_msg in ("document", "image"):
                        # El socio envió un archivo adjunto (ej. comprobante de pago).
                        # El "caption" (si lo escribió) queda en texto, puede venir vacío.
                        caption = msg.get(tipo_msg, {}).get("caption", "")
                        mensajes.append(MensajeEntrante(
                            telefono=remitente,
                            texto=caption,
                            mensaje_id=msg.get("id", ""),
                            es_propio=False,
                            tipo=tipo_msg,
                        ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía mensaje via Meta WhatsApp Cloud API."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "text",
            "text": {"body": mensaje},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error Meta API: {r.status_code} — {r.text}")
            return r.status_code == 200

    async def _subir_media(self, ruta_archivo: str) -> str | None:
        """Sube un archivo local a los servidores de Meta y retorna su media_id."""
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            with open(ruta_archivo, "rb") as f:
                files = {"file": (os.path.basename(ruta_archivo), f, "application/pdf")}
                data = {"messaging_product": "whatsapp"}
                async with httpx.AsyncClient() as client:
                    r = await client.post(url, headers=headers, data=data, files=files, timeout=60)
        except FileNotFoundError:
            logger.error(f"Archivo no encontrado para subir a Meta: {ruta_archivo}")
            return None
        if r.status_code != 200:
            logger.error(f"Error subiendo media a Meta: {r.status_code} — {r.text}")
            return None
        return r.json().get("id")

    async def enviar_documento(self, telefono: str, ruta_archivo: str, nombre_archivo: str) -> bool:
        """Sube un archivo y lo envía como documento por WhatsApp."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        media_id = await self._subir_media(ruta_archivo)
        if not media_id:
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "document",
            "document": {"id": media_id, "filename": nombre_archivo},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error enviando documento via Meta API: {r.status_code} — {r.text}")
            return r.status_code == 200
