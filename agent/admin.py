# agent/admin.py — Panel de administración simple (ver conversaciones)
# Generado por AgentKit

"""
Panel web mínimo, protegido con usuario/contraseña, para que el dueño del
negocio pueda ver qué le están escribiendo los clientes y qué respondió el
agente, sin depender de los logs técnicos de Railway.
"""

import os
import html
import secrets
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from agent.memory import listar_conversaciones, obtener_historial_completo

logger = logging.getLogger("agentkit")
router = APIRouter()
security = HTTPBasic()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

ESTILO = """
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; background:#f4f4f6; margin:0; padding:24px; color:#222; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  .sub { color:#666; margin-bottom:20px; font-size:14px; }
  .conv { background:#fff; border-radius:10px; padding:14px 16px; margin-bottom:10px; box-shadow:0 1px 3px rgba(0,0,0,.08); text-decoration:none; display:block; color:#222; }
  .conv:hover { box-shadow:0 2px 8px rgba(0,0,0,.12); }
  .tel { font-weight:600; }
  .preview { color:#555; font-size:14px; margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .meta { color:#999; font-size:12px; margin-top:4px; }
  .empty { color:#888; padding:40px; text-align:center; }
  a.back { color:#2563eb; text-decoration:none; font-size:14px; }
  .bubble { max-width:70%; padding:10px 14px; border-radius:14px; margin:6px 0; white-space:pre-wrap; word-wrap:break-word; }
  .user { background:#e5e7eb; margin-right:auto; }
  .assistant { background:#dcf8c6; margin-left:auto; text-align:left; }
  .row { display:flex; }
  .ts { font-size:11px; color:#999; margin-top:2px; }
</style>
"""


def _verificar_credenciales(credentials: HTTPBasicCredentials = Depends(security)):
    if not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Panel de admin no configurado: falta ADMIN_PASSWORD en las variables de entorno.",
        )
    usuario_ok = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    clave_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (usuario_ok and clave_ok):
        raise HTTPException(
            status_code=401,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/admin", response_class=HTMLResponse)
async def panel_admin(usuario: str = Depends(_verificar_credenciales)):
    """Lista todas las conversaciones, más reciente primero."""
    conversaciones = await listar_conversaciones()
    filas = ""
    for c in conversaciones:
        tel = html.escape(c["telefono"] or "(desconocido)")
        preview = html.escape((c["ultimo_mensaje"] or "")[:120])
        prefijo = "Tú: " if c["ultimo_role"] == "assistant" else ""
        fecha = c["ultima_fecha"].strftime("%d/%m/%Y %H:%M") if c["ultima_fecha"] else ""
        filas += f"""
        <a class="conv" href="/admin/chat/{tel}">
          <div class="tel">{tel}</div>
          <div class="preview">{prefijo}{preview}</div>
          <div class="meta">{fecha} · {c['total_mensajes']} mensajes</div>
        </a>
        """
    if not conversaciones:
        filas = '<div class="empty">Todavía no hay conversaciones.</div>'

    return f"""
    <html>
    <head><title>Conversaciones — Coosermul BN</title>{ESTILO}</head>
    <body>
      <h1>Conversaciones de WhatsApp</h1>
      <div class="sub">Coosermul BN · Soporte Coosermul</div>
      {filas}
    </body>
    </html>
    """


@router.get("/admin/chat/{telefono}", response_class=HTMLResponse)
async def panel_chat(telefono: str, usuario: str = Depends(_verificar_credenciales)):
    """Muestra el historial completo de una conversación."""
    historial = await obtener_historial_completo(telefono)
    burbujas = ""
    for msg in historial:
        clase = "assistant" if msg["role"] == "assistant" else "user"
        contenido = html.escape(msg["content"])
        ts = msg["timestamp"].strftime("%d/%m/%Y %H:%M") if msg.get("timestamp") else ""
        burbujas += f"""
        <div class="row">
          <div class="bubble {clase}">{contenido}<div class="ts">{ts}</div></div>
        </div>
        """
    if not historial:
        burbujas = '<div class="empty">Sin mensajes.</div>'

    tel_seguro = html.escape(telefono)
    return f"""
    <html>
    <head><title>Chat con {tel_seguro} — Coosermul BN</title>{ESTILO}</head>
    <body>
      <a class="back" href="/admin">&larr; Volver a conversaciones</a>
      <h1>{tel_seguro}</h1>
      {burbujas}
    </body>
    </html>
    """
