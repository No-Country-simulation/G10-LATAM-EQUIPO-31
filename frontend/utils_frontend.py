"""
frontend.utils_frontend  (MF-12)

Cliente HTTP del panel de revisión humana (HITL) y utilidades de presentación. El panel SOLO habla con
la API de MediFlow (GET /auditoria/bandeja, GET /documentos/{id}/historial, POST /auditoria/{id}/decision):
las credenciales de OCI quedan en el servidor y el panel no las necesita.

Variables de entorno: MEDIFLOW_API_URL (http://localhost:8000) · MEDIFLOW_ZONA_HORARIA (America/Bogota)
· MEDIFLOW_MAX_COLA (50).
"""
from __future__ import annotations

import os
import threading
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE_URL = os.getenv("MEDIFLOW_API_URL", "http://localhost:8000")
TIMEOUT_CONEXION = 10
TIMEOUT_CONSULTA = 15
MAX_COLA = int(os.getenv("MEDIFLOW_MAX_COLA", "50"))

# Mismo contrato que el backend (app/services/auditoria_eventos.py). Solo APROBAR o RECHAZAR: no hay corrección.
DECISIONES_AUDITORIA = ("APROBADO", "RECHAZADO")
MOTIVOS_RECHAZO = {
    "ILEGIBLE": "Documento ilegible o de baja calidad",
    "INCOMPLETO": "Documento incompleto (faltan datos clave)",
    "INCONSISTENTE": "Datos inconsistentes o sospechosos",
    "TIPO_INCORRECTO": "No corresponde al tipo de documento esperado",
    "OTRO": "Otro motivo (detallar en notas)",
}
TIPO_NO_CLASIFICADO = "No Clasificado"
TIPOS_DOCUMENTO_MF02 = [
    "Receta Medica",
    "Informe de Estudio de Diagnostico por Imagenes/Laboratorio",
    "Orden de Solicitud de Procedimiento",
    "Epicrisis / Informe de Alta",
    "Certificado Medico",
    TIPO_NO_CLASIFICADO,
]


class ErrorClienteAPI(Exception):
    """Se lanza cuando una llamada a la API de MediFlow falla."""


class ErrorDecisionConflicto(ErrorClienteAPI):
    """409: el documento ya no está pendiente (otro auditor decidió o se reprocesó)."""


def es_conflicto(exc: Exception) -> bool:
    return isinstance(exc, ErrorDecisionConflicto) or str(exc).startswith("409:")


# --------------------------------------------------------------------------
# Sesión HTTP (una por hilo: Streamlit atiende cada sesión en su propio hilo y requests.Session no es thread-safe)
# --------------------------------------------------------------------------
_local = threading.local()


def _crear_sesion() -> requests.Session:
    sesion = requests.Session()
    politica = Retry(
        total=4, connect=4,                       # la petición no llegó al servidor: reintentar es seguro
        read=2, status=2, backoff_factor=0.7,     # read/status solo aplican a métodos idempotentes, nunca a POST
        status_forcelist=(502, 503, 504), allowed_methods=frozenset({"GET", "HEAD", "OPTIONS", "PUT"}),
        raise_on_status=False,
    )
    sesion.mount("http://", HTTPAdapter(max_retries=politica, pool_maxsize=4))
    sesion.mount("https://", HTTPAdapter(max_retries=politica, pool_maxsize=4))
    return sesion


def obtener_sesion() -> requests.Session:
    if getattr(_local, "sesion", None) is None:
        _local.sesion = _crear_sesion()
    return _local.sesion


def _mensaje_error(respuesta: requests.Response) -> str:
    """Extrae el `detail` que devuelve FastAPI en vez del mensaje genérico de requests."""
    try:
        cuerpo = respuesta.json()
        detalle = cuerpo.get("detail")
        if not detalle and (cuerpo.get("mensaje") or cuerpo.get("error")):
            detalle = " — ".join(str(x) for x in (cuerpo.get("mensaje"), cuerpo.get("error")) if x)
        if detalle:
            return f"{respuesta.status_code}: {detalle}"
    except Exception:
        pass
    return f"{respuesta.status_code} {respuesta.reason}"


