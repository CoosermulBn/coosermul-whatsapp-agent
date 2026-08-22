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

from agent.tools import (
    resolver_paquete_credito,
    resolver_paquete_inscripcion,
    resolver_info_odontologico,
    resolver_info_institucional,
    ruta_completa,
    verificar_socio,
)

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
        "name": "verificar_socio",
        "description": (
            "Busca un DNI en el padrón oficial de socios de Coosermul BN "
            "para saber si la persona ya es socia. Úsala apenas el usuario "
            "te dé su número de DNI al inicio de la conversación (o en "
            "cualquier momento que lo comparta para verificar su condición "
            "de socio). Retorna si es socio y, si lo es, su apellido "
            "paterno, materno, nombres y código."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dni": {"type": "string", "description": "Número de DNI (8 dígitos)"}
            },
            "required": ["dni"],
        },
    },
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
    {
        "name": "enviar_info_centro_odontologico",
        "description": (
            "Envía por WhatsApp la lista de precios (imagen) del Centro "
            "Odontológico propio de Coosermul BN. Úsala cuando el socio "
            "elija la opción 'Centro Odontológico' del menú, o pregunte "
            "por precios o servicios dentales de la cooperativa."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "enviar_info_institucional",
        "description": (
            "Envía por WhatsApp el paquete de información institucional "
            "de Coosermul BN (carta de presentación, tríptico y catálogo). "
            "Úsala cuando un trabajador del Banco de la Nación que NO es "
            "socio responda con interés (cualquier respuesta que no sea "
            "una negativa clara) al mensaje inicial en el que le "
            "pedimos autorización para enviarle información."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "pedir_boleta_y_ofrecer_asesor",
        "description": (
            "Envía el mensaje (con botones Sí/No) pidiéndole al socio su "
            "boleta de pago para evaluar su capacidad de crédito, y "
            "ofreciéndole hablar ahora mismo con el Asesor personal. "
            "El texto exacto y los botones ya están armados por el "
            "sistema — tú solo indicas brevemente de qué trámite se "
            "trata. Úsala SIEMPRE que el socio confirme que quiere "
            "tramitar un crédito en efectivo, o en cuanto sepas su perfil "
            "para la inscripción — en vez de escribir tú mismo el pedido "
            "de la boleta como texto plano, usa esta herramienta para "
            "garantizar que el mensaje sea completo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tramite": {
                    "type": "string",
                    "description": (
                        "Breve descripción del trámite, ej. 'tu "
                        "inscripción como pensionista' o 'tu crédito a "
                        "sola firma'"
                    ),
                }
            },
            "required": ["tramite"],
        },
    },
    {
        "name": "mostrar_opciones",
        "description": (
            "Muestra una lista de 2 a 10 opciones NUMERADAS como un menú "
            "táctil de WhatsApp (el socio puede tocar una opción, o "
            "seguir respondiendo con el número por texto si prefiere). "
            "Úsala SIEMPRE que vayas a presentar 2 o más opciones "
            "numeradas — el menú principal, submenús, tipos de crédito, "
            "productos del bazar, perfiles de inscripción, etc. — en vez "
            "de escribir la lista numerada como texto plano (ej. '1️⃣ "
            "Créditos\\n2️⃣ Bazar'). El texto de introducción (todo lo "
            "que dirías antes de la lista) va en el parámetro `texto` de "
            "esta misma herramienta, NO lo repitas en tu respuesta final."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": (
                        "Texto de introducción antes de la lista, ej. "
                        "'¿En qué te ayudo? Elige una opción:'"
                    ),
                },
                "texto_boton": {
                    "type": "string",
                    "description": "Texto corto del botón que abre la lista, ej. 'Ver opciones' (máx 20 caracteres).",
                },
                "opciones": {
                    "type": "array",
                    "description": (
                        "Las opciones, en el mismo orden en que las "
                        "numerarías (1, 2, 3...). Máximo 10."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "titulo": {
                                "type": "string",
                                "description": "Nombre corto de la opción (máx 24 caracteres).",
                            },
                            "descripcion": {
                                "type": "string",
                                "description": "Detalle adicional opcional, ej. precio o resumen (máx 72 caracteres).",
                            },
                        },
                        "required": ["titulo"],
                    },
                },
            },
            "required": ["texto", "opciones"],
        },
    },
    {
        "name": "preguntar_hablar_con_asesor",
        "description": (
            "Muestra dos botones táctiles (Sí / No) para preguntarle al "
            "socio si quiere que lo comuniques AHORA MISMO con el "
            "Asesor personal (asesor humano), en vez de escribir la "
            "pregunta como texto plano. Úsala cada vez que le ofrezcas "
            "esta opción explícitamente (ej. después de pedirle su boleta "
            "de pago). En tu respuesta de texto final de ese mismo turno "
            "NO repitas la pregunta '¿quieres hablar con un asesor?' — los "
            "botones ya la muestran por separado; solo incluye lo demás "
            "que tengas que decir antes de eso."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mensaje": {
                    "type": "string",
                    "description": (
                        "Texto que acompaña a los botones, ej. 'Si "
                        "prefieres, también puedo comunicarte ahora mismo "
                        "con nuestro Asesor personal para que te "
                        "ayude directamente.'"
                    ),
                }
            },
            "required": ["mensaje"],
        },
    },
    {
        "name": "escalar_a_humano",
        "description": (
            "Avisa al equipo humano de Coosermul BN que este socio necesita "
            "hablar con una persona, DENTRO de esta misma conversación de "
            "WhatsApp (no lo mandes a otro número ni canal). Úsala cuando el "
            "socio pida explícitamente hablar con un asesor/humano, o cuando "
            "la consulta claramente no la puedes resolver tú (ej. reclamos, "
            "casos muy específicos o delicados)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": "Resumen breve de por qué el socio necesita un humano",
                }
            },
            "required": ["motivo"],
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


