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
import asyncio
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
from agent.tools import (
    resolver_paquete_credito,
    resolver_paquete_inscripcion,
    resolver_cuentas_abono,
    resolver_info_institucional,
    ruta_completa,
    buscar_socios,
    identificar_socio_por_telefono,
)

# Los mensajes de adjuntos recibidos se guardan con una etiqueta al inicio,
# ej. "[[adjunto:12]] leyenda del usuario", para poder mostrar la imagen/
# archivo real en el panel sin tener que cambiar el esquema de Mensaje.
PATRON_ADJUNTO = re.compile(r"^\[\[adjunto:(\d+)\]\]\s*")

# Plantillas de mensaje aprobadas por Meta para iniciar una conversación
# (obligatorias fuera de la ventana de 24h o con alguien que nunca escribió).
# El nombre y el idioma deben coincidir exactamente con la plantilla creada
# en el WhatsApp Manager de Meta.
PLANTILLAS_DISPONIBLES = {
    "recordatorio_pago": {
        "etiqueta": "Recordatorio de pago",
        # Meta la registró con el código de idioma "en" (aunque el texto
        # aprobado está en español) — debe coincidir exacto o el envío falla.
        "idioma": "en",
        "variables": ["Nombre del socio", "Monto (S/)", "Fecha de vencimiento"],
        "vista_previa": (
            "Hola {{1}}, te recordamos que tienes una cuota pendiente de S/ {{2}} "
            "con vencimiento el {{3}}. Si ya realizaste el pago, puedes ignorar este "
            "mensaje. Cualquier consulta, escríbenos por este medio. — Coosermul BN"
        ),
    },
    "tramite_aprobado": {
        "etiqueta": "Trámite / crédito aprobado",
        "idioma": "es_PE",
        "variables": ["Nombre del socio", "Trámite (ej. solicitud de crédito)"],
        "vista_previa": (
            "Hola {{1}}, te informamos que tu {{2}} ha sido aprobado(a). Nuestro "
            "equipo se pondrá en contacto contigo para los siguientes pasos. "
            "Cualquier consulta, escríbenos por este medio. — Coosermul BN"
        ),
    },
    "autorizacion_info_coosermul": {
        "etiqueta": "Autorización de info (no socios BN)",
        "idioma": "es_PE",
        "variables": ["Nombre del trabajador"],
        "vista_previa": (
            "Hola {{1}}, te escribimos de Coosermul BN, la Cooperativa de "
            "Servicios Múltiples de los Trabajadores del Banco de la Nación. "
            "Nos gustaría compartirte información sobre los beneficios de "
            "asociarte (créditos, bazar, previsión social y más). Si te "
            "interesa recibir esta información, respóndenos SÍ."
        ),
    },
}

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
  .nombre-socio { font-weight:600; }
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
  .btn-nueva { background:#7c3aed; color:#fff; border:none; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; text-decoration:none; display:inline-block; }
  .form-nueva { background:#fff; border-radius:10px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,.08); max-width:480px; }
  .form-nueva label { display:block; margin-bottom:14px; font-size:13px; color:#444; font-weight:600; }
  .form-nueva input, .form-nueva select { width:100%; margin-top:6px; padding:9px 10px; border-radius:8px; border:1px solid #ddd; font-size:14px; box-sizing:border-box; font-weight:normal; }
  .form-nueva button { background:#16a34a; color:#fff; border:none; border-radius:8px; padding:10px 20px; font-size:14px; cursor:pointer; }
  .vista-previa { background:#f4f4f6; border-radius:8px; padding:10px 12px; font-size:13px; color:#555; font-style:italic; margin-bottom:10px; }
  .alerta-info { background:#eff6ff; color:#1e3a8a; border-radius:10px; padding:12px 16px; margin-bottom:16px; font-size:13px; }
  .buscar-socio-wrap { position:relative; }
  .resultados-busqueda { display:none; position:absolute; z-index:10; left:0; right:0; top:100%; background:#fff; border:1px solid #ddd; border-radius:8px; margin-top:4px; max-height:220px; overflow-y:auto; box-shadow:0 4px 12px rgba(0,0,0,.12); }
  .resultado-item { padding:8px 12px; font-size:13px; font-weight:normal; cursor:pointer; border-bottom:1px solid #eee; }
  .resultado-item:last-child { border-bottom:none; }
  .resultado-item:hover { background:#f4f4f6; }
  .resultado-item .tel { color:#888; }
  .caja-paquetes { background:#fff; border-radius:10px; padding:14px 16px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  .caja-paquetes h4 { margin:0 0 4px 0; font-size:13px; color:#666; }
  .caja-paquetes .sub { margin:0 0 12px 0; }
  .form-paquete { display:flex; gap:8px; align-items:center; margin-top:8px; flex-wrap:wrap; }
  .form-paquete select { padding:8px 10px; border-radius:8px; border:1px solid #ddd; font-size:13px; }
  .btn-paquete { background:#7c3aed; color:#fff; border:none; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; }
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
        socio = identificar_socio_por_telefono(c["telefono"] or "")
        nombre_html = f'<span class="nombre-socio">{html.escape(socio["nombre"])}</span> · ' if socio else ""
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
          <div class="tel">{nombre_html}{tel}{badge}</div>
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
      <div class="toolbar">
        <div>
          <h1>Conversaciones de WhatsApp</h1>
          <div class="sub">Coosermul BN · Soporte Coosermul</div>
        </div>
        <div style="display:flex; gap:8px;">
          <a class="btn-nueva" href="/admin/nueva">+ Nueva conversación</a>
          <a class="btn-nueva" href="/admin/nueva/masivo">+ Envío masivo</a>
        </div>
      </div>
      <button id="btn-sonido" class="btn-sonido">🔕 Activar notificaciones (sonido)</button>
      <div id="alerta-pendientes" class="alerta"></div>
      <div id="feed-eventos" class="feed-eventos"><h4>Actividad reciente</h4><div id="feed-eventos-lista"></div></div>
      {filas}
      {SCRIPT_NOTIFICACIONES}
    </body>
    </html>
    """


@router.get("/admin/api/buscar_socio")
async def api_buscar_socio(q: str = "", usuario: str = Depends(_verificar_credenciales)):
    """Busca socios del padrón por nombre/DNI (con celular registrado), para /admin/nueva."""
    resultados = buscar_socios(q)
    return JSONResponse({"socios": resultados})


@router.get("/admin/nueva", response_class=HTMLResponse)
async def nueva_conversacion_form(error: str = "", usuario: str = Depends(_verificar_credenciales)):
    """
    Formulario para que el equipo inicie una conversación con alguien que
    nunca escribió (o pasaron más de 24h desde su último mensaje). WhatsApp
    solo permite esto usando una plantilla previamente aprobada por Meta.
    """
    mensaje_error = ""
    if error == "datos_invalidos":
        mensaje_error = '<div class="alerta" style="display:block;">Completa el número y elige una plantilla.</div>'
    elif error == "envio_fallido":
        mensaje_error = (
            '<div class="alerta" style="display:block;">No se pudo enviar. Verifica que la '
            "plantilla ya esté aprobada por Meta y que el número tenga el código de país.</div>"
        )

    bloques_plantilla = ""
    for nombre, info in PLANTILLAS_DISPONIBLES.items():
        campos = ""
        for var in info["variables"]:
            campos += f'<label>{html.escape(var)}<input type="text" name="variables" disabled></label>'
        bloques_plantilla += f"""
        <div class="bloque-plantilla" data-plantilla="{nombre}" style="display:none;">
          <div class="vista-previa">{html.escape(info['vista_previa'])}</div>
          {campos}
        </div>
        """

    opciones = "".join(
        f'<option value="{nombre}">{html.escape(info["etiqueta"])}</option>'
        for nombre, info in PLANTILLAS_DISPONIBLES.items()
    )

    return f"""
    <html>
    <head><title>Nueva conversación — Coosermul BN</title>{ESTILO}</head>
    <body>
      <a class="back" href="/admin">&larr; Volver a conversaciones</a>
      <h1>Iniciar conversación nueva</h1>
      <div class="alerta-info">
        WhatsApp solo permite que el negocio escriba primero usando una plantilla
        aprobada por Meta. Si la persona ya te escribió antes (dentro de las
        últimas 24h), no necesitas esto: respóndele directo desde su chat.
      </div>
      {mensaje_error}
      <form method="post" action="/admin/nueva" class="form-nueva">
        <label class="buscar-socio-wrap">Buscar socio del padrón (nombre o DNI)
          <input type="text" id="buscar-socio" placeholder="Escribe al menos 3 letras..." autocomplete="off">
          <div id="resultados-busqueda" class="resultados-busqueda"></div>
        </label>
        <label>Número de WhatsApp (con código de país, sin +, ej. 51987654321)
          <input type="text" name="telefono" id="input-telefono" required pattern="[0-9]+" placeholder="51987654321">
        </label>
        <label>Plantilla
          <select name="plantilla" id="select-plantilla" required>
            <option value="">-- Selecciona --</option>
            {opciones}
          </select>
        </label>
        {bloques_plantilla}
        <button type="submit">Enviar</button>
      </form>
      <script>
        var select = document.getElementById('select-plantilla');
        var bloques = document.querySelectorAll('.bloque-plantilla');
        select.addEventListener('change', function () {{
          bloques.forEach(function (b) {{
            var activo = b.getAttribute('data-plantilla') === select.value;
            b.style.display = activo ? 'block' : 'none';
            b.querySelectorAll('input').forEach(function (inp) {{
              inp.disabled = !activo;
              inp.required = activo;
            }});
          }});
        }});

        var inputBuscar = document.getElementById('buscar-socio');
        var divResultados = document.getElementById('resultados-busqueda');
        var inputTelefono = document.getElementById('input-telefono');
        var temporizador = null;

        inputBuscar.addEventListener('input', function () {{
          clearTimeout(temporizador);
          var q = inputBuscar.value.trim();
          if (q.length < 3) {{ divResultados.style.display = 'none'; divResultados.innerHTML = ''; return; }}
          temporizador = setTimeout(function () {{
            fetch('/admin/api/buscar_socio?q=' + encodeURIComponent(q)).then(function (r) {{ return r.json(); }}).then(function (data) {{
              var socios = data.socios || [];
              if (socios.length === 0) {{
                divResultados.innerHTML = '<div class="resultado-item">Sin resultados</div>';
                divResultados.style.display = 'block';
                return;
              }}
              divResultados.innerHTML = socios.map(function (s) {{
                return '<div class="resultado-item" data-nombre="' + s.nombre.replace(/"/g, '&quot;') + '" data-celular="' + s.celular + '">' +
                  '<strong>' + s.nombre + '</strong><br><span class="tel">' + s.celular + ' &middot; código ' + s.codigo + '</span></div>';
              }}).join('');
              divResultados.style.display = 'block';
            }}).catch(function () {{}});
          }}, 300);
        }});

        divResultados.addEventListener('mousedown', function (e) {{
          var item = e.target.closest('.resultado-item');
          if (!item || !item.hasAttribute('data-celular')) return;
          var nombre = item.getAttribute('data-nombre');
          var celular = item.getAttribute('data-celular');
          inputTelefono.value = celular;
          inputBuscar.value = nombre;
          divResultados.style.display = 'none';
          var bloqueActivo = null;
          bloques.forEach(function (b) {{ if (b.style.display === 'block') bloqueActivo = b; }});
          if (bloqueActivo) {{
            var primerInput = bloqueActivo.querySelector('input');
            if (primerInput) primerInput.value = nombre;
          }}
        }});

        document.addEventListener('click', function (e) {{
          if (e.target !== inputBuscar) divResultados.style.display = 'none';
        }});
      </script>
    </body>
    </html>
    """


@router.post("/admin/nueva")
async def nueva_conversacion_enviar(
    telefono: str = Form(...),
    plantilla: str = Form(...),
    variables: list[str] = Form([]),
    usuario: str = Depends(_verificar_credenciales),
):
    """Envía la plantilla elegida para iniciar la conversación con ese número."""
    telefono = telefono.strip()
    info = PLANTILLAS_DISPONIBLES.get(plantilla)
    if not info or not telefono:
        return RedirectResponse(url="/admin/nueva?error=datos_invalidos", status_code=303)

    proveedor = obtener_proveedor()
    enviado = await proveedor.enviar_plantilla(telefono, plantilla, info["idioma"], variables)

    if not enviado:
        logger.error(f"No se pudo enviar la plantilla {plantilla} a {telefono}")
        return RedirectResponse(url="/admin/nueva?error=envio_fallido", status_code=303)

    registro = f"[plantilla enviada: {info['etiqueta']}] " + " | ".join(variables)
    await guardar_mensaje(telefono, "humano", registro)
    await activar_modo_humano(telefono)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)


MAX_ENVIOS_MASIVOS = 200
PAUSA_ENTRE_ENVIOS_MASIVOS = 0.4  # segundos, para no chocar con limites de Meta


@router.get("/admin/nueva/masivo", response_class=HTMLResponse)
async def nueva_masiva_form(usuario: str = Depends(_verificar_credenciales)):
    """Formulario para enviar la misma plantilla a una lista de números."""
    opciones = "".join(
        f'<option value="{nombre}">{html.escape(info["etiqueta"])}</option>'
        for nombre, info in PLANTILLAS_DISPONIBLES.items()
    )
    bloques_ayuda = ""
    for nombre, info in PLANTILLAS_DISPONIBLES.items():
        formato = "telefono" + "".join(f",{v}" for v in info["variables"])
        bloques_ayuda += f"""
        <div class="bloque-plantilla" data-plantilla="{nombre}" style="display:none;">
          <div class="vista-previa">
            Formato por línea: <code>{html.escape(formato)}</code><br>
            Ej: <code>51987654321,{", ".join(v.split(" (")[0] for v in info["variables"])}</code>
          </div>
        </div>
        """

    return f"""
    <html>
    <head><title>Envío masivo — Coosermul BN</title>{ESTILO}</head>
    <body>
      <a class="back" href="/admin">&larr; Volver a conversaciones</a>
      <h1>Enviar plantilla a varios números</h1>
      <div class="alerta-info">
        Se envía la misma plantilla a cada número de la lista, uno por
        uno con una pequeña pausa entre cada envío para no chocar con
        los límites de Meta. Máximo {MAX_ENVIOS_MASIVOS} números por
        tanda — si tienes más, envíalos en varias tandas.
      </div>
      <form method="post" action="/admin/nueva/masivo" class="form-nueva">
        <label>Plantilla
          <select name="plantilla" id="select-plantilla-masivo" required>
            <option value="">-- Selecciona --</option>
            {opciones}
          </select>
        </label>
        {bloques_ayuda}
        <label>Números y variables (uno por línea, separados por coma)
          <textarea name="lista" required rows="10" placeholder="51987654321,Juan Pérez&#10;51912345678,María López"
            style="width:100%; font-family:monospace; font-size:13px; padding:10px; border-radius:8px; border:1px solid #ddd; box-sizing:border-box; margin-top:6px;"></textarea>
        </label>
        <button type="submit">Enviar a todos</button>
      </form>
      <script>
        var select = document.getElementById('select-plantilla-masivo');
        var bloques = document.querySelectorAll('.bloque-plantilla');
        select.addEventListener('change', function () {{
          bloques.forEach(function (b) {{
            b.style.display = b.getAttribute('data-plantilla') === select.value ? 'block' : 'none';
          }});
        }});
      </script>
    </body>
    </html>
    """


@router.post("/admin/nueva/masivo", response_class=HTMLResponse)
async def nueva_masiva_enviar(
    plantilla: str = Form(...),
    lista: str = Form(...),
    usuario: str = Depends(_verificar_credenciales),
):
    """Envía la plantilla elegida a cada número de la lista, uno por uno."""
    info = PLANTILLAS_DISPONIBLES.get(plantilla)
    if not info:
        return RedirectResponse(url="/admin/nueva/masivo", status_code=303)

    proveedor = obtener_proveedor()
    lineas = [l.strip() for l in lista.splitlines() if l.strip()][:MAX_ENVIOS_MASIVOS]

    resultados = []
    for linea in lineas:
        partes = [p.strip() for p in linea.split(",")]
        telefono = re.sub(r"\D", "", partes[0]) if partes else ""
        variables = partes[1:]
        if not telefono:
            resultados.append({"telefono": linea, "ok": False, "detalle": "número inválido"})
            continue

        enviado = await proveedor.enviar_plantilla(telefono, plantilla, info["idioma"], variables)
        if enviado:
            registro = f"[plantilla enviada: {info['etiqueta']}] " + " | ".join(variables)
            await guardar_mensaje(telefono, "humano", registro)
            await activar_modo_humano(telefono)
            resultados.append({"telefono": telefono, "ok": True, "detalle": ""})
        else:
            logger.error(f"Envio masivo: no se pudo enviar {plantilla} a {telefono}")
            resultados.append({"telefono": telefono, "ok": False, "detalle": "no se pudo enviar (ver logs)"})

        await asyncio.sleep(PAUSA_ENTRE_ENVIOS_MASIVOS)

    exitosos = sum(1 for r in resultados if r["ok"])
    fallidos = len(resultados) - exitosos
    filas = "".join(
        f'<div class="feed-item">{"✅" if r["ok"] else "❌"} {html.escape(r["telefono"])} '
        f'{html.escape(r["detalle"])}</div>'
        for r in resultados
    )

    return f"""
    <html>
    <head><title>Resultado envío masivo — Coosermul BN</title>{ESTILO}</head>
    <body>
      <a class="back" href="/admin">&larr; Volver a conversaciones</a>
      <h1>Resultado del envío masivo</h1>
      <div class="alerta-info">
        {exitosos} enviados correctamente, {fallidos} fallidos, de {len(resultados)} en total.
      </div>
      <div class="feed-eventos" style="display:block;">{filas}</div>
      <a class="btn-nueva" href="/admin/nueva/masivo" style="margin-top:16px; display:inline-block;">Enviar otra tanda</a>
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
    socio = identificar_socio_por_telefono(telefono)
    titulo_chat = f"{html.escape(socio['nombre'])} ({tel_seguro})" if socio else tel_seguro
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
    <head><title>Chat con {titulo_chat} — Coosermul BN</title>{ESTILO}</head>
    <body>
      <div class="toolbar">
        <a class="back" href="/admin">&larr; Volver a conversaciones</a>
        <div style="display:flex; gap:8px;">{boton_liberar}{boton_borrar}</div>
      </div>
      <button id="btn-sonido" class="btn-sonido">🔕 Activar notificaciones (sonido)</button>
      <div id="alerta-pendientes" class="alerta"></div>
      <div id="feed-eventos" class="feed-eventos"><h4>Actividad reciente</h4><div id="feed-eventos-lista"></div></div>
      <h1>{titulo_chat}{badge}</h1>
      {burbujas}
      <div class="caja-paquetes">
        <h4>Enviar documentos (tras evaluar boleta de pago)</h4>
        <p class="sub" style="margin:0 0 8px 0;">Revisa la boleta adjunta arriba y envía el paquete correspondiente.</p>
        <form class="form-paquete" method="post" action="/admin/chat/{tel_seguro}/enviar_credito"
              onsubmit="return confirm('¿Enviar los 4 documentos de crédito (Solicitud, Pagaré, Contrato, Declaración Jurada)?');">
          <button class="btn-paquete" type="submit">📎 Enviar paquete de crédito</button>
        </form>
        <form class="form-paquete" method="post" action="/admin/chat/{tel_seguro}/enviar_inscripcion"
              onsubmit="return confirm('¿Enviar los documentos de inscripción para el perfil elegido?');">
          <select name="perfil" required>
            <option value="">Perfil del socio...</option>
            <option value="activo">Activo</option>
            <option value="pensionista">Pensionista</option>
            <option value="cesante">Cesante</option>
            <option value="feban">FEBAN</option>
            <option value="tercero">Tercero</option>
          </select>
          <button class="btn-paquete" type="submit">📎 Enviar paquete de inscripción</button>
        </form>
        <form class="form-paquete" method="post" action="/admin/chat/{tel_seguro}/enviar_cuentas_abono"
              onsubmit="return confirm('¿Enviar el PDF de cuentas de abono para pagos?');">
          <button class="btn-paquete" type="submit">📎 Enviar cuentas de abono</button>
        </form>
        <form class="form-paquete" method="post" action="/admin/chat/{tel_seguro}/enviar_info_institucional"
              onsubmit="return confirm('¿Enviar el paquete de información (carta, tríptico y catálogo)?');">
          <button class="btn-paquete" type="submit">📎 Enviar paquete de información</button>
        </form>
      </div>
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


@router.post("/admin/chat/{telefono}/enviar_credito")
async def enviar_paquete_credito_manual(telefono: str, usuario: str = Depends(_verificar_credenciales)):
    """El equipo envía manualmente el paquete de crédito (Solicitud, Pagaré, Contrato), tras evaluar la boleta."""
    proveedor = obtener_proveedor()
    archivos = resolver_paquete_credito()
    enviados = []
    for nombre_archivo in archivos:
        ok = await proveedor.enviar_documento(telefono, ruta_completa(nombre_archivo), nombre_archivo)
        if ok:
            enviados.append(nombre_archivo)
        else:
            logger.error(f"No se pudo enviar {nombre_archivo} a {telefono} (paquete de crédito manual)")

    if enviados:
        registro = "[paquete de crédito enviado] " + ", ".join(enviados)
        await guardar_mensaje(telefono, "humano", registro)
        await activar_modo_humano(telefono)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)


@router.post("/admin/chat/{telefono}/enviar_inscripcion")
async def enviar_paquete_inscripcion_manual(
    telefono: str,
    perfil: str = Form(...),
    usuario: str = Depends(_verificar_credenciales),
):
    """El equipo envía manualmente el paquete de inscripción según el perfil, tras evaluar la boleta."""
    proveedor = obtener_proveedor()
    archivos = resolver_paquete_inscripcion(perfil)
    if not archivos:
        logger.error(f"Perfil desconocido '{perfil}' al enviar paquete de inscripción a {telefono}")
        return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)

    enviados = []
    for nombre_archivo in archivos:
        ok = await proveedor.enviar_documento(telefono, ruta_completa(nombre_archivo), nombre_archivo)
        if ok:
            enviados.append(nombre_archivo)
        else:
            logger.error(f"No se pudo enviar {nombre_archivo} a {telefono} (paquete de inscripción manual)")

    if enviados:
        registro = f"[paquete de inscripción enviado, perfil {perfil}] " + ", ".join(enviados)
        await guardar_mensaje(telefono, "humano", registro)
        await activar_modo_humano(telefono)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)


@router.post("/admin/chat/{telefono}/enviar_cuentas_abono")
async def enviar_cuentas_abono_manual(telefono: str, usuario: str = Depends(_verificar_credenciales)):
    """El equipo envía manualmente el PDF con los datos de las cuentas de abono para pagos."""
    proveedor = obtener_proveedor()
    archivos = resolver_cuentas_abono()
    enviados = []
    for nombre_archivo in archivos:
        ok = await proveedor.enviar_documento(telefono, ruta_completa(nombre_archivo), nombre_archivo)
        if ok:
            enviados.append(nombre_archivo)
        else:
            logger.error(f"No se pudo enviar {nombre_archivo} a {telefono} (cuentas de abono manual)")

    if enviados:
        registro = "[cuentas de abono enviadas] " + ", ".join(enviados)
        await guardar_mensaje(telefono, "humano", registro)
        await activar_modo_humano(telefono)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)


@router.post("/admin/chat/{telefono}/enviar_info_institucional")
async def enviar_info_institucional_manual(telefono: str, usuario: str = Depends(_verificar_credenciales)):
    """El equipo envía manualmente el paquete de información institucional (carta, tríptico, catálogo)."""
    proveedor = obtener_proveedor()
    archivos = resolver_info_institucional()
    enviados = []
    for nombre_archivo in archivos:
        ok = await proveedor.enviar_documento(telefono, ruta_completa(nombre_archivo), nombre_archivo)
        if ok:
            enviados.append(nombre_archivo)
        else:
            logger.error(f"No se pudo enviar {nombre_archivo} a {telefono} (info institucional manual)")

    if enviados:
        registro = "[paquete de información enviado] " + ", ".join(enviados)
        await guardar_mensaje(telefono, "humano", registro)
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
