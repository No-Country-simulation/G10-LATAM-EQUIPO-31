"""
app/services/auditoria_eventos.py  (MF-12 -- mecanismo HITL sobre historial/)

Lógica de la bandeja de revisión humana. Cada documento tiene UNA línea de tiempo en
`historial/{clave}/` (MF-15). MF-12 solo AGREGA a esa línea de tiempo un tipo de evento:

    historial/{clave}/{timestamp}.json           procesamiento (MF-15, ya existe; no se toca)
    historial/{clave}/{timestamp}_decision.json  decisión humana APROBADO | RECHAZADO (NUEVO)

Reglas
* El revisor SOLO aprueba o rechaza. No hay corrección de datos clínicos: el documento es de un
  tercero y el revisor no puede suponer posología ni diagnóstico.
* RECHAZADO exige un motivo (catálogo MOTIVOS_RECHAZO) y notas. APROBADO no lleva motivo.
* ESTADO VIGENTE de un documento = carpeta de resultado más reciente (procesados/* o
  errores_tecnicos/). MF-13 no borra el resultado anterior al reprocesar, así que una copia vieja en
  procesados/revision_humana/ NO significa "pendiente".
* PENDIENTE = estado vigente `revision_humana` y último evento de historial que NO es una decisión.
  RESUELTO = estado vigente `revision_humana` y último evento que SÍ es una decisión.
  Reprocesar un documento resuelto agrega un procesamiento nuevo y vuelve a dejarlo pendiente.
* Las decisiones nunca se sobrescriben (escritura "solo si no existe") y no mueven ni borran
  archivos: `recibidos/`, `procesados/*` e historial previo quedan intactos.
* La huella SHA-256 (MF-22) NO se usa para decidir nada aquí. Si el evento sobre el que se decide
  ya la trae (campo CAMPO_HUELLA), la decisión la COPIA para trazabilidad; si no la trae, se guarda
  igual sin ella.
* El auditor es un texto libre (no hay autenticación en el MVP): queda registrado en cada decisión.
* Este módulo no envía notificaciones (Slack/correo es MF-14).

Solo usa la biblioteca estándar: la misma lógica sirve con OCI (producción) y con memoria (tests).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

PREFIJO_HISTORIAL = "historial/"
CARPETAS_ESTADO = {
    "estandar": "procesados/estandar/",
    "urgente": "procesados/urgente/",
    "revision_humana": "procesados/revision_humana/",
    "error_tecnico": "errores_tecnicos/",
}
ESTADO_PENDIENTE = "revision_humana"
SUFIJO_DECISION = "_decision"
TIPO_PROCESAMIENTO = "procesamiento"  # los eventos de MF-15 no traen `tipo_evento`
TIPO_DECISION = "decision_humana"
CAMPO_HUELLA = "huella_sha256"  # NOMBRE A CONFIRMAR con MF-22 (SHA-256 hex del contenido recibido)
SCHEMA_VERSION = 1
DECISIONES = ("APROBADO", "RECHAZADO")
MOTIVOS_RECHAZO = ("ILEGIBLE", "INCOMPLETO", "INCONSISTENTE", "TIPO_INCORRECTO", "OTRO")
_EPOCA = datetime.min.replace(tzinfo=timezone.utc)
_MOMENTO = re.compile(r"^(\d{8}T\d{12})")
_FORMATO_MOMENTO = "%Y%m%dT%H%M%S%f"


class ErrorAuditoria(Exception):
    """Base de los errores de negocio de la bandeja."""


class DecisionInvalida(ErrorAuditoria):  # -> HTTP 422
    pass


class DocumentoNoEncontrado(ErrorAuditoria):  # -> HTTP 404
    pass


class DocumentoNoPendiente(ErrorAuditoria):  # -> HTTP 409
    pass


class Almacen(Protocol):
    """Lo mínimo que se necesita del almacenamiento: lo implementa OCIStorageService (producción) y, en tests, un almacén en memoria."""

    def listar(self, prefijo: str) -> list[tuple[str, datetime | None]]: ...
    def leer_json(self, nombre: str) -> dict[str, Any]: ...
    def escribir_json_nuevo(self, nombre: str, contenido: dict[str, Any]) -> Any:
        """Escribe SIN sobrescribir; debe lanzar FileExistsError si el objeto ya existe."""


def sanitizar_clave(documento_id: str) -> str:
    """Misma regla que `_sanitizar_nombre_archivo` de oci_storage_service.py."""
    nombre = documento_id.replace("\\", "/").split("/")[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", nombre) or "archivo"


def nombre_decision(clave: str, momento: datetime) -> str:
    marca = momento.astimezone(timezone.utc).strftime(_FORMATO_MOMENTO)
    return f"{PREFIJO_HISTORIAL}{clave}/{marca}{SUFIJO_DECISION}.json"


def _archivo(nombre: str) -> str:
    return nombre.rsplit("/", 1)[1]


def es_nombre_decision(nombre: str) -> bool:
    """Distingue una decisión de un procesamiento SIN leer el objeto (solo por el nombre)."""
    return _archivo(nombre).endswith(f"{SUFIJO_DECISION}.json")


def tipo_evento(evento: dict[str, Any]) -> str:
    return evento.get("tipo_evento") or TIPO_PROCESAMIENTO


def _momento_de(nombre: str) -> datetime | None:
    m = _MOMENTO.match(_archivo(nombre))
    return datetime.strptime(m.group(1), _FORMATO_MOMENTO).replace(tzinfo=timezone.utc) if m else None


def _huella(evento: dict[str, Any]) -> str | None:
    valor = evento.get(CAMPO_HUELLA)
    return valor.strip().lower() if isinstance(valor, str) and valor.strip() else None


# --------------------------------------------------------------------------
# Índices (solo listados, sin leer objetos)
# --------------------------------------------------------------------------
def _estados_vigentes(almacen: Almacen) -> dict[str, tuple[str, datetime, str]]:
    """clave -> (estado, fecha_de_escritura, nombre_del_resultado) de la carpeta más reciente."""
    vigentes: dict[str, tuple[str, datetime, str]] = {}
    for estado, prefijo in CARPETAS_ESTADO.items():
        for nombre, fecha in almacen.listar(prefijo):
            resto = nombre[len(prefijo):]
            if not resto.endswith(".json") or "/" in resto:
                continue
            clave, fecha = resto[: -len(".json")], fecha or _EPOCA
            if clave not in vigentes or fecha > vigentes[clave][1]:
                vigentes[clave] = (estado, fecha, nombre)
    return vigentes


def _eventos_por_clave(almacen: Almacen) -> dict[str, list[str]]:
    """clave -> nombres de sus eventos de historial, del más antiguo al más reciente."""
    por_clave: dict[str, list[str]] = {}
    for nombre, _ in almacen.listar(PREFIJO_HISTORIAL):
        partes = nombre[len(PREFIJO_HISTORIAL):].split("/")
        if len(partes) == 2 and partes[1].endswith(".json"):
            por_clave.setdefault(partes[0], []).append(nombre)
    return {c: sorted(ns, key=_archivo) for c, ns in por_clave.items()}


def _situacion(clave: str, vigentes: dict, eventos: dict) -> tuple[str | None, str | None]:
    """('pendiente' | 'resuelto' | None, nombre del último evento). Se deduce del NOMBRE, sin leer objetos."""
    if clave not in vigentes or vigentes[clave][0] != ESTADO_PENDIENTE:
        return None, None
    nombres = eventos.get(clave) or []
    ultimo = nombres[-1] if nombres else None
    if not ultimo or not es_nombre_decision(ultimo):
        return "pendiente", ultimo
    return "resuelto", ultimo


# --------------------------------------------------------------------------
# Operaciones
# --------------------------------------------------------------------------
def construir_bandeja(almacen: Almacen, limite: int = 50, max_resueltos: int = 20) -> dict[str, Any]:
    """
    {'pendientes': [evento...], 'total_pendientes': n, 'resueltos': [evento_decision...], 'avisos': [...]}
    Los eventos son el JSON tal cual está guardado (más `evento_id`).
    Si un pendiente no tiene historial (p. ej. historial_ok=false), se usa su resultado de procesados/.
    """
    vigentes, eventos = _estados_vigentes(almacen), _eventos_por_clave(almacen)
    pendientes: list[tuple[datetime, str]] = []
    resueltos: list[str] = []
    for clave, (_, fecha, nombre_resultado) in vigentes.items():
        situacion, ultimo = _situacion(clave, vigentes, eventos)
        if situacion == "pendiente":
            pendientes.append((fecha, ultimo or nombre_resultado))
        elif situacion == "resuelto":
            resueltos.append(ultimo)
    pendientes.sort(key=lambda x: x[0], reverse=True)
    resueltos.sort(key=_archivo, reverse=True)

    avisos: list[str] = []

    def leer(nombre: str) -> dict[str, Any] | None:
        try:
            evento = almacen.leer_json(nombre)
        except Exception as exc:  # un objeto corrupto no debe tumbar toda la bandeja
            avisos.append(f"No se pudo leer {nombre}: {exc}")
            return None
        evento.setdefault("evento_id", _archivo(nombre))
        return evento

    lista = [e for e in (leer(n) for _, n in pendientes[:limite]) if e]
    resueltas = [e for e in (leer(n) for n in resueltos[:max_resueltos]) if e]
    if len(pendientes) > limite:
        avisos.append(f"Se muestran los {limite} más recientes de {len(pendientes)} pendientes.")
    return {"pendientes": lista, "total_pendientes": len(pendientes), "resueltos": resueltas, "avisos": avisos}


def historial_de(almacen: Almacen, documento_id: str) -> list[dict[str, Any]]:
    """Línea de tiempo completa (procesamientos y decisiones), de la más antigua a la más reciente."""
    clave = sanitizar_clave(documento_id)
    nombres = sorted(
        (n for n, _ in almacen.listar(f"{PREFIJO_HISTORIAL}{clave}/") if n.endswith(".json")), key=_archivo
    )
    salida = []
    for nombre in nombres:
        evento = almacen.leer_json(nombre)
        evento.setdefault("evento_id", _archivo(nombre))
        salida.append(evento)
    return salida


def _contexto(evento: dict[str, Any]) -> dict[str, Any]:
    resultado = evento.get("resultado") or {}
    clasificacion = resultado.get("clasificacion") or {}
    if not isinstance(clasificacion, dict):
        clasificacion = {"tipo_documento": clasificacion}
    return {
        "tipo_documento": clasificacion.get("tipo_documento"),
        "nivel_urgencia": evento.get("nivel_urgencia"),
        "urgente": evento.get("urgente"),
        "categoria_confianza": resultado.get("categoria_confianza"),
    }


def registrar_decision(
    almacen: Almacen,
    documento_id: str,
    decision: str,
    auditor: str,
    notas: str = "",
    motivo: str | None = None,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """
    Agrega un evento `decision_humana` a la línea de tiempo. Lanza ErrorAuditoria si no corresponde.
    APROBADO: sin motivo. RECHAZADO: motivo (catálogo) y notas obligatorios.
    """
    if decision not in DECISIONES:
        raise DecisionInvalida(f"Decisión inválida: {decision!r}. Use {', '.join(DECISIONES)}.")
    if not (auditor or "").strip():
        raise DecisionInvalida("El auditor es obligatorio.")
    if decision == "RECHAZADO":
        if motivo not in MOTIVOS_RECHAZO:
            raise DecisionInvalida(f"El motivo del rechazo es obligatorio. Use {', '.join(MOTIVOS_RECHAZO)}.")
        if not (notas or "").strip():
            raise DecisionInvalida("Las notas son obligatorias para rechazar.")
    elif motivo is not None:
        raise DecisionInvalida("El motivo solo se admite al RECHAZAR.")

    clave = sanitizar_clave(documento_id)
    vigentes, eventos = _estados_vigentes(almacen), _eventos_por_clave(almacen)
    if clave not in vigentes:
        raise DocumentoNoEncontrado(f"No existe un resultado para el documento {documento_id!r}.")
    situacion, ultimo = _situacion(clave, vigentes, eventos)
    if situacion != "pendiente":
        raise DocumentoNoPendiente(
            f"El documento {documento_id!r} no está pendiente de revisión humana "
            f"(estado vigente: {vigentes[clave][0]}; "
            f"{'ya tiene una decisión' if situacion == 'resuelto' else 'no está en revisión humana'}).")

    referencia = ultimo or vigentes[clave][2]
    base = almacen.leer_json(referencia)
    ahora = _momento_despues_del_ultimo(ahora, ultimo)
    evento: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tipo_evento": TIPO_DECISION,
        "documento_id": base.get("documento_id") or documento_id,
        "decision": decision,
        "notas": (notas or "").strip(),
        "auditor": auditor.strip(),
        "timestamp": ahora.astimezone(timezone.utc).isoformat(),
        **_contexto(base),
        "evento_referencia": referencia,
    }
    if _huella(base):
        evento[CAMPO_HUELLA] = _huella(base)  # trazabilidad: huella del contenido sobre el que se decide
    if decision == "RECHAZADO":
        evento["motivo"] = motivo
    nombre = nombre_decision(clave, ahora)
    try:
        almacen.escribir_json_nuevo(nombre, evento)
    except FileExistsError as exc:
        raise DocumentoNoPendiente("Otro auditor registró una decisión al mismo tiempo.") from exc
    evento["evento_id"] = _archivo(nombre)
    return evento


def _momento_despues_del_ultimo(ahora: datetime | None, ultimo: str | None) -> datetime:
    """La decisión SIEMPRE debe quedar después del último evento (se ordena por nombre), aunque el
    reloj de quien escribe vaya atrasado respecto del backend."""
    ahora = ahora or datetime.now(timezone.utc)
    anterior = _momento_de(ultimo) if ultimo else None
    if anterior and ahora.astimezone(timezone.utc) <= anterior:
        ahora = anterior + timedelta(microseconds=1)
    return ahora
