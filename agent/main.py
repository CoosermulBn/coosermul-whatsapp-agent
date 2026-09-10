# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con cualquier proveedor (Meta, Twilio) gracias a la capa de providers.
"""

import sys
import os
import re
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
from agent.memory import (
    inicializar_db,
    guardar_mensaje,
    obtener_historial,
    activar_modo_humano,
    esta_en_modo_humano,
    guardar_adjunto,
)
from agent.providers import obtener_proveedor
from agent.admin import router as admin_router
from agent.tools import resolver_info_institucional, resolver_cuentas_abono, ruta_completa

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
    "¡Gracias, lo recibimos! 📄 Tu documento pasará a Contabilidad y/o "
    "Créditos. Le estaremos informando sobre su trámite. Si necesitas algo "
    'más escribe "Menú" para regresar al menú inicial.'
)

# Respuesta fija cuando el socio toca la opción "Finalizar conversación"
# de cualquier menú (Menú A, Menú B, o el menú de opciones que se envía
# tras la plantilla de autorización). No pasa por Claude: es un botón, no
# texto libre, así que no hay ambigüedad que interpretar — no tiene
# sentido arriesgar una falla de la API justo en la despedida.
MENSAJE_DESPEDIDA = (
    "¡Gracias por escribirnos! 🙌 Fue un gusto ayudarte. Si necesitas algo "
    "más, aquí estaré — solo escríbeme cuando quieras. ¡Que tengas un buen día!"
)

# Respuesta fija cuando el socio presiona el botón "Sí" para hablar con el
# Asesor personal. No pasa por Claude: garantiza que SIEMPRE se
# escale a un humano, sin depender de que el modelo interprete el botón.
MENSAJE_ASESOR_CONFIRMADO = (
    "¡Listo! 🙌 Ya avisé a nuestro Asesor personal, en breve te "
    "atenderá aquí mismo en este chat."
)

# La primera respuesta a la plantilla "Autorización de info (no socios
# BN)" se maneja 100% en código (sin pasar por Claude): varias pruebas
# reales mostraron que depender del modelo para esto (enviar el paquete +
# mostrar el menú + el link, todo junto) no era confiable — a veces no
# enviaba el archivo, a veces escalaba a un humano sin motivo, etc.
MARCADOR_PLANTILLA_AUTORIZACION = "[plantilla enviada: Autorización de info (no socios BN)]"

MENSAJE_NEGATIVA_AUTORIZACION = (
    "Disculpa la molestia 🙏 Quedamos atentos — no dudes en escribirnos "
    "si más adelante deseas recibir esta información."
)

MENSAJE_INFO_AUTORIZACION_ENVIADA = (
    "¡Listo! Te acabo de enviar la información sobre Coosermul BN 📎. "
    "También puedes escribirnos directo aquí: https://wa.me/51996899924"
)

MENU_B_TEXTO = "¿En qué te ayudo? Elige una opción:"
MENU_B_BOTON = "Ver opciones"
MENU_B_FILAS = [
    {"id": "1", "titulo": "Necesito información", "descripcion": ""},
    {"id": "2", "titulo": "Quiero inscribirme", "descripcion": "Como socio nuevo"},
    {"id": "3", "titulo": "Asesor personal", "descripcion": ""},
    {"id": "4", "titulo": "Finalizar conversación", "descripcion": ""},
]


def _es_primera_respuesta_a_autorizacion(historial: list[dict]) -> bool:
    """
    True si el socio todavía no respondió nunca a esta plantilla — aunque
    se la hayan reenviado más de una vez sin que conteste (ej. un nuevo
    envío meses después). Antes exigía `len(historial) == 1`, lo que
    fallaba justo en ese caso: al reenviar la plantilla, el historial
    pasa a tener 2+ marcadores y la respuesta terminaba en manos de
    Claude en vez de en este flujo determinístico.
    """
    return bool(historial) and all(
        m["content"].startswith(MARCADOR_PLANTILLA_AUTORIZACION) for m in historial
    )


def _es_negativa_clara(texto: str) -> bool:
    """
    Detecta una negativa de forma flexible: basta con que la palabra "no"
    aparezca en cualquier parte del mensaje (ej. "ahora no, gracias", "no
    por el momento", "no, no me interesa"). Es intencionalmente amplia:
    ante la duda, es preferible NO mandar información no solicitada a un
    trabajador que no dio su autorización clara.
    """
    t = (texto or "").strip().lower()
    return bool(re.search(r"\bno\b", t))


# Mensaje genérico para cuando la respuesta a una plantilla no encaja
# claramente en ningún caso reconocido (ni negativa, ni un "sí" claro,
# ni un agradecimiento) — solo se le deriva a un número de contacto, sin
# escalar al Asesor personal ni asumir qué es lo que quiere.
PALABRAS_POSITIVAS_AUTORIZACION = {
    "si", "sí", "ok", "okay", "okey", "dale", "claro", "bueno", "acepto",
    "quiero", "interesa", "envia", "envía", "manda", "mandame", "mándame",
    "porfavor", "porfa",
}


def _es_positiva_clara_autorizacion(texto: str) -> bool:
    t = (texto or "").strip().lower()
    if re.search(r"\bpor favor\b", t):
        return True
    palabras = set(re.findall(r"[a-záéíóúñ]+", t))
    return bool(palabras & PALABRAS_POSITIVAS_AUTORIZACION)


# La primera respuesta a la plantilla "Recordatorio de pago" también se
# maneja 100% en código, por la misma razón que la de autorización: no
# es confiable depender de que Claude use la herramienta correcta y
# escriba el texto exacto en el mismo turno, todas las veces.
MARCADOR_PLANTILLA_RECORDATORIO = "[plantilla enviada: Recordatorio de pago]"

PALABRAS_YA_PAGO = (
    "ya pagu", "ya pague", "ya pagué", "ya cancel", "ya deposit",
    "ya transfer", "esta pagado", "está pagado", "esta cancelado",
    "está cancelado", "es un error", "eso es un error", "esta mal",
    "está mal", "no me corresponde", "no corresponde", "no es correcto",
)

MENSAJE_YA_PAGO_RECORDATORIO = (
    "Las disculpas del caso 🙏 Por favor ignora el recordatorio de pago "
    "— vamos a informar a Sistemas para que no vuelva a pasar."
)

MENSAJE_CUENTAS_ABONO_RECORDATORIO = (
    "Sabemos que es descuento por planilla, solo para que tenga en "
    "cuenta y sepa cuánto es lo que le tienen que descontar. En caso no "
    "cubra su descuento, puede abonar a nuestras cuentas. Mayor "
    "información al N° 996899924 ó N° 996899927."
)

MENSAJE_AGRADECIMIENTO_RECORDATORIO = "Muy agradecido por su atención."

# Palabras de un simple acuse de recibo (ej. "ok", "gracias", "ok
# gracias") — en ese caso el bot solo agradece y NO manda las cuentas de
# abono (evita spamear a alguien que solo estaba confirmando que leyó).
PALABRAS_AGRADECIMIENTO = {
    "ok", "okay", "okey", "vale", "gracias", "entendido", "listo",
    "perfecto", "bien", "genial",
}
PALABRAS_RELLENO_AGRADECIMIENTO = {"muchas", "mil", "de", "acuerdo", "todo", "esta", "está", "super", "súper"}


def _es_primera_respuesta_a_recordatorio(historial: list[dict]) -> bool:
    """
    True si el socio todavía no respondió nunca a esta plantilla — aunque
    se la hayan reenviado más de una vez sin respuesta (ej. el
    recordatorio del mes siguiente, antes de que conteste al anterior).
    Antes exigía `len(historial) == 1`, lo que fallaba justo en ese caso:
    al reenviar la plantilla, el historial pasa a tener 2+ marcadores y
    la respuesta terminaba en manos de Claude en vez de en este flujo
    determinístico (causa del mensaje de error técnico reportado).
    """
    return bool(historial) and all(
        m["content"].startswith(MARCADOR_PLANTILLA_RECORDATORIO) for m in historial
    )


def _es_reclamo_ya_pago(texto: str) -> bool:
    t = (texto or "").strip().lower()
    return any(p in t for p in PALABRAS_YA_PAGO)


def _es_agradecimiento_simple(texto: str) -> bool:
    """True para un acuse de recibo corto sin preguntas (ej. "ok", "ok gracias")."""
    t = (texto or "").strip().lower()
    if "?" in t or "¿" in t:
        return False
    palabras = re.findall(r"[a-záéíóúñ]+", t)
    if not palabras or len(palabras) > 5:
        return False
    tiene_agradecimiento = any(p in PALABRAS_AGRADECIMIENTO for p in palabras)
    todas_validas = all(
        p in PALABRAS_AGRADECIMIENTO or p in PALABRAS_RELLENO_AGRADECIMIENTO for p in palabras
    )
    return tiene_agradecimiento and todas_validas


# Mensaje para cuando la respuesta a una plantilla no encaja claramente
# en ningún caso reconocido — se deriva a un Asesor personal con el link
# de WhatsApp de AMBOS números de contacto (996899924 y 996899927), en
# vez de asumir qué necesita o de escalar internamente.
MENSAJE_DERIVACION_ASESOR = (
    "Para una amplia información, comunícate directo con nuestro Asesor "
    "personal: https://wa.me/51996899924 o https://wa.me/51996899927"
)
MENSAJE_NO_RECONOCIDO_PLANTILLA = MENSAJE_DERIVACION_ASESOR

PALABRAS_SOLICITUD_INFO_RECORDATORIO = (
    "cuenta", "cuentas", "pagar", "pago", "monto", "informacion",
    "información", "deuda", "abono", "banco", "numero", "número",
    "cuanto", "cuánto", "descuento", "planilla", "cuota",
)


def _es_solicitud_info_clara_recordatorio(texto: str) -> bool:
    t = (texto or "").strip().lower()
    return any(p in t for p in PALABRAS_SOLICITUD_INFO_RECORDATORIO)


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

            # Meta reportó que un envío nuestro (plantilla, documento, texto)
            # NO se pudo entregar de verdad, aunque la API lo haya aceptado
            # en su momento (ej. fuera de la ventana de 24h, plantilla
            # rechazada). Lo dejamos como mensaje visible en el chat para
            # que el equipo se entere sin tener que revisar logs.
            if msg.tipo == "estado_fallido":
                logger.warning(f"Registrando entrega fallida a {msg.telefono}: {msg.texto}")
                await guardar_mensaje(
                    msg.telefono, "sistema", f"⚠️ No se pudo entregar un mensaje anterior: {msg.texto}"
                )
                continue

            # Documentos/imágenes (ej. comprobantes de pago): respuesta fija,
            # sin pasar por Claude, para garantizar el mensaje exacto.
            if msg.tipo in ("document", "image"):
                logger.info(f"Adjunto ({msg.tipo}) de {msg.telefono}")
                respuesta = MENSAJE_COMPROBANTE_RECIBIDO
                registro = msg.texto or f"[{msg.tipo} adjunto sin descripción]"

                # Descargar y guardar el archivo real para que el equipo
                # pueda verlo/descargarlo desde el panel /admin.
                if msg.media_id:
                    descarga = await proveedor.descargar_media(msg.media_id)
                    if descarga:
                        contenido_bytes, mime_type = descarga
                        nombre_archivo = msg.nombre_archivo or f"adjunto_{msg.mensaje_id}"
                        adjunto_id = await guardar_adjunto(
                            msg.telefono, nombre_archivo, mime_type, contenido_bytes
                        )
                        etiqueta = f"[[adjunto:{adjunto_id}]]"
                        registro = f"{etiqueta} {registro}".strip()
                    else:
                        logger.error(f"No se pudo descargar el adjunto {msg.media_id} de {msg.telefono}")

                await guardar_mensaje(msg.telefono, "user", registro)
                await guardar_mensaje(msg.telefono, "assistant", respuesta)
                await proveedor.enviar_mensaje(msg.telefono, respuesta)
                logger.info(f"Respuesta a {msg.telefono}: {respuesta}")
                continue

            # Botón "Sí, hablar con un asesor": escalamos DIRECTO, sin pasar
            # por Claude, para garantizar que siempre funcione igual.
            if msg.tipo == "boton" and msg.boton_id == "asesor_si":
                logger.info(f"Boton 'asesor_si' presionado por {msg.telefono}")
                respuesta = MENSAJE_ASESOR_CONFIRMADO
                await guardar_mensaje(msg.telefono, "user", f"[botón] {msg.texto or 'Sí'}")
                await guardar_mensaje(msg.telefono, "assistant", respuesta)
                await proveedor.enviar_mensaje(msg.telefono, respuesta)
                await activar_modo_humano(msg.telefono)
                logger.info(f"Respuesta a {msg.telefono}: {respuesta}")
                continue

            # Botón "No": lo tratamos como un pedido de volver al menú, y
            # sigue el flujo normal de abajo (pasa por Claude como texto).
            if msg.tipo == "boton" and msg.boton_id == "asesor_no":
                msg.texto = "No, gracias. Muéstrame el menú."

            # Opción "Finalizar conversación" (Menú A, Menú B, o el menú
            # que se envía tras la plantilla de autorización): despedida
            # fija, sin pasar por Claude.
            if msg.tipo == "boton" and (msg.texto or "").strip() == "Finalizar conversación":
                logger.info(f"'Finalizar conversación' elegido por {msg.telefono}")
                respuesta = MENSAJE_DESPEDIDA
                await guardar_mensaje(msg.telefono, "user", f"[opción de menú] {msg.texto}")
                await guardar_mensaje(msg.telefono, "assistant", respuesta)
                await proveedor.enviar_mensaje(msg.telefono, respuesta)
                logger.info(f"Respuesta a {msg.telefono}: {respuesta}")
                continue

            # Mensajes de texto vacíos: no hay nada que procesar
            if not msg.texto:
                continue

            logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            # Si la conversación ya está en manos de un humano, el bot NO
            # responde — solo guarda el mensaje para que el equipo lo vea
            # y conteste desde el panel /admin, en el mismo chat.
            if await esta_en_modo_humano(msg.telefono):
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                logger.info(f"{msg.telefono} esta en modo humano, el bot no responde")
                continue

            # Obtener historial ANTES de guardar el mensaje actual
            # (brain.py agrega el mensaje actual, evitando duplicados)
            historial = await obtener_historial(msg.telefono)

            # Primera respuesta a la plantilla de autorización de info:
            # manejo 100% determinístico, sin pasar por Claude (ver nota
            # arriba en MARCADOR_PLANTILLA_AUTORIZACION).
            if _es_primera_respuesta_a_autorizacion(historial):
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                if _es_negativa_clara(msg.texto):
                    respuesta = MENSAJE_NEGATIVA_AUTORIZACION
                    await guardar_mensaje(msg.telefono, "assistant", respuesta)
                    await proveedor.enviar_mensaje(msg.telefono, respuesta)
                elif not _es_positiva_clara_autorizacion(msg.texto):
                    respuesta = MENSAJE_NO_RECONOCIDO_PLANTILLA
                    await guardar_mensaje(msg.telefono, "assistant", respuesta)
                    await proveedor.enviar_mensaje(msg.telefono, respuesta)
                else:
                    archivos = resolver_info_institucional()
                    for nombre_archivo in archivos:
                        ok = await proveedor.enviar_documento(
                            msg.telefono, ruta_completa(nombre_archivo), nombre_archivo
                        )
                        if not ok:
                            logger.error(
                                f"No se pudo enviar {nombre_archivo} a {msg.telefono} "
                                "(paquete de información, respuesta a autorización)"
                            )
                    respuesta = MENSAJE_INFO_AUTORIZACION_ENVIADA
                    await guardar_mensaje(msg.telefono, "assistant", respuesta)
                    await proveedor.enviar_mensaje(msg.telefono, respuesta)
                    await proveedor.enviar_lista(msg.telefono, MENU_B_TEXTO, MENU_B_BOTON, MENU_B_FILAS)
                logger.info(f"Respuesta a {msg.telefono} (autorizacion info): {respuesta}")
                continue

            # Primera respuesta a la plantilla de recordatorio de pago:
            # manejo 100% determinístico, sin pasar por Claude (ver nota
            # arriba en MARCADOR_PLANTILLA_RECORDATORIO).
            if _es_primera_respuesta_a_recordatorio(historial):
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                if _es_reclamo_ya_pago(msg.texto):
                    respuesta = MENSAJE_YA_PAGO_RECORDATORIO
                    await guardar_mensaje(msg.telefono, "assistant", respuesta)
                    await proveedor.enviar_mensaje(msg.telefono, respuesta)
                elif _es_agradecimiento_simple(msg.texto):
                    respuesta = MENSAJE_AGRADECIMIENTO_RECORDATORIO
                    await guardar_mensaje(msg.telefono, "assistant", respuesta)
                    await proveedor.enviar_mensaje(msg.telefono, respuesta)
                elif not _es_solicitud_info_clara_recordatorio(msg.texto):
                    respuesta = MENSAJE_NO_RECONOCIDO_PLANTILLA
                    await guardar_mensaje(msg.telefono, "assistant", respuesta)
                    await proveedor.enviar_mensaje(msg.telefono, respuesta)
                else:
                    archivos = resolver_cuentas_abono()
                    for nombre_archivo in archivos:
                        ok = await proveedor.enviar_documento(
                            msg.telefono, ruta_completa(nombre_archivo), nombre_archivo
                        )
                        if not ok:
                            logger.error(
                                f"No se pudo enviar {nombre_archivo} a {msg.telefono} "
                                "(cuentas de abono, respuesta a recordatorio de pago)"
                            )
                    respuesta = MENSAJE_CUENTAS_ABONO_RECORDATORIO
                    await guardar_mensaje(msg.telefono, "assistant", respuesta)
                    await proveedor.enviar_mensaje(msg.telefono, respuesta)
                logger.info(f"Respuesta a {msg.telefono} (recordatorio pago): {respuesta}")
                continue

            # Generar respuesta con Claude (puede incluir documentos a enviar
            # o pedir escalar la conversación a un humano)
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

            # Si Claude pidió mostrar los botones Sí/No (ej. para ofrecer
            # hablar con un asesor), los enviamos como mensaje aparte.
            botones = resultado.get("botones")
            if botones:
                await proveedor.enviar_botones(
                    msg.telefono, botones["mensaje"], botones["opciones"]
                )

            # Si Claude pidió mostrar un menú de opciones táctil (ej. el
            # menú principal, tipos de crédito, productos del bazar), lo
            # enviamos como mensaje aparte.
            lista = resultado.get("lista")
            if lista:
                await proveedor.enviar_lista(
                    msg.telefono, lista["texto"], lista["texto_boton"], lista["filas"]
                )

            logger.info(f"Respuesta a {msg.telefono}: {respuesta}")

            # Si Claude pidió escalar, activamos el modo humano DESPUÉS de
            # enviar la respuesta (para que el bot se despida antes de callar)
            if resultado.get("escalar"):
                await activar_modo_humano(msg.telefono)
                logger.info(f"Conversacion con {msg.telefono} pasada a modo humano: {resultado.get('motivo_escalamiento', '')}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
