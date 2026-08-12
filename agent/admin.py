# agent/admin.py — Panel de administración simple (ver y responder conversaciones)
# Generado por AgentKit

"""
Panel web mínimo, protegido con usuario/contraseña, para que el equipo de
Coosermul BN pueda ver qué le están escribiendo los clientes, y tomar el
control de una conversación (responder directamente en el mismo chat de
WhatsApp del cliente) cuando el bot escala a un humano.
"""

import os
import html
import secrets
import logging
import tempfile
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from agent.memory import (
    listar_conversaciones,
    obtener_historial_completo,
    guardar_mensaje,
    activar_modo_humano,
    desactivar_modo_humano,
    esta_en_modo_humano,
    limpiar_historial,
)
from agent.providers import obtener_proveedor

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
  .conv { background:#fff; border-radius:10px; padding:14px 16px; margin-bottom:10px; box-shadow:0 1px 3px rgba(0,0,0,.08); text-decoration:none; display:block; color:#222; position:relative; }
  .conv:hover { box-shadow:0 2px 8px rgba(0,0,0,.12); }
  .tel { font-weight:600; }
  .preview { color:#555; font-size:14px; margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .meta { color:#999; font-size:12px; margin-top:4px; }
  .empty { color:#888; padding:40px; text-align:center; }
  a.back { color:#2563eb; text-decoration:none; font-size:14px; }
  .bubble { max-width:70%; padding:10px 14px; border-radius:14px; margin:6px 0; white-space:pre-wrap; word-wrap:break-word; }
  .user { background:#e5e7eb; margin-right:auto; }
  .assistant { background:#dcf8c6; margin-left:auto; text-align:left; }
  .humano { background:#bfdbfe; margin-left:auto; text-align:left; }
  .row { display:flex; }
  .ts { font-size:11px; color:#999; margin-top:2px; }
  .badge { display:inline-block; background:#f97316; color:#fff; font-size:11px; font-weight:600; padding:2px 8px; border-radius:999px; margin-left:8px; vertical-align:middle; }
  .toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; gap:10px; flex-wrap:wrap; }
  form.reply { display:flex; gap:8px; margin-top:20px; position:sticky; bottom:0; background:#f4f4f6; padding:10px 0; align-items:flex-end; flex-wrap:wrap; }
  form.reply textarea { flex:1; min-width:200px; border-radius:10px; border:1px solid #ddd; padding:10px; font-family:inherit; font-size:14px; resize:vertical; min-height:44px; }
  form.reply input[type=file] { font-size:12px; max-width:180px; }
  form.reply button { background:#16a34a; color:#fff; border:none; border-radius:10px; padding:0 18px; height:38px; font-size:14px; cursor:pointer; }
  .btn-liberar { background:#2563eb; color:#fff; border:none; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; text-decoration:none; }
  .btn-borrar { background:#dc2626; color:#fff; border:none; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; }
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
        badge = '<span class="badge">Necesita humano</span>' if c.get("modo_humano") else ""
        filas += f"""
        <a class="conv" href="/admin/chat/{tel}">
          <div class="tel">{tel}{badge}</div>
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
    """Muestra el historial completo de una conversación, con opción de responder."""
    historial = await obtener_historial_completo(telefono)
    en_modo_humano = await esta_en_modo_humano(telefono)

    burbujas = ""
    for msg in historial:
        clase = {"assistant": "assistant", "humano": "humano"}.get(msg["role"], "user")
        contenido = html.escape(msg["content"])
        ts = msg["timestamp"].strftime("%d/%m/%Y %H:%M") if msg.get("timestamp") else ""
        etiqueta = " (tú)" if msg["role"] == "humano" else ""
        burbujas += f"""
        <div class="row">
          <div class="bubble {clase}">{contenido}<div class="ts">{ts}{etiqueta}</div></div>
        </div>
        """
    if not historial:
        burbujas = '<div class="empty">Sin mensajes.</div>'

    tel_seguro = html.escape(telefono)
    badge = '<span class="badge">Necesita humano</span>' if en_modo_humano else ""
    boton_liberar = (
        f'<form method="post" action="/admin/chat/{tel_seguro}/liberar">'
        f'<button class="btn-liberar" type="submit">Devolver al bot</button></form>'
        if en_modo_humano else ""
    )
    boton_borrar = f"""
      <form method="post" action="/admin/chat/{tel_seguro}/borrar"
            onsubmit="return confirm('¿Borrar todo el historial de esta conversación? Esto no se puede deshacer.');">
        <button class="btn-borrar" type="submit">Borrar historial</button>
      </form>
    """

    return f"""
    <html>
    <head><title>Chat con {tel_seguro} — Coosermul BN</title>{ESTILO}</head>
    <body>
      <div class="toolbar">
        <a class="back" href="/admin">&larr; Volver a conversaciones</a>
        <div style="display:flex; gap:8px;">{boton_liberar}{boton_borrar}</div>
      </div>
      <h1>{tel_seguro}{badge}</h1>
      {burbujas}
      <form class="reply" method="post" action="/admin/chat/{tel_seguro}/responder" enctype="multipart/form-data">
        <textarea name="mensaje" placeholder="Escribe tu respuesta (opcional si adjuntas un archivo)..."></textarea>
        <input type="file" name="archivo" accept=".pdf,.jpg,.jpeg,.png">
        <button type="submit">Enviar</button>
      </form>
    </body>
    </html>
    """


MAX_ADJUNTO_BYTES = 20 * 1024 * 1024  # 20 MB, límite de WhatsApp para documentos


@router.post("/admin/chat/{telefono}/responder")
async def responder_chat(
    telefono: str,
    mensaje: str = Form(""),
    archivo: UploadFile | None = File(None),
    usuario: str = Depends(_verificar_credenciales),
):
    """El equipo humano envía un mensaje y/o un archivo real por WhatsApp, en el mismo chat."""
    mensaje = (mensaje or "").strip()
    proveedor = obtener_proveedor()
    algo_enviado = False

    if archivo is not None and archivo.filename:
        contenido = await archivo.read()
        if len(contenido) > MAX_ADJUNTO_BYTES:
            logger.error(f"Adjunto de {telefono} supera el límite de tamaño ({len(contenido)} bytes)")
        else:
            sufijo = os.path.splitext(archivo.filename)[1] or ""
            with tempfile.NamedTemporaryFile(delete=False, suffix=sufijo) as tmp:
                tmp.write(contenido)
                ruta_temp = tmp.name
            try:
                enviado = await proveedor.enviar_documento(
                    telefono, ruta_temp, archivo.filename, caption=mensaje
                )
            finally:
                try:
                    os.remove(ruta_temp)
                except OSError:
                    pass
            if enviado:
                registro = f"[archivo enviado: {archivo.filename}]"
                if mensaje:
                    registro += f" {mensaje}"
                await guardar_mensaje(telefono, "humano", registro)
                algo_enviado = True
            else:
                logger.error(f"No se pudo enviar el archivo {archivo.filename} a {telefono}")
    elif mensaje:
        enviado = await proveedor.enviar_mensaje(telefono, mensaje)
        if enviado:
            await guardar_mensaje(telefono, "humano", mensaje)
            algo_enviado = True
        else:
            logger.error(f"No se pudo enviar la respuesta manual a {telefono}")

    if algo_enviado:
        # Si un humano responde, la conversación queda en modo humano
        # (el bot no debe interrumpir mientras el equipo está atendiendo).
        await activar_modo_humano(telefono)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)


@router.post("/admin/chat/{telefono}/liberar")
async def liberar_chat(telefono: str, usuario: str = Depends(_verificar_credenciales)):
    """Devuelve la conversación al bot."""
    await desactivar_modo_humano(telefono)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)


@router.post("/admin/chat/{telefono}/borrar")
async def borrar_chat(telefono: str, usuario: str = Depends(_verificar_credenciales)):
    """Borra todo el historial de una conversación (para reiniciar pruebas, por ejemplo)."""
    await limpiar_historial(telefono)
    await desactivar_modo_humano(telefono)
    return RedirectResponse(url="/admin", status_code=303)
