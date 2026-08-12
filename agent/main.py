# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con cualquier proveedor (Meta, Twilio) gracias a la capa de providers.
"""

import sys
import os
import logging

# Algunos contenedores Linux minimalistas arrancan con una configuración
# regional que no es UTF-8 (por ejemplo, si el locale "C.UTF-8" no está
# generado en la imagen). Esto hace que cualquier logging o manejo de texto
# con tildes/emojis falle con "'ascii' codec can't encode characters...".
# Forzamos UTF-8 aquí en tiempo de ejecución para no depender de la
# configuración del contenedor/host.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial
from agent.providers import obtener_proveedor
from agent.admin import router as admin_router

load_dotenv()

# Configuración de logging según entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger("agentkit")

# Proveedor de WhatsApp (se configura en .env con WHATSAPP_PROVIDER)
proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))

# Respuesta fija cuando el socio envía un documento/imagen (ej. comprobante
# de pago). No pasa por Claude para garantizar el mensaje exacto siempre.
MENSAJE_COMPROBANTE_RECIBIDO = (
    "¡Gracias, lo recibimos! 📄 Tu documento pasará a Contabilidad para su "
    "convalidación. Si necesitas algo más mientras tanto, escríbenos."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    yield


app = FastAPI(
    title="AgentKit — WhatsApp AI Agent",
    version="1.0.0",
    lifespan=lifespan
)
app.include_router(admin_router)


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway/monitoreo."""
    return {"status": "ok", "service": "agentkit"}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificación GET del webhook (requerido por Meta Cloud API, no-op para otros)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


@app.post("/webhook")
async def webhook_handler(request: Request):
    """
    Recibe mensajes de WhatsApp via el proveedor configurado.
    Procesa el mensaje, genera respuesta con Claude y la envía de vuelta.
    """
    try:
        # Parsear webhook — el proveedor normaliza el formato
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            # Ignorar mensajes propios (los que envió el propio agente)
            if msg.es_propio:
                continue

            # Documentos/imágenes (ej. comprobantes de pago): respuesta fija,
            # sin pasar por Claude, para garantizar el mensaje exacto.
            if msg.tipo in ("document", "image"):
                logger.info(f"Adjunto ({msg.tipo}) de {msg.telefono}")
                respuesta = MENSAJE_COMPROBANTE_RECIBIDO
                registro = msg.texto or f"[{msg.tipo} adjunto sin descripción]"
                await guardar_mensaje(msg.telefono, "user", registro)
                await guardar_mensaje(msg.telefono, "assistant", respuesta)
                await proveedor.enviar_mensaje(msg.telefono, respuesta)
                logger.info(f"Respuesta a {msg.telefono}: {respuesta}")
                continue

            # Mensajes de texto vacíos: no hay nada que procesar
            if not msg.texto:
                continue

            logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            # Obtener historial ANTES de guardar el mensaje actual
            # (brain.py agrega el mensaje actual, evitando duplicados)
            historial = await obtener_historial(msg.telefono)

            # Generar respuesta con Claude (puede incluir documentos a enviar)
            resultado = await generar_respuesta(msg.texto, historial)
            respuesta = resultado["texto"]
            documentos = resultado.get("documentos", [])

            # Guardar mensaje del usuario Y respuesta del agente en memoria
            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)

            # Enviar los documentos primero (si los hay), luego el texto
            for doc in documentos:
                enviado = await proveedor.enviar_documento(
                    msg.telefono, doc["ruta"], doc["nombre_archivo"]
                )
                if not enviado:
                    logger.error(f"No se pudo enviar el documento {doc['nombre_archivo']} a {msg.telefono}")

            # Enviar respuesta por WhatsApp via el proveedor
            await proveedor.enviar_mensaje(msg.telefono, respuesta)

            logger.info(f"Respuesta a {msg.telefono}: {respuesta}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
