"""
frontend.carga_archivos

Sección «Enviar documento»: carga un archivo al pipeline de MediFlow (POST /documentos de la API).

El formato NO se elige a mano: se deduce del propio archivo (extensión + contenido). Se aceptan solo
JPG, PNG, PDF, JSON y Markdown; cualquier otro se rechaza con un aviso que lista los formatos válidos.

Es un módulo nuevo e independiente: no modifica el panel HITL ni la API. Usa solo lo que ya existe
(`API_BASE_URL`, la sesión HTTP y `ErrorClienteAPI` de utils_frontend) y envía el archivo por el mismo
contrato que ya consume el backend.

Uso:
    streamlit run frontend/panel_carga.py --server.port 8501      (página propia)
o, para incrustarlo en otro panel:
    from carga_archivos import render_carga_archivos
    render_carga_archivos()

Variables de entorno: MEDIFLOW_MAX_MB_CARGA (20, igual que `maxUploadSize` de .streamlit/config.toml) ·
MEDIFLOW_TIMEOUT_CARGA (120 s: el pipeline llama a un LLM y puede tardar más que una consulta normal).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests
import streamlit as st
from utils_frontend import API_BASE_URL, ErrorClienteAPI, _mensaje_error, obtener_sesion

MAX_MB_CARGA = int(os.getenv("MEDIFLOW_MAX_MB_CARGA", "20"))
TIMEOUT_CONEXION_CARGA = 10
TIMEOUT_CARGA = int(os.getenv("MEDIFLOW_TIMEOUT_CARGA", "120"))
MAX_LARGO_ID = 80

# extensión -> (nombre para mostrar, Content-Type que se envía a la API).
# El backend solo acepta `text/*`, `application/pdf` e `image/*` (415 en cualquier otro caso): por eso JSON y
# Markdown viajan como `text/plain` (es lo que ya usan las pruebas de la API); `application/json` daría 415.
FORMATOS: dict[str, tuple[str, str]] = {
    "jpg": ("JPG", "image/jpeg"),
    "jpeg": ("JPG", "image/jpeg"),
    "png": ("PNG", "image/png"),
    "pdf": ("PDF", "application/pdf"),
    "json": ("JSON", "text/plain"),
    "md": ("Markdown", "text/plain"),
    "markdown": ("Markdown", "text/plain"),
}
LISTA_FORMATOS = "JPG, PNG, PDF, JSON y Markdown (.jpg, .jpeg, .png, .pdf, .json, .md, .markdown)"

_FIRMA_PNG = b"\x89PNG\r\n\x1a\n"
_FIRMA_JPG = b"\xff\xd8\xff"
_FIRMA_PDF = b"%PDF-"
_ID_VALIDO = re.compile(r"^[A-Za-z0-9._-]+$")  # mismo juego de caracteres que conserva el backend al guardar en OCI

ETIQUETA_ESTADO = {
    "estandar": "Automático",
    "urgente": "Alerta urgente",
    "revision_humana": "Auditoría humana",
    "error_tecnico": "Error técnico",
}


@dataclass(frozen=True)
class ValidacionArchivo:
    ok: bool
    error: str | None = None
    formato: str | None = None   # "JPG" | "PNG" | "PDF" | "JSON" | "Markdown"
    mime: str | None = None      # Content-Type a enviar a la API


def _rechazo(mensaje: str) -> ValidacionArchivo:
    return ValidacionArchivo(ok=False, error=mensaje)


def validar_archivo(nombre: str, contenido: bytes, max_mb: int = MAX_MB_CARGA) -> ValidacionArchivo:
    """Valida extensión, tamaño y contenido real. No envía nada: es lógica pura."""
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if extension not in FORMATOS:
        detectado = f"«.{extension}»" if extension else "sin extensión"
        return _rechazo(
            f"Formato o tipo de archivo no válido ({detectado}) en «{nombre}». "
            f"Formatos permitidos: {LISTA_FORMATOS}."
        )
    formato, mime = FORMATOS[extension]

    if not contenido:
        return _rechazo(f"El archivo «{nombre}» está vacío.")
    if len(contenido) > max_mb * 1024 * 1024:
        return _rechazo(f"El archivo «{nombre}» supera el tamaño máximo permitido ({max_mb} MB).")

    # El contenido debe corresponder a la extensión (evita, p. ej., un .txt renombrado a .pdf).
    coincide = {
        "PNG": contenido.startswith(_FIRMA_PNG),
        "JPG": contenido.startswith(_FIRMA_JPG),
        "PDF": _FIRMA_PDF in contenido[:1024],
    }.get(formato, True)
    if not coincide:
        return _rechazo(
            f"«{nombre}» no es un archivo {formato} válido: el contenido no coincide con la extensión. "
            f"Formatos permitidos: {LISTA_FORMATOS}."
        )

    if formato in ("JSON", "Markdown"):
        try:
            texto = contenido.decode("utf-8-sig")  # el backend decodifica los textos como UTF-8
        except UnicodeDecodeError:
            return _rechazo(f"«{nombre}» no está codificado en UTF-8. Guárdelo como UTF-8 y vuelva a cargarlo.")
        if not texto.strip():
            return _rechazo(f"El archivo «{nombre}» no tiene contenido.")
        if formato == "JSON":
            try:
                json.loads(texto)
            except json.JSONDecodeError as exc:
                return _rechazo(f"«{nombre}» no es un JSON válido (línea {exc.lineno}, columna {exc.colno}: {exc.msg}).")

    return ValidacionArchivo(ok=True, formato=formato, mime=mime)


def validar_campos(documento_id: str, canal_origen: str) -> str | None:
    """Devuelve el mensaje de error de los campos de texto, o None si están bien."""
    if not documento_id.strip():
        return "Escriba el ID del documento."
    if len(documento_id.strip()) > MAX_LARGO_ID or not _ID_VALIDO.match(documento_id.strip()):
        return (
            f"El ID del documento solo admite letras, números, punto, guion y guion bajo "
            f"(máximo {MAX_LARGO_ID} caracteres), sin espacios."
        )
    if not canal_origen.strip():
        return "Escriba el canal de origen."
    return None


def generar_id_documento() -> str:
    """ID único sugerido (editable): evita pisar sin querer el resultado de un documento anterior."""
    return f"DOC-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4].upper()}"


def enviar_documento(documento_id: str, canal_origen: str, nombre_archivo: str, contenido: bytes, mime: str) -> dict[str, Any]:
    """POST /documentos con el mismo contrato que ya usa el backend. Lanza ErrorClienteAPI si falla."""
    try:
        respuesta = obtener_sesion().post(
            f"{API_BASE_URL}/documentos",
            data={"documento_id": documento_id.strip(), "canal_origen": canal_origen.strip()},
            files={"archivo": (nombre_archivo, contenido, mime)},
            timeout=(TIMEOUT_CONEXION_CARGA, TIMEOUT_CARGA),
        )
    except requests.exceptions.ConnectionError as exc:
        raise ErrorClienteAPI(
            f"No hay conexión con la API en {API_BASE_URL} (¿está corriendo `uvicorn main:app`?)."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise ErrorClienteAPI(
            f"La API no respondió en {TIMEOUT_CARGA} s. El documento pudo haberse procesado: "
            "revise el resultado antes de reenviarlo."
        ) from exc
    if not respuesta.ok:
        raise ErrorClienteAPI(_mensaje_error(respuesta))
    return respuesta.json()


def _mostrar_resultado(resp: dict[str, Any]) -> None:
    st.success(resp.get("mensaje") or "Documento procesado correctamente por MediFlow.")
    if resp.get("persistencia_ok") is False:
        st.warning("El documento se procesó, pero no se pudo guardar el resultado en OCI.")
    clasificacion = resp.get("clasificacion") or {}
    extraccion = resp.get("extraccion") or {}
    c1, c2, c3 = st.columns(3)
    c1.metric("Documento ID", str(resp.get("documento_id", "—")))
    c2.metric("Destino", ETIQUETA_ESTADO.get(resp.get("estado"), str(resp.get("estado") or "—")))
    c3.metric("Nivel de urgencia", str(extraccion.get("nivel_urgencia") or "—"))
    st.caption("Para consultarlo más adelante, use «Consulta de resultados» con este ID.")
    if clasificacion.get("tipo_documento"):
        st.caption(f"Tipo de documento: {clasificacion['tipo_documento']}")
    with st.expander("Ver respuesta completa (JSON)"):
        st.json(resp, expanded=False)


def render_carga_archivos(clave: str = "carga") -> None:
    """Dibuja la sección «Enviar documento». Cada envío exitoso reinicia el formulario (nuevo ID, sin archivo)."""
    ronda = st.session_state.get(f"{clave}_ronda", 0)  # cambia las claves de los widgets para limpiarlos
    clave_id = f"{clave}_id_{ronda}"
    st.session_state.setdefault(clave_id, generar_id_documento())
    st.session_state.setdefault(f"{clave}_canal", "Panel_Web")

    with st.container(border=True):
        st.subheader("Enviar documento")
        documento_id = st.text_input("ID del documento", key=clave_id)
        canal_origen = st.text_input("Canal de origen", key=f"{clave}_canal", placeholder="ej. Guardia_Emergencias")
        archivo = st.file_uploader(
            "Cargar archivo",
            key=f"{clave}_archivo_{ronda}",
            help=f"Formatos permitidos: {LISTA_FORMATOS}. Tamaño máximo: {MAX_MB_CARGA} MB.",
        )  # sin `type=`: así el aviso de formato no válido es el nuestro (en español y con la lista de formatos)
        st.caption(f"Formatos permitidos: {LISTA_FORMATOS} · Máx. {MAX_MB_CARGA} MB")

        validacion = None
        contenido = b""
        if archivo is not None:
            contenido = archivo.getvalue()
            validacion = validar_archivo(archivo.name, contenido)
            if validacion.ok:
                st.caption(f"✅ Archivo {validacion.formato} válido.")
            else:
                st.error(validacion.error)

        enviar = st.button(
            "Enviar al pipeline", type="primary", key=f"{clave}_enviar_{ronda}",
            disabled=validacion is None or not validacion.ok,
        )

        if enviar and validacion is not None and validacion.ok:
            error_campos = validar_campos(documento_id, canal_origen)
            if error_campos:
                st.error(error_campos)
            else:
                try:
                    with st.spinner("Procesando el documento en el pipeline…"):
                        resp = enviar_documento(documento_id, canal_origen, archivo.name, contenido, validacion.mime)
                except ErrorClienteAPI as exc:
                    st.error(f"No se pudo enviar el documento: {exc}")
                else:
                    st.session_state[f"{clave}_ultimo"] = resp
                    st.session_state["ultimo_documento_id"] = documento_id.strip()  # precarga la consulta
                    st.session_state[f"{clave}_ronda"] = ronda + 1
                    st.rerun()

    ultimo = st.session_state.get(f"{clave}_ultimo")
    if ultimo:
        _mostrar_resultado(ultimo)