def _ejecutar_herramienta(nombre: str, entrada: dict) -> dict:
    """
    Ejecuta una herramienta localmente (sin llamar a ninguna API externa).

    Returns:
        {"resultado_texto": str, "documentos": [...], "escalar": bool, "motivo": str}
    """
    if nombre == "verificar_socio":
        resultado = verificar_socio(entrada.get("dni", ""))
        if resultado.get("es_socio"):
            texto = (
                f"ES SOCIO. Apellido paterno: {resultado['apellido_paterno']}. "
                f"Apellido materno: {resultado['apellido_materno']}. "
                f"Nombres: {resultado['nombres']}. Código: {resultado['codigo']}."
            )
        else:
            texto = "NO ES SOCIO. Ese DNI no aparece en el padrón de socios."
        return {"resultado_texto": texto, "documentos": [], "escalar": False}

    if nombre == "enviar_paquete_credito":
        archivos = resolver_paquete_credito()
        if not archivos:
            return {"resultado_texto": "No se encontraron documentos.", "documentos": [], "escalar": False}
        documentos = [
            {"nombre_archivo": n, "ruta": ruta_completa(n)} for n in archivos
        ]
        return {
            "resultado_texto": f"Documentos preparados y en cola de envío: {', '.join(archivos)}.",
            "documentos": documentos,
            "escalar": False,
        }

    if nombre == "enviar_paquete_inscripcion":
        archivos = resolver_paquete_inscripcion(entrada.get("perfil", ""))
        if not archivos:
            return {"resultado_texto": "No se encontraron documentos para ese perfil.", "documentos": [], "escalar": False}
        documentos = [
            {"nombre_archivo": n, "ruta": ruta_completa(n)} for n in archivos
        ]
        return {
            "resultado_texto": f"Documentos preparados y en cola de envío: {', '.join(archivos)}.",
            "documentos": documentos,
            "escalar": False,
        }

    if nombre == "enviar_info_centro_odontologico":
        archivos = resolver_info_odontologico()
        documentos = [
            {"nombre_archivo": n, "ruta": ruta_completa(n)} for n in archivos
        ]
        return {
            "resultado_texto": f"Documento preparado y en cola de envío: {', '.join(archivos)}.",
            "documentos": documentos,
            "escalar": False,
        }

    if nombre == "enviar_info_institucional":
        archivos = resolver_info_institucional()
        documentos = [
            {"nombre_archivo": n, "ruta": ruta_completa(n)} for n in archivos
        ]
        return {
            "resultado_texto": f"Documentos preparados y en cola de envío: {', '.join(archivos)}.",
            "documentos": documentos,
            "escalar": False,
        }

    if nombre == "pedir_boleta_y_ofrecer_asesor":
        tramite = entrada.get("tramite", "").strip() or "tu trámite"
        mensaje_botones = (
            f"Antes de enviarte los documentos para {tramite}, necesitamos "
            "evaluar tu capacidad de crédito. ¿Nos podrías enviar tu boleta "
            "de pago (o de pensión) más reciente? En cuanto la evaluemos, "
            "te enviaremos los documentos.\n\n"
            "Si prefieres, también puedes comunicarte ahora mismo con "
            "nuestro Asesor personal para que te ayude directamente al "
            "siguiente link: https://wa.me/51996899924"
        )
        return {
            "resultado_texto": "Mensaje con botones mostrado al socio (pedido de boleta + opción de asesor).",
            "documentos": [],
            "escalar": False,
            "botones": {
                "mensaje": mensaje_botones,
                "opciones": [
                    {"id": "asesor_si", "titulo": "Sí"},
                    {"id": "asesor_no", "titulo": "No"},
                ],
            },
        }

    if nombre == "mostrar_opciones":
        texto_intro = (entrada.get("texto") or "Elige una opción:").strip()
        texto_boton = (entrada.get("texto_boton") or "Ver opciones").strip()[:20]
        opciones_raw = entrada.get("opciones") or []
        filas = []
        for i, op in enumerate(opciones_raw[:10]):
            titulo = str(op.get("titulo", "")).strip()[:24] or f"Opción {i + 1}"
            descripcion = str(op.get("descripcion", "")).strip()[:72]
            filas.append({"id": str(i + 1), "titulo": titulo, "descripcion": descripcion})
        return {
            "resultado_texto": "Menú de opciones táctiles mostrado al socio.",
            "documentos": [],
            "escalar": False,
            "lista": {
                "texto": texto_intro,
                "texto_boton": texto_boton,
                "filas": filas,
            },
        }

    if nombre == "preguntar_hablar_con_asesor":
        mensaje_botones = entrada.get(
            "mensaje", "¿Quieres que te comunique ahora mismo con nuestro Asesor personal?"
        )
        return {
            "resultado_texto": "Botones Sí/No mostrados al socio.",
            "documentos": [],
            "escalar": False,
            "botones": {
                "mensaje": mensaje_botones,
                "opciones": [
                    {"id": "asesor_si", "titulo": "Sí"},
                    {"id": "asesor_no", "titulo": "No"},
                ],
            },
        }

    if nombre == "escalar_a_humano":
        motivo = entrada.get("motivo", "El socio pidió hablar con un asesor.")
        return {
            "resultado_texto": (
                "Escalamiento registrado. El equipo humano fue notificado y va a "
                "responder en este mismo chat de WhatsApp en cuanto pueda."
            ),
            "documentos": [],
            "escalar": True,
            "motivo": motivo,
        }

    return {"resultado_texto": f"Herramienta desconocida: {nombre}", "documentos": [], "escalar": False}


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
    vacio = {"texto": obtener_mensaje_fallback(), "documentos": [], "escalar": False, "motivo_escalamiento": "", "botones": None, "lista": None}
    if not mensaje or not mensaje.strip():
        return vacio

    system_prompt = cargar_system_prompt()

    # La API de Claude solo acepta los roles "user" y "assistant". Los
    # mensajes que escribió un humano del equipo (role="humano", guardados
    # desde el panel /admin) se mapean a "assistant" para que Claude tenga
    # continuidad de la conversación sin romper la llamada a la API.
    mensajes = [
        {
            "role": "assistant" if m["role"] == "humano" else m["role"],
            "content": m["content"],
        }
        for m in historial
    ]
    mensajes.append({"role": "user", "content": mensaje})

    documentos_totales: list[dict] = []
    escalar_total = False
    motivo_total = ""
    botones_total: dict | None = None
    lista_total: dict | None = None

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
                    # Si ya se ejecutó una herramienta útil (documentos
                    # preparados o botones armados), un texto vacío no es
                    # un error real — usamos un remate corto en vez del
                    # mensaje de error genérico.
                    if documentos_totales or botones_total or lista_total:
                        texto = "¡Listo!"
                    else:
                        logger.warning("Claude no devolvio texto (solo bloques no-texto)")
                        return {
                            "texto": obtener_mensaje_error(),
                            "documentos": documentos_totales,
                            "escalar": escalar_total,
                            "motivo_escalamiento": motivo_total,
                            "botones": botones_total,
                            "lista": lista_total,
                        }
                logger.info(f"Respuesta generada ({response.usage.input_tokens} in / {response.usage.output_tokens} out)")
                return {
                    "texto": texto,
                    "documentos": documentos_totales,
                    "escalar": escalar_total,
                    "motivo_escalamiento": motivo_total,
                    "botones": botones_total,
                    "lista": lista_total,
                }

            # Claude pidió usar una o más herramientas: las ejecutamos y
            # le devolvemos el resultado para que continúe la conversación.
            mensajes.append({"role": "assistant", "content": response.content})
            resultados_tool = []
            for bloque in response.content:
                if getattr(bloque, "type", None) == "tool_use":
                    logger.info(f"Claude solicito herramienta: {bloque.name}({bloque.input})")
                    resultado = _ejecutar_herramienta(bloque.name, bloque.input or {})
                    documentos_totales.extend(resultado["documentos"])
                    if resultado.get("escalar"):
                        escalar_total = True
                        motivo_total = resultado.get("motivo", "")
                    if resultado.get("botones"):
                        botones_total = resultado["botones"]
                    if resultado.get("lista"):
                        lista_total = resultado["lista"]
                    resultados_tool.append({
                        "type": "tool_result",
                        "tool_use_id": bloque.id,
                        "content": resultado["resultado_texto"],
                    })
            mensajes.append({"role": "user", "content": resultados_tool})

        # Si tras 2 vueltas sigue pidiendo herramientas, cortamos con un mensaje genérico.
        logger.warning("Se agotaron los turnos de tool-use sin respuesta final de texto")
        return {
            "texto": "Listo, ya te envié la información solicitada. ¿Necesitas algo más?",
            "documentos": documentos_totales,
            "escalar": escalar_total,
            "motivo_escalamiento": motivo_total,
            "botones": botones_total,
            "lista": lista_total,
        }

    except Exception:
        logger.exception("Error Claude API")
        return {
            "texto": obtener_mensaje_error(),
            "documentos": documentos_totales,
            "escalar": escalar_total,
            "motivo_escalamiento": motivo_total,
            "botones": botones_total,
            "lista": lista_total,
        }
