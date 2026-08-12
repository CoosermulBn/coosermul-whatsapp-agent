# agent/admin.py — Panel de administración simple (ver y responder conversaciones)
# Generado por AgentKit

"""
Panel web mínimo, protegido con usuario/contraseña, para que el equipo de
Coosermul BN pueda ver qué le están escribiendo los clientes, y tomar el
control de una conversación (responder directamente en el mismo chat de
WhatsApp del cliente) cuando el bot escala a un humano.
"""

import os
import re
import html
import json
import secrets
import logging
import tempfile
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from agent.memory import (
    listar_conversaciones,
    obtener_historial_completo,
    guardar_mensaje,
    activar_modo_humano,
    desactivar_modo_humano,
    esta_en_modo_humano,
    limpiar_historial,
    obtener_adjunto,
    obtener_eventos_atencion,
)
from agent.providers import obtener_proveedor

# Los mensajes de adjuntos recibidos se guardan con una etiqueta al inicio,
# ej. "[[adjunto:12]] leyenda del usuario", para poder mostrar la imagen/
# archivo real en el panel sin tener que cambiar el esquema de Mensaje.
PATRON_ADJUNTO = re.compile(r"^\[\[adjunto:(\d+)\]\]\s*")

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
  .alerta { display:none; background:#dc2626; color:#fff; border-radius:10px; padding:14px 16px; margin-bottom:16px; font-weight:600; animation:pulso 1.2s infinite; }
  .alerta a { color:#fff; text-decoration:underline; }
  @keyframes pulso { 0%,100% { opacity:1; } 50% { opacity:.75; } }
  .btn-sonido { background:#111827; color:#fff; border:none; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; margin-bottom:16px; }
  .btn-sonido.activo { background:#16a34a; }
  .adjunto-img { max-width:260px; max-height:260px; border-radius:8px; display:block; }
  .feed-eventos { display:none; background:#fff; border-radius:10px; padding:12px 16px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  .feed-eventos h4 { margin:0 0 8px 0; font-size:13px; color:#666; }
  .feed-item { font-size:13px; padding:6px 0; border-top:1px solid #eee; }
  .feed-item:first-child { border-top:none; }
  .feed-item a { color:#2563eb; text-decoration:none; font-weight:600; }
  .feed-item .tipo { color:#888; }
</style>
"""

# JS para notificación visible + auditiva cuando hay una conversación
# esperando un humano (modo_humano). Sondea /admin/api/pendientes cada
# pocos segundos; el sonido se genera con Web Audio API (sin archivos
# externos) y solo se activa tras un click del usuario, por las políticas
# de autoplay de los navegadores.
SCRIPT_NOTIFICACIONES = """
<script>
(function () {
  var yaAvisados = new Set(JSON.parse(localStorage.getItem('coosermul_avisados') || '[]'));
  var audioCtx = null;
  var sonidoActivo = false;
  var tituloOriginal = document.title;
  var parpadeo = null;

  // Eventos que requieren atención inmediata: conversación nueva o adjunto
  // recibido. Se identifican por id de mensaje (no por teléfono), para no
  // perder avisos si el mismo número escribe varias veces.
  var guardadoEventoId = localStorage.getItem('coosermul_ultimo_evento_id');
  var ultimoEventoId = guardadoEventoId === null ? null : parseInt(guardadoEventoId, 10);
  var historialEventos = JSON.parse(localStorage.getItem('coosermul_historial_eventos') || '[]');

  function activarSonido(porClickDelUsuario) {
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      sonidoActivo = true;
      localStorage.setItem('coosermul_sonido_activado', '1');
      var btn = document.getElementById('btn-sonido');
      if (btn) { btn.textContent = '🔔 Notificaciones activadas'; btn.classList.add('activo'); }
      if (porClickDelUsuario) pitar(); // sonido de confirmacion solo si fue un click real
    } catch (e) {
      // el navegador bloqueo la creacion automatica sin gesto del usuario;
      // el boton se queda visible para que lo activen con un click
    }
  }

  function pitar() {
    if (!audioCtx) return;
    var t = audioCtx.currentTime;
    [0, 0.28].forEach(function (delay) {
      var osc = audioCtx.createOscillator();
      var gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, t + delay);
      gain.gain.setValueAtTime(0.0001, t + delay);
      gain.gain.exponentialRampToValueAtTime(0.3, t + delay + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + delay + 0.25);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t + delay);
      osc.stop(t + delay + 0.3);
    });
  }

  function parpadearTitulo(activar) {
    if (activar && !parpadeo) {
      var mostrar = false;
      parpadeo = setInterval(function () {
        document.title = mostrar ? tituloOriginal : '🔴 Nueva solicitud';
        mostrar = !mostrar;
      }, 1000);
    } else if (!activar && parpadeo) {
      clearInterval(parpadeo);
      parpadeo = null;
      document.title = tituloOriginal;
    }
  }

  function etiquetaTipo(tipo) {
    if (tipo === 'nueva_conversacion') return '🆕 Nueva conversación';
    if (tipo === 'adjunto') return '📎 Envió un archivo';
    if (tipo === 'nueva_conversacion_adjunto') return '🆕📎 Nueva conversación con archivo';
    return 'Actividad';
  }

  function pintarFeed() {
    var caja = document.getElementById('feed-eventos');
    var lista = document.getElementById('feed-eventos-lista');
    if (!caja || !lista) return;
    if (historialEventos.length === 0) { caja.style.display = 'none'; return; }
    caja.style.display = 'block';
    lista.innerHTML = historialEventos.map(function (ev) {
      return '<div class="feed-item"><span class="tipo">' + etiquetaTipo(ev.tipo) + '</span> — ' +
        '<a href="/admin/chat/' + ev.telefono + '">' + ev.telefono + '</a></div>';
    }).join('');
  }

  function revisarEventos() {
    var url = '/admin/api/eventos?desde_id=' + (ultimoEventoId === null ? 0 : ultimoEventoId);
    fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      var eventos = data.eventos || [];
      var esPrimeraCarga = (ultimoEventoId === null);
      var maxId = ultimoEventoId === null ? 0 : ultimoEventoId;

      eventos.forEach(function (ev) {
        if (ev.id > maxId) maxId = ev.id;
        historialEventos.unshift(ev);
      });
      if (historialEventos.length > 8) historialEventos = historialEventos.slice(0, 8);
      localStorage.setItem('coosermul_historial_eventos', JSON.stringify(historialEventos));
      pintarFeed();

      // En la primera carga de la página no avisamos (evita un alud de
      // sonidos/notificaciones por historial viejo); desde ahí en adelante
      // sí, apenas aparezca algo nuevo.
      if (!esPrimeraCarga && eventos.length > 0 && sonidoActivo) {
        pitar();
        if (window.Notification && Notification.permission === 'granted') {
          eventos.forEach(function (ev) {
            new Notification('Coosermul BN — ' + etiquetaTipo(ev.tipo), { body: ev.telefono });
          });
        }
      }

      ultimoEventoId = maxId;
      localStorage.setItem('coosermul_ultimo_evento_id', String(maxId));
    }).catch(function () {});
  }

  function revisarPendientes() {
    fetch('/admin/api/pendientes').then(function (r) { return r.json(); }).then(function (data) {
      var pendientes = data.telefonos || [];
      var nuevos = pendientes.filter(function (t) { return !yaAvisados.has(t); });

      var banner = document.getElementById('alerta-pendientes');
      if (pendientes.length > 0) {
        banner.style.display = 'block';
        banner.innerHTML = '🔔 ' + pendientes.length + ' conversación(es) esperando un asesor: ' +
          pendientes.map(function (t) { return '<a href="/admin/chat/' + t + '">' + t + '</a>'; }).join(', ');
        parpadearTitulo(true);
      } else {
        banner.style.display = 'none';
        parpadearTitulo(false);
      }

      if (nuevos.length > 0 && sonidoActivo) {
        pitar();
        if (window.Notification && Notification.permission === 'granted') {
          new Notification('Coosermul BN — Nueva solicitud', {
            body: nuevos.join(', ') + ' necesita un asesor.',
          });
        }
      }
      pendientes.forEach(function (t) { yaAvisados.add(t); });
      // limpiar los que ya no estan pendientes, para que si vuelven a
      // escalar mas adelante, se vuelva a avisar
      yaAvisados = new Set(pendientes);
      localStorage.setItem('coosermul_avisados', JSON.stringify(Array.from(yaAvisados)));
    }).catch(function () {});
  }

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('btn-sonido');
    if (btn) btn.addEventListener('click', function () { activarSonido(true); });
    if (window.Notification && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    // Si el usuario ya activo el sonido antes en este navegador, lo
    // reactivamos solos al cargar la pagina (sin pedirle otro click).
    if (localStorage.getItem('coosermul_sonido_activado') === '1') {
      activarSonido(false);
    }
    pintarFeed();
    revisarPendientes();
    revisarEventos();
    setInterval(function () { revisarPendientes(); revisarEventos(); }, 8000);
  });
})();
</script>
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
        ultimo_mensaje = c["ultimo_mensaje"] or ""
        if PATRON_ADJUNTO.match(ultimo_mensaje):
            ultimo_mensaje = ("📎 " + PATRON_ADJUNTO.sub("", ultimo_mensaje)).strip()
            if ultimo_mensaje == "📎":
                ultimo_mensaje = "📎 Archivo adjunto"
        preview = html.escape(ultimo_mensaje[:120])
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
      <button id="btn-sonido" class="btn-sonido">🔕 Activar notificaciones (sonido)</button>
      <div id="alerta-pendientes" class="alerta"></div>
      <div id="feed-eventos" class="feed-eventos"><h4>Actividad reciente</h4><div id="feed-eventos-lista"></div></div>
      {filas}
      {SCRIPT_NOTIFICACIONES}
    </body>
    </html>
    """


@router.get("/admin/media/{adjunto_id}")
async def ver_adjunto(adjunto_id: int, usuario: str = Depends(_verificar_credenciales)):
    """Sirve el archivo real (imagen/documento) que envió un socio por WhatsApp."""
    adjunto = await obtener_adjunto(adjunto_id)
    if not adjunto:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    nombre = adjunto["nombre_archivo"] or f"adjunto_{adjunto_id}"
    return Response(
        content=adjunto["contenido"],
        media_type=adjunto["mime_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )


@router.get("/admin/api/pendientes")
async def api_pendientes(usuario: str = Depends(_verificar_credenciales)):
    """Lista los teléfonos que están esperando un asesor humano (modo_humano=True)."""
    conversaciones = await listar_conversaciones()
    telefonos = [c["telefono"] for c in conversaciones if c.get("modo_humano")]
    return JSONResponse({"telefonos": telefonos})


@router.get("/admin/api/eventos")
async def api_eventos(desde_id: int = 0, usuario: str = Depends(_verificar_credenciales)):
    """
    Eventos que requieren atención inmediata: conversaciones nuevas y
    adjuntos (imágenes/documentos) recibidos, con id > desde_id.
    """
    eventos = await obtener_eventos_atencion(desde_id=desde_id)
    return JSONResponse({
        "eventos": [
            {
                "id": e["id"],
                "telefono": e["telefono"],
                "tipo": e["tipo"],
                "timestamp": e["timestamp"].isoformat() if e.get("timestamp") else None,
            }
            for e in eventos
        ]
    })


@router.get("/admin/chat/{telefono}", response_class=HTMLResponse)
async def panel_chat(telefono: str, usuario: str = Depends(_verificar_credenciales)):
    """Muestra el historial completo de una conversación, con opción de responder."""
    historial = await obtener_historial_completo(telefono)
    en_modo_humano = await esta_en_modo_humano(telefono)

    burbujas = ""
    for msg in historial:
        clase = {"assistant": "assistant", "humano": "humano"}.get(msg["role"], "user")
        ts = msg["timestamp"].strftime("%d/%m/%Y %H:%M") if msg.get("timestamp") else ""
        etiqueta = " (tú)" if msg["role"] == "humano" else ""

        match = PATRON_ADJUNTO.match(msg["content"])
        if match:
            adjunto_id = match.group(1)
            texto_restante = html.escape(msg["content"][match.end():])
            adjunto_html = (
                f'<a href="/admin/media/{adjunto_id}" target="_blank">'
                f'<img src="/admin/media/{adjunto_id}" class="adjunto-img" '
                f'onerror="this.outerHTML=\'📎 <a href=&quot;/admin/media/{adjunto_id}&quot; target=&quot;_blank&quot;>Ver archivo adjunto</a>\'"></a>'
            )
            contenido = adjunto_html + (f"<div>{texto_restante}</div>" if texto_restante else "")
        else:
            contenido = html.escape(msg["content"])

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
      <button id="btn-sonido" class="btn-sonido">🔕 Activar notificaciones (sonido)</button>
      <div id="alerta-pendientes" class="alerta"></div>
      <div id="feed-eventos" class="feed-eventos"><h4>Actividad reciente</h4><div id="feed-eventos-lista"></div></div>
      <h1>{tel_seguro}{badge}</h1>
      {burbujas}
      <form class="reply" method="post" action="/admin/chat/{tel_seguro}/responder" enctype="multipart/form-data">
        <textarea name="mensaje" placeholder="Escribe tu respuesta (opcional si adjuntas un archivo)..."></textarea>
        <input type="file" name="archivo" accept=".pdf,.jpg,.jpeg,.png">
        <button type="submit">Enviar</button>
      </form>
      {SCRIPT_NOTIFICACIONES}
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
