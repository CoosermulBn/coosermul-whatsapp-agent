# agent/providers/base.py — Clase base para proveedores de WhatsApp
# Generado por AgentKit

"""
Define la interfaz común que todos los proveedores de WhatsApp deben implementar.
Esto permite cambiar de proveedor sin modificar el resto del código.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from fastapi import Request


@dataclass
class MensajeEntrante:
    """Mensaje normalizado — mismo formato sin importar el proveedor."""
    telefono: str       # Número del remitente
    texto: str          # Contenido del mensaje (o el caption, si es un adjunto)
    mensaje_id: str     # ID único del mensaje
    es_propio: bool     # True si lo envió el agente (se ignora)
    tipo: str = "text"  # "text" | "document" | "image" | "boton" — tipo de contenido recibido
    media_id: str = ""       # ID del adjunto en el proveedor (para descargarlo)
    nombre_archivo: str = "" # Nombre de archivo original, si el proveedor lo da
    boton_id: str = ""       # ID del botón presionado (si tipo == "boton")


class ProveedorWhatsApp(ABC):
    """Interfaz que cada proveedor de WhatsApp debe implementar."""

    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Extrae y normaliza mensajes del payload del webhook."""
        ...

    @abstractmethod
    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía un mensaje de texto. Retorna True si fue exitoso."""
        ...

    async def enviar_documento(
        self, telefono: str, ruta_archivo: str, nombre_archivo: str, caption: str = ""
    ) -> bool:
        """
        Envía un archivo (PDF, imagen, etc.) desde disco. Proveedores que no
        soporten esto pueden dejar la implementación por defecto (no-op).
        """
        return False

    async def descargar_media(self, media_id: str) -> tuple[bytes, str] | None:
        """
        Descarga un archivo recibido (por su media_id) desde el proveedor.
        Retorna (contenido_bytes, mime_type) o None si falla.
        """
        return None

    async def enviar_botones(self, telefono: str, texto: str, opciones: list[dict]) -> bool:
        """
        Envía un mensaje con botones táctiles de respuesta rápida.
        `opciones` es una lista de hasta 3 dicts {"id": str, "titulo": str}.
        Retorna True si fue exitoso.
        """
        return False

    async def enviar_lista(
        self, telefono: str, texto: str, texto_boton: str, filas: list[dict]
    ) -> bool:
        """
        Envía un menú interactivo tipo lista (hasta 10 filas), con un botón
        que lo abre. `filas` es una lista de hasta 10 dicts
        {"id": str, "titulo": str, "descripcion": str (opcional)}.
        Retorna True si fue exitoso.
        """
        return False

    async def enviar_plantilla(
        self, telefono: str, nombre_plantilla: str, idioma: str, parametros: list[str]
    ) -> bool:
        """
        Envía un mensaje usando una plantilla aprobada (requerido para que el
        negocio inicie una conversación con alguien que no ha escrito antes,
        o fuera de la ventana de 24h). Retorna True si fue exitoso.
        """
        return False

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Verificación GET del webhook (solo Meta la requiere). Retorna respuesta o None."""
        return None
