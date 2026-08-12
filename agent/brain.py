# agent/brain.py — Cerebro del agente: conexión con Claude API
# Generado por AgentKit

"""
Lógica de IA del agente. Lee el system prompt de prompts.yaml
y genera respuestas usando la API de Anthropic Claude.

Además de texto, el agente puede "usar herramientas" (tool use) para
activar el envío de documentos PDF reales por WhatsApp cuando la
conversación lo amerita (ej. el socio pide tramitar un crédito).
"""

import os
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.tools import resolver_paquete_credito, resolver_paquete_inscripcion, ruta_completa

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente de Anthropic
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Modelo de Claude a usar (el más reciente Sonnet disponible)
MODELO = "claude-sonnet-5"

# Herramientas que Claude puede usar para activar el envío de documentos.
# Los nombres de archivo NO se le muestran al modelo: el modelo solo dice
# QUÉ paquete o perfil, y nuestro código (agent/tools.py) resuelve los
# archivos exactos a enviar.
HERRAMIENTAS = [
    {
        "name": "enviar_paquete_credito",
        "description": (
            "Envía por WhatsApp los 3 documentos necesarios para tramitar "
            "cualquier crédito en efectivo (Solicitud de Créditos, Pagaré, "
            "Contrato de Crédito). Úsala cuando el socio confirme que quiere "
            "tramitar/solicitar un crédito en efectivo (sola firma, "
            "garantizado, gratificación, etc. — NO para el Bazar), sin "
            "importar el monto o tipo de crédito."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "enviar_paquete_inscripcion",
        "description": (
            "Envía por WhatsApp los documentos necesarios para inscribirse "
            "como socio nuevo de Coosermul BN. Úsala cuando el socio ya te "
            "haya confirmado su perfil (activo, pensionista, cesante, feban "
            "o tercero) y quiera tramitar su afiliación."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "perfil": {
                    "type": "string",
                    "enum": ["activo", "pensionista", "cesante", "feban", "tercero"],
                    "description": "Perfil del nuevo socio",
                }
            },
            "required": ["perfil"],
        },
    },
]


def cargar_config_prompts() -> dict:
    """Lee toda la configuración desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    """Lee el system prompt desde config/prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("system_prompt", "Eres un asistente útil. Responde en español.")


def obtener_mensaje_error() -> str:
    """Retorna el mensaje de error configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("error_message", "Lo siento, estoy teniendo problemas técnicos. Por favor intenta de nuevo en unos minutos.")


def obtener_mensaje_fallback() -> str:
    """Retorna el mensaje de fallback configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("fallback_message", "Disculpa, no entendí tu mensaje. ¿Podrías reformularlo?")


def _texto_de(response) -> str:
    """Une los bloques de tipo 'text' de una respuesta de Claude."""
    return "".join(
        bloque.text for bloque in response.content if getattr(bloque, "type", None) == "text"
    ).strip()


def _ejecutar_herramienta(nombre: str, entrada: dict) -> tuple[str, list[dict]]:
    """
    Ejecuta una herramienta localmente (sin llamar a ninguna API externa).

    Returns:
        (resultado_para_claude, documentos_a_enviar)
        documentos_a_enviar: lista de {"nombre_archivo": ..., "ruta": ...}
    """
    if nombre == "enviar_paquete_credito":
        archivos = resolver_paquete_credito()
    elif nombre == "enviar_paquete_inscripcion":
        archivos = resolver_paquete_inscripcion(entrada.get("perfil", ""))
    else:
        return f"Herramienta desconocida: {nombre}", []

    if not archivos:
        return "No se encontraron documentos para ese perfil/paquete.", []

    documentos = [
        {"nombre_archivo": nombre_archivo, "ruta": ruta_completa(nombre_archivo)}
        for nombre_archivo in archivos
    ]
    resultado = f"Documentos preparados y en cola de envío: {', '.join(archivos)}."
    return resultado, documentos


async def generar_respuesta(mensaje: str, historial: list[dict]) -> dict:
    """
    Genera una respuesta usando Claude API. Puede incluir documentos a
    enviar si Claude decide usar una herramienta durante la conversación.

    Args:
        mensaje: El mensaje nuevo del usuario
        historial: Lista de mensajes anteriores [{"role": "user/assistant", "content": "..."}]

    Returns:
        {"texto": str, "documentos": [{"nombre_archivo": str, "ruta": str}, ...]}
    """
    vacio = {"texto": obtener_mensaje_fallback(), "documentos": []}
    if not mensaje or not mensaje.strip():
        return vacio

    system_prompt = cargar_system_prompt()

    mensajes = [{"role": m["role"], "content": m["content"]} for m in historial]
    mensajes.append({"role": "user", "content": mensaje})

    documentos_totales: list[dict] = []

    try:
        # Hasta 2 vueltas: 1) Claude puede pedir usar una herramienta,
        # 2) le devolvemos el resultado y Claude da la respuesta final.
        for _ in range(2):
            response = await client.messages.create(
                model=MODELO,
                max_tokens=1024,
                system=system_prompt,
                messages=mensajes,
                tools=HERRAMIENTAS,
            )

            if response.stop_reason != "tool_use":
                texto = _texto_de(response)
                if not texto:
                    logger.warning("Claude no devolvio texto (solo bloques no-texto)")
                    return {"texto": obtener_mensaje_error(), "documentos": documentos_totales}
                logger.info(f"Respuesta generada ({response.usage.input_tokens} in / {response.usage.output_tokens} out)")
                return {"texto": texto, "documentos": documentos_totales}

            # Claude pidió usar una o más herramientas: las ejecutamos y
            # le devolvemos el resultado para que continúe la conversación.
            mensajes.append({"role": "assistant", "content": response.content})
            resultados_tool = []
            for bloque in response.content:
                if getattr(bloque, "type", None) == "tool_use":
                    logger.info(f"Claude solicito herramienta: {bloque.name}({bloque.input})")
                    resultado_texto, documentos = _ejecutar_herramienta(bloque.name, bloque.input or {})
                    documentos_totales.extend(documentos)
                    resultados_tool.append({
                        "type": "tool_result",
                        "tool_use_id": bloque.id,
                        "content": resultado_texto,
                    })
            mensajes.append({"role": "user", "content": resultados_tool})

        # Si tras 2 vueltas sigue pidiendo herramientas, cortamos con un mensaje genérico.
        logger.warning("Se agotaron los turnos de tool-use sin respuesta final de texto")
        return {
            "texto": "Listo, ya te envié la información solicitada. ¿Necesitas algo más?",
            "documentos": documentos_totales,
        }

    except Exception:
        logger.exception("Error Claude API")
        return {"texto": obtener_mensaje_error(), "documentos": documentos_totales}
