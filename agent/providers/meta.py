# agent/providers/meta.py — Adaptador para Meta WhatsApp Cloud API
# Generado por AgentKit

import os
import json
import mimetypes
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
                        adjunto = msg.get(tipo_msg, {})
                        caption = adjunto.get("caption", "")
                        mensajes.append(MensajeEntrante(
                            telefono=remitente,
                            texto=caption,
                            mensaje_id=msg.get("id", ""),
                            es_propio=False,
                            tipo=tipo_msg,
                            media_id=adjunto.get("id", ""),
                            nombre_archivo=adjunto.get("filename", ""),
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

    async def _subir_media(self, ruta_archivo: str, mime_type: str) -> str | None:
        """Sube un archivo local a los servidores de Meta y retorna su media_id."""
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            with open(ruta_archivo, "rb") as f:
                files = {"file": (os.path.basename(ruta_archivo), f, mime_type)}
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

    async def enviar_documento(
        self, telefono: str, ruta_archivo: str, nombre_archivo: str, caption: str = ""
    ) -> bool:
        """
        Sube un archivo y lo envía por WhatsApp. Detecta el tipo (imagen o
        documento genérico) según la extensión del archivo.
        """
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False

        mime_type, _ = mimetypes.guess_type(nombre_archivo)
        mime_type = mime_type or "application/octet-stream"
        es_imagen = mime_type.startswith("image/")

        media_id = await self._subir_media(ruta_archivo, mime_type)
        if not media_id:
            return False

        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        if es_imagen:
            contenido = {"id": media_id}
            if caption:
                contenido["caption"] = caption
            payload = {
                "messaging_product": "whatsapp",
                "to": telefono,
                "type": "image",
                "image": contenido,
            }
        else:
            contenido = {"id": media_id, "filename": nombre_archivo}
            if caption:
                contenido["caption"] = caption
            payload = {
                "messaging_product": "whatsapp",
                "to": telefono,
                "type": "document",
                "document": contenido,
            }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error enviando documento via Meta API: {r.status_code} — {r.text}")
            return r.status_code == 200

    async def descargar_media(self, media_id: str) -> tuple[bytes, str] | None:
        """
        Descarga un archivo recibido de un socio (comprobante de pago, etc.).
        Meta requiere 2 pasos: 1) pedir la URL temporal del archivo con el
        media_id, 2) descargar esa URL con el mismo token de acceso.
        """
        if not self.access_token or not media_id:
            return None
        url_info = f"https://graph.facebook.com/{self.api_version}/{media_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient() as client:
            r = await client.get(url_info, headers=headers, timeout=30)
            if r.status_code != 200:
                logger.error(f"Error obteniendo info de media {media_id}: {r.status_code} — {r.text}")
                return None
            info = r.json()
            media_url = info.get("url")
            mime_type = info.get("mime_type", "application/octet-stream")
            if not media_url:
                return None
            r2 = await client.get(media_url, headers=headers, timeout=60)
            if r2.status_code != 200:
                logger.error(f"Error descargando media {media_id}: {r2.status_code}")
                return None
            return r2.content, mime_type
