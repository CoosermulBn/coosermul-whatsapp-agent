# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria del agente. Guarda el historial de conversaciones
por número de teléfono usando SQLite (local) o PostgreSQL (producción).
"""

import os
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, Boolean, LargeBinary, select, Integer, func
from dotenv import load_dotenv

load_dotenv()

# Configuración de base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentkit.db")

# Si es PostgreSQL en producción, ajustar el esquema de URL
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    """Modelo de mensaje en la base de datos."""
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" o "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EstadoConversacion(Base):
    """
    Marca si una conversación está en modo humano (el bot deja de
    responder automáticamente hasta que un miembro del equipo la libere
    desde el panel /admin).
    """
    __tablename__ = "estado_conversacion"

    telefono: Mapped[str] = mapped_column(String(50), primary_key=True)
    modo_humano: Mapped[bool] = mapped_column(Boolean, default=False)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Adjunto(Base):
    """Archivo (imagen/documento) recibido de un socio por WhatsApp — ej. comprobantes de pago."""
    __tablename__ = "adjuntos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    nombre_archivo: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    contenido: Mapped[bytes] = mapped_column(LargeBinary)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def inicializar_db():
    """Crea las tablas si no existen."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def guardar_mensaje(telefono: str, role: str, content: str):
    """Guarda un mensaje en el historial de conversación."""
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            timestamp=datetime.utcnow()
        )
        session.add(mensaje)
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    """
    Recupera los últimos N mensajes de una conversación.

    Args:
        telefono: Número de teléfono del cliente
        limite: Máximo de mensajes a recuperar (default: 20)

    Returns:
        Lista de diccionarios con role y content
    """
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
        result = await session.execute(query)
        mensajes = result.scalars().all()

        # Invertir para orden cronológico (los más recientes están primero)
        mensajes.reverse()

        return [
            {"role": msg.role, "content": msg.content}
            for msg in mensajes
        ]


async def listar_conversaciones() -> list[dict]:
    """
    Lista todos los números que han escrito, con su último mensaje y fecha,
    ordenados del más reciente al más antiguo. Para el panel de admin.
    """
    async with async_session() as session:
        # último mensaje por teléfono
        subq = (
            select(
                Mensaje.telefono,
                func.max(Mensaje.timestamp).label("ultima_fecha"),
                func.count(Mensaje.id).label("total_mensajes"),
            )
            .group_by(Mensaje.telefono)
            .order_by(func.max(Mensaje.timestamp).desc())
        )
        result = await session.execute(subq)
        filas = result.all()

        conversaciones = []
        for telefono, ultima_fecha, total_mensajes in filas:
            query_ultimo = (
                select(Mensaje)
                .where(Mensaje.telefono == telefono)
                .order_by(Mensaje.timestamp.desc())
                .limit(1)
            )
            r2 = await session.execute(query_ultimo)
            ultimo = r2.scalars().first()
            estado = await session.get(EstadoConversacion, telefono)
            conversaciones.append({
                "telefono": telefono,
                "ultima_fecha": ultima_fecha,
                "total_mensajes": total_mensajes,
                "ultimo_role": ultimo.role if ultimo else "",
                "ultimo_mensaje": ultimo.content if ultimo else "",
                "modo_humano": bool(estado and estado.modo_humano),
            })
        return conversaciones


async def obtener_historial_completo(telefono: str) -> list[dict]:
    """Recupera TODO el historial (sin límite) de una conversación, con fecha."""
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.asc())
        )
        result = await session.execute(query)
        mensajes = result.scalars().all()
        return [
            {"role": msg.role, "content": msg.content, "timestamp": msg.timestamp}
            for msg in mensajes
        ]


async def activar_modo_humano(telefono: str):
    """Marca la conversación para que el bot deje de responder automáticamente."""
    async with async_session() as session:
        estado = await session.get(EstadoConversacion, telefono)
        if estado:
            estado.modo_humano = True
            estado.actualizado = datetime.utcnow()
        else:
            estado = EstadoConversacion(telefono=telefono, modo_humano=True, actualizado=datetime.utcnow())
            session.add(estado)
        await session.commit()


async def desactivar_modo_humano(telefono: str):
    """Devuelve la conversación al bot (deja de estar en modo humano)."""
    async with async_session() as session:
        estado = await session.get(EstadoConversacion, telefono)
        if estado:
            estado.modo_humano = False
            estado.actualizado = datetime.utcnow()
            await session.commit()


async def esta_en_modo_humano(telefono: str) -> bool:
    """Retorna True si esta conversación está en manos de un humano ahora."""
    async with async_session() as session:
        estado = await session.get(EstadoConversacion, telefono)
        return bool(estado and estado.modo_humano)


async def guardar_adjunto(telefono: str, nombre_archivo: str, mime_type: str, contenido: bytes) -> int:
    """Guarda un archivo recibido (imagen/documento) y retorna su ID."""
    async with async_session() as session:
        adjunto = Adjunto(
            telefono=telefono,
            nombre_archivo=nombre_archivo,
            mime_type=mime_type,
            contenido=contenido,
            timestamp=datetime.utcnow(),
        )
        session.add(adjunto)
        await session.commit()
        await session.refresh(adjunto)
        return adjunto.id


async def obtener_adjunto(adjunto_id: int) -> dict | None:
    """Recupera un archivo guardado por su ID."""
    async with async_session() as session:
        adjunto = await session.get(Adjunto, adjunto_id)
        if not adjunto:
            return None
        return {
            "telefono": adjunto.telefono,
            "nombre_archivo": adjunto.nombre_archivo,
            "mime_type": adjunto.mime_type,
            "contenido": adjunto.contenido,
        }


async def limpiar_historial(telefono: str):
    """Borra todo el historial de una conversación."""
    async with async_session() as session:
        query = select(Mensaje).where(Mensaje.telefono == telefono)
        result = await session.execute(query)
        mensajes = result.scalars().all()
        for msg in mensajes:
            await session.delete(msg)
        await session.commit()
