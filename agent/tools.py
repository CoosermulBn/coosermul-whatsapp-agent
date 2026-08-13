# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas del negocio de Coosermul BN.
Estas funciones extienden las capacidades del agente más allá de responder texto.
"""

import os
import csv
import re
import yaml
import logging
from datetime import datetime

logger = logging.getLogger("agentkit")

PADRON_PATH = os.path.join("data", "padron.csv")
_padron_cache: dict[str, dict] | None = None


def _normalizar_dni(dni: str) -> str:
    return re.sub(r"\D", "", dni or "")


def _cargar_padron() -> dict[str, dict]:
    """Carga el padrón de socios en memoria (dni -> datos), una sola vez."""
    global _padron_cache
    if _padron_cache is not None:
        return _padron_cache
    padron = {}
    try:
        with open(PADRON_PATH, "r", encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f):
                dni = _normalizar_dni(fila.get("dni", ""))
                if dni:
                    padron[dni] = fila
    except FileNotFoundError:
        logger.error(f"No se encontró el padrón de socios en {PADRON_PATH}")
    _padron_cache = padron
    logger.info(f"Padron de socios cargado: {len(padron)} registros")
    return padron


def verificar_socio(dni: str) -> dict:
    """
    Busca un DNI en el padrón de socios.

    Returns:
        Si es socio: {"es_socio": True, "apellido_paterno": ..., "apellido_materno": ...,
                       "nombres": ..., "codigo": ...}
        Si no: {"es_socio": False}
    """
    padron = _cargar_padron()
    dni_normalizado = _normalizar_dni(dni)
    registro = padron.get(dni_normalizado)
    if not registro:
        return {"es_socio": False}
    return {
        "es_socio": True,
        "apellido_paterno": (registro.get("apellido_paterno") or "").strip().title(),
        "apellido_materno": (registro.get("apellido_materno") or "").strip().title(),
        "nombres": (registro.get("nombres") or "").strip().title(),
        "codigo": (registro.get("codigo") or "").strip(),
    }


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio."""
    info = cargar_info_negocio()
    return {
        "horario": info.get("negocio", {}).get("horario", "No disponible"),
        "esta_abierto": True,  # TODO: calcular según hora actual y horario
    }


def buscar_en_knowledge(consulta: str) -> str:
    """
    Busca información relevante en los archivos de /knowledge (texto plano,
    markdown, etc.). Para PDFs, ver listar_formatos_disponibles().
    """
    resultados = []
    knowledge_dir = "knowledge"

    if not os.path.exists(knowledge_dir):
        return "No hay archivos de conocimiento disponibles."

    for archivo in os.listdir(knowledge_dir):
        ruta = os.path.join(knowledge_dir, archivo)
        if archivo.startswith(".") or not os.path.isfile(ruta):
            continue
        if archivo.lower().endswith(".pdf"):
            continue  # los PDFs se listan con listar_formatos_disponibles()
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                if consulta.lower() in contenido.lower():
                    resultados.append(f"[{archivo}]: {contenido[:500]}")
        except (UnicodeDecodeError, IOError):
            continue

    if resultados:
        return "\n---\n".join(resultados)
    return "No encontré información específica sobre eso en mis archivos."


# ════════════════════════════════════════════════════════════
# Inscripción de nuevos socios — envío de formatos (caso "Otro")
# ════════════════════════════════════════════════════════════

# Mapa de perfil de socio → nombre exacto del PDF en /knowledge
FORMATOS_INSCRIPCION = {
    "activo": "1.-Solicitud de Ingreso-2025-ACTIVOS Y PENSIONISTAS.pdf",
    "pensionista": "1.-Solicitud de Ingreso-2025-ACTIVOS Y PENSIONISTAS.pdf",
    "cesante": "1.-Solicitud de Ingreso-2025-cesantes 19990.pdf",
    "feban": "1.-Solicitud de Ingreso-2025-FEBAN.pdf",
    "tercero": "1.-Solicitud de Ingreso-2025-terceros.pdf",
}

FORMATOS_DESCUENTO = {
    "activo": "2.-Autorización descuento Planilla activos.pdf",
    "pensionista": "2.-Autorizacion de descuentos pensionistas.pdf",
    "feban": "2.-Autorizacion de descuentos FEBAN.pdf",
    "cts": "10.-Autorización descuento CTS y liquidaciones.pdf",
}

# Documentos fijos adicionales para el paquete de inscripción (todos los perfiles)
FORMATOS_INSCRIPCION_COMUNES = [
    "6.- Declaración Jurada de Direccion.pdf",
    "8.-FICHA DE INSCRIPCCION FPS.pdf",
]

# Paquete B: crédito en efectivo — siempre estos 3, sin importar el tipo/monto
FORMATOS_CREDITO = [
    "5.-SOLICITUD DE CREDITOS.pdf",
    "4.-Pagare.pdf",
    "7.-Contrato de Credito.pdf",
]

# Lista de precios del Centro Odontológico (imagen/PDF informativo).
FORMATO_ODONTOLOGICO = "Centro Odontologico - Lista de precios.pdf"

KNOWLEDGE_DIR = "knowledge"


def ruta_completa(nombre_archivo: str) -> str:
    """Retorna la ruta absoluta/relativa de un archivo dentro de /knowledge."""
    return os.path.join(KNOWLEDGE_DIR, nombre_archivo)


