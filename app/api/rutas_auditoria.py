"""
app/api/rutas_auditoria.py  (MF-12 -- endpoints del mecanismo HITL)

Registrados en main.py con `app.include_router(router_auditoria)`; no tocan las rutas de
`app/api/routes.py` (POST /documentos, estándar/urgente/revision_humana siguen igual).

  GET  /auditoria/bandeja                    casos pendientes de revisión humana + decisiones recientes
  GET  /documentos/{id}/historial            línea de tiempo del documento (procesamientos y decisiones)
  POST /auditoria/{id}/decision              APROBADO | RECHAZADO (motivo y notas obligatorios al rechazar)

Las credenciales de OCI quedan solo en el servidor. Los endpoints son síncronos (`def`): el SDK de
OCI es bloqueante y FastAPI los ejecuta en un hilo. Estos endpoints NO envían notificaciones (MF-14).
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import auditoria_eventos as eventos
from app.services.almacen_oci import AlmacenOCI
from app.services.oci_storage_service import OCIStorageService

logger = logging.getLogger("mediflow.app.api.rutas_auditoria")

router = APIRouter(tags=["auditoria"])


def obtener_almacen() -> eventos.Almacen:
    return AlmacenOCI(OCIStorageService())


class DecisionEntrada(BaseModel):
    # El revisor solo aprueba o rechaza: no corrige datos clínicos de un documento ajeno.
    decision: Literal["APROBADO", "RECHAZADO"]
    auditor: str = Field(min_length=1)
    notas: str = ""
    motivo: Literal["ILEGIBLE", "INCOMPLETO", "INCONSISTENTE", "TIPO_INCORRECTO", "OTRO"] | None = None


def _http(exc: eventos.ErrorAuditoria) -> HTTPException:
    codigo = {
        eventos.DocumentoNoEncontrado: 404,
        eventos.DocumentoNoPendiente: 409,
        eventos.DecisionInvalida: 422,
    }.get(type(exc), 400)
    return HTTPException(status_code=codigo, detail=str(exc))


@router.get("/auditoria/bandeja")
def bandeja(limite: int = Query(50, ge=1, le=200), almacen=Depends(obtener_almacen)):
    return eventos.construir_bandeja(almacen, limite=limite)


@router.get("/documentos/{documento_id}/historial")
def historial(documento_id: str, almacen=Depends(obtener_almacen)):
    lista = eventos.historial_de(almacen, documento_id)
    if not lista:
        raise HTTPException(status_code=404, detail=f"Sin historial para {documento_id!r}.")
    return {"documento_id": documento_id, "eventos": lista}


@router.post("/auditoria/{documento_id}/decision", status_code=201)
def decidir(documento_id: str, cuerpo: DecisionEntrada, almacen=Depends(obtener_almacen)):
    try:
        evento = eventos.registrar_decision(
            almacen, documento_id, cuerpo.decision, cuerpo.auditor, cuerpo.notas, motivo=cuerpo.motivo,
        )
    except eventos.ErrorAuditoria as exc:
        # Se registra quién intentó qué y por qué no procedió; nunca datos clínicos ni el texto de las notas.
        logger.warning(
            "Decisión HITL no registrada: documento_id=%r decision=%s auditor=%r motivo_error=%s",
            documento_id, cuerpo.decision, cuerpo.auditor, type(exc).__name__,
        )
        raise _http(exc) from exc
    logger.info(
        "Decisión HITL registrada: documento_id=%r decision=%s motivo=%s auditor=%r evento=%s",
        documento_id, evento["decision"], evento.get("motivo"), evento["auditor"], evento["evento_id"],
    )
    return evento