def _solicitar(metodo: str, ruta: str, **kwargs: Any) -> Any:
    try:
        respuesta = obtener_sesion().request(
            metodo, f"{API_BASE_URL}{ruta}", timeout=(TIMEOUT_CONEXION, TIMEOUT_CONSULTA), **kwargs
        )
    except requests.exceptions.ConnectionError as exc:
        raise ErrorClienteAPI(
            f"No hay conexión con la API en {API_BASE_URL} (¿está corriendo `uvicorn main:app`?)."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise ErrorClienteAPI(
            "La API tardó demasiado en responder. Si estaba guardando una decisión, actualice la bandeja "
            "antes de repetirla."
        ) from exc
    if not respuesta.ok:
        mensaje = _mensaje_error(respuesta)
        raise (ErrorDecisionConflicto if respuesta.status_code == 409 else ErrorClienteAPI)(mensaje)
    return respuesta.json()


def _ruta_documento(documento_id: str) -> str:
    return urllib.parse.quote(documento_id, safe="")


# --------------------------------------------------------------------------
# Presentación
# --------------------------------------------------------------------------
ZONA_HORARIA = os.getenv("MEDIFLOW_ZONA_HORARIA", "America/Bogota")


def _zona() -> Any:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(ZONA_HORARIA)
    except Exception:  # sin base tzdata en el sistema: UTC-5 fijo
        return timezone(timedelta(hours=-5))


def formatear_fecha(iso_utc: Any) -> str:
    """'2026-10-01T14:24:10+00:00' -> '01/10/2026 09:24' (hora local). Si no se puede leer, devuelve el texto tal cual."""
    if not iso_utc:
        return "—"
    try:
        valor = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    except ValueError:
        return str(iso_utc)
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(_zona()).strftime("%d/%m/%Y %H:%M")


def _nombre_campo(clave: str) -> str:
    return clave.replace("_", " ").strip().capitalize()


def aplanar_extraccion(datos: Any, prefijo: str = "") -> list[dict[str, str]]:
    """Extracción (JSON anidado) -> filas {Campo, Valor} legibles. Solo lectura: el documento no se edita."""
    filas: list[dict[str, str]] = []
    if isinstance(datos, dict):
        for clave, valor in datos.items():
            nombre = f"{prefijo} › {_nombre_campo(clave)}" if prefijo else _nombre_campo(clave)
            if isinstance(valor, (dict, list)):
                filas += aplanar_extraccion(valor, nombre)
            else:
                filas.append({"Campo": nombre, "Valor": "—" if valor in (None, "") else str(valor)})
    elif isinstance(datos, list):
        if datos and all(not isinstance(v, (dict, list)) for v in datos):
            filas.append({"Campo": prefijo, "Valor": ", ".join(map(str, datos))})
        else:
            for i, valor in enumerate(datos, 1):
                filas += aplanar_extraccion(valor, f"{prefijo} #{i}")
        if not datos:
            filas.append({"Campo": prefijo, "Valor": "—"})
    return filas


def es_nivel_urgente(nivel: Any) -> bool:
    """`nivel_urgencia` del Extractor: no_urgente | prioritario | urgente | emergencia."""
    return str(nivel or "").strip().lower() in {"urgente", "emergencia", "alerta_urgente"}


def item_es_urgente(item: dict[str, Any]) -> bool:
    """MF-11 conserva `urgente` aunque el documento vaya a revisión humana: se muestra como prioritario."""
    if item.get("urgente"):
        return True
    prioridad = (item.get("clasificacion") or {}).get("nivel_prioridad")
    return es_nivel_urgente(item.get("nivel_urgencia")) or str(prioridad or "").strip().lower() == "urgente"


def _clave_tipo(valor: Any) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.casefold().split())


_TIPOS_POR_CLAVE = {_clave_tipo(t): t for t in TIPOS_DOCUMENTO_MF02}
_ALIAS_TIPOS_LEGADOS = {"otro": TIPO_NO_CLASIFICADO, "desconocido": TIPO_NO_CLASIFICADO}


def normalizar_tipo_documento(valor: Any) -> str:
    """Nombre canónico MF-02 (ignora mayúsculas/acentos). Vacío/None/OTRO -> 'No Clasificado'; desconocido, tal cual."""
    if valor is None or not str(valor).strip():
        return TIPO_NO_CLASIFICADO
    clave = _clave_tipo(valor)
    return _TIPOS_POR_CLAVE.get(clave) or _ALIAS_TIPOS_LEGADOS.get(clave) or str(valor)