def resolver_paquete_credito() -> list[str]:
    """Retorna los nombres de archivo del paquete de crédito en efectivo (fijo)."""
    return list(FORMATOS_CREDITO)


def resolver_paquete_inscripcion(perfil_socio: str) -> list[str]:
    """
    Retorna los nombres de archivo del paquete de inscripción según el
    perfil del socio ('activo', 'pensionista', 'cesante', 'feban', 'tercero').
    Retorna lista vacía si el perfil no se reconoce.
    """
    perfil = (perfil_socio or "").strip().lower()
    solicitud = FORMATOS_INSCRIPCION.get(perfil)
    descuento = FORMATOS_DESCUENTO.get(perfil)
    if not solicitud:
        return []
    archivos = [solicitud]
    if descuento:
        archivos.append(descuento)
    archivos.extend(FORMATOS_INSCRIPCION_COMUNES)
    return archivos


def resolver_info_odontologico() -> list[str]:
    """Retorna el archivo de la lista de precios del Centro Odontológico."""
    return [FORMATO_ODONTOLOGICO]


def listar_formatos_disponibles() -> list[str]:
    """Lista los PDFs disponibles en /knowledge (formatos y material informativo)."""
    knowledge_dir = "knowledge"
    if not os.path.exists(knowledge_dir):
        return []
    return sorted(
        f for f in os.listdir(knowledge_dir)
        if f.lower().endswith(".pdf")
    )


def sugerir_formato_inscripcion(perfil_socio: str) -> str | None:
    """
    Dado el perfil del socio ('activo', 'pensionista', 'cesante', 'feban',
    'tercero'), retorna el nombre del formato de Solicitud de Ingreso que le
    corresponde, o None si el perfil no es reconocido.
    """
    return FORMATOS_INSCRIPCION.get(perfil_socio.strip().lower())


def sugerir_formato_descuento(perfil_socio: str) -> str | None:
    """Retorna el formato de Autorización de Descuento que corresponde al perfil."""
    return FORMATOS_DESCUENTO.get(perfil_socio.strip().lower())


# ════════════════════════════════════════════════════════════
# Agendar citas (ej. consultorio odontológico convenio)
# ════════════════════════════════════════════════════════════

def solicitar_cita(telefono: str, motivo: str, dia_preferido: str = "", hora_preferida: str = "") -> dict:
    """
    Registra una solicitud de cita del cliente para que el equipo humano la
    confirme (no hay calendario en línea todavía). Guarda un registro simple
    en un archivo de texto para revisión manual.
    """
    os.makedirs("data", exist_ok=True)
    linea = (
        f"{datetime.utcnow().isoformat()} | tel={telefono} | motivo={motivo} "
        f"| dia={dia_preferido} | hora={hora_preferida}\n"
    )
    with open("data/citas_pendientes.txt", "a", encoding="utf-8") as f:
        f.write(linea)
    logger.info(f"Cita solicitada: {linea.strip()}")
    return {"registrada": True, "mensaje": "Tu solicitud de cita quedó registrada, el equipo la confirmará."}


# ════════════════════════════════════════════════════════════
# Tomar pedidos del Bazar
# ════════════════════════════════════════════════════════════

def registrar_pedido_bazar(telefono: str, producto: str, notas: str = "") -> dict:
    """Registra el interés/pedido de un producto del Bazar para seguimiento humano."""
    os.makedirs("data", exist_ok=True)
    linea = f"{datetime.utcnow().isoformat()} | tel={telefono} | producto={producto} | notas={notas}\n"
    with open("data/pedidos_bazar.txt", "a", encoding="utf-8") as f:
        f.write(linea)
    logger.info(f"Pedido de bazar registrado: {linea.strip()}")
    return {"registrado": True, "mensaje": "Tu interés en el producto quedó registrado, te confirmarán precio y cuotas vigentes."}


# ════════════════════════════════════════════════════════════
# Leads / ventas de créditos y afiliación
# ════════════════════════════════════════════════════════════

def registrar_lead(telefono: str, interes: str, nombre: str = "") -> dict:
    """Registra un lead interesado en un crédito o en afiliarse como socio."""
    os.makedirs("data", exist_ok=True)
    linea = f"{datetime.utcnow().isoformat()} | tel={telefono} | nombre={nombre} | interes={interes}\n"
    with open("data/leads.txt", "a", encoding="utf-8") as f:
        f.write(linea)
    logger.info(f"Lead registrado: {linea.strip()}")
    return {"registrado": True, "mensaje": "Gracias, un asesor de Coosermul BN te contactará pronto."}


# ════════════════════════════════════════════════════════════
# Soporte post-venta
# ════════════════════════════════════════════════════════════

def crear_ticket_soporte(telefono: str, problema: str) -> dict:
    """Crea un ticket simple de soporte para seguimiento del equipo humano."""
    os.makedirs("data", exist_ok=True)
    ticket_id = f"TCK-{int(datetime.utcnow().timestamp())}"
    linea = f"{datetime.utcnow().isoformat()} | id={ticket_id} | tel={telefono} | problema={problema}\n"
    with open("data/tickets_soporte.txt", "a", encoding="utf-8") as f:
        f.write(linea)
    logger.info(f"Ticket creado: {linea.strip()}")
    return {"ticket_id": ticket_id, "mensaje": f"Se creó tu ticket {ticket_id}. El equipo de Coosermul BN te dará seguimiento."}