# --------------------------------------------------------------------------
# Eventos de la API -> filas/items del panel
# --------------------------------------------------------------------------
def _item_desde_evento(evento: dict[str, Any]) -> dict[str, Any]:
    """Evento de historial (envelope + `resumen` + `recorrido`, MF-15) -> item de la bandeja."""
    resultado = evento.get("resultado") or {}
    clasificacion = resultado.get("clasificacion") or {}
    if not isinstance(clasificacion, dict):
        clasificacion = {"tipo_documento": clasificacion}
    tipo = clasificacion.get("tipo_documento") or clasificacion.get("tipo")
    recorrido = evento.get("recorrido") or {}
    modelos = dict(recorrido.get("proveedor_modelo") or {})
    if not modelos:
        modelos = {"clasificador": resultado.get("metadata_clasificacion"), "extractor": resultado.get("metadata_extraccion")}
    return {
        "documento_id": evento.get("documento_id") or "",
        "evento_id": evento.get("evento_id"),
        "tipo_documento": normalizar_tipo_documento(tipo),
        "nivel_urgencia": evento.get("nivel_urgencia") or clasificacion.get("nivel_urgencia"),
        "urgente": evento.get("urgente"),  # MF-11; se conserva aunque vaya a revisión humana
        "estado": evento.get("estado"),
        "timestamp": evento.get("timestamp"),
        "validacion_ok": resultado.get("validacion_ok"),
        "errores_validacion": resultado.get("errores_validacion") or [],
        "inconsistencias": resultado.get("inconsistencias") or [],  # MF-09
        "score_confianza_final": resultado.get("score_confianza_final"),  # MF-10
        "categoria_confianza": resultado.get("categoria_confianza"),
        "motivos_confianza": resultado.get("motivos_confianza") or [],  # lista de textos; se muestra tal cual
        "justificacion_enrutamiento": resultado.get("justificacion_enrutamiento"),  # MF-11
        "requiere_auditoria_humana": resultado.get("requiere_auditoria_humana"),
        "clasificacion": clasificacion,
        "extraccion": resultado.get("extraccion") or {},
        "resumen": evento.get("resumen") or {},
        "recorrido": recorrido,
        "metadata": {k: v for k, v in modelos.items() if v},
    }


def _fila_decision(evento: dict[str, Any]) -> dict[str, Any]:
    return {
        "documento_id": evento.get("documento_id"),
        "decision": evento.get("decision"),
        "auditor": evento.get("auditor"),
        "timestamp": evento.get("timestamp"),
        "tipo_documento": normalizar_tipo_documento(evento.get("tipo_documento")),
        "motivo": evento.get("motivo"),
        "notas": evento.get("notas") or "",
    }


# --------------------------------------------------------------------------
# Operaciones del panel
# --------------------------------------------------------------------------
def obtener_bandeja(limite: int = MAX_COLA) -> dict[str, Any]:
    """{'pendientes': [item], 'total_pendientes': n, 'resueltos': [fila], 'avisos': [str]}"""
    bruta = _solicitar("GET", "/auditoria/bandeja", params={"limite": limite})
    return {
        "pendientes": [_item_desde_evento(e) for e in bruta.get("pendientes", [])],
        "total_pendientes": bruta.get("total_pendientes", len(bruta.get("pendientes", []))),
        "resueltos": [_fila_decision(e) for e in bruta.get("resueltos", [])],
        "avisos": bruta.get("avisos", []),
    }


def obtener_linea_tiempo(documento_id: str) -> list[dict[str, Any]]:
    """Línea de tiempo del documento (procesamientos y decisiones), en orden cronológico."""
    eventos = _solicitar("GET", f"/documentos/{_ruta_documento(documento_id)}/historial")["eventos"]
    filas = []
    for e in eventos:
        if e.get("tipo_evento") == "decision_humana":
            etiqueta = "Decisión humana"
            motivo = MOTIVOS_RECHAZO.get(e.get("motivo") or "", "")
            detalle = f"{e.get('decision')} por {e.get('auditor')}" + (f" · {motivo}" if motivo else "") + (
                f" — {e['notas']}" if e.get("notas") else "")
        else:
            etiqueta = "Procesamiento"
            conf = (e.get("resumen") or {}).get("categoria_confianza")
            huella = e.get("huella_sha256")
            detalle = f"estado: {e.get('estado')}" + (f" · confianza {conf}" if conf else "") + (
                f" · huella {str(huella)[:8]}" if huella else "")
        filas.append({"evento": etiqueta, "fecha": formatear_fecha(e.get("timestamp")), "detalle": detalle})
    return filas


def registrar_decision_auditoria(
    item: dict[str, Any], decision: str, notas: str, auditor: str, motivo: str | None = None,
) -> dict[str, Any]:
    """Guarda la decisión (APROBADO | RECHAZADO) como evento `decision_humana` en la línea de tiempo."""
    return _solicitar(
        "POST", f"/auditoria/{_ruta_documento(item['documento_id'])}/decision",
        json={"decision": decision, "auditor": auditor, "notas": notas, "motivo": motivo},
    )
