"""Salida estructurada del Agente Clasificador (MF-05).

Este es el contrato que consume el Agente Extractor (MF-06, Mauricio) y
el grafo de LangGraph (MF-07, Jennifer + Kimberlyn). Pendiente de
alinear con el schema Pydantic definitivo del proyecto (MF-02, Manuel).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TipoDocumento(str, Enum):
    RECETA_MEDICA = "receta_medica"
    INFORME_ESTUDIO_DIAGNOSTICO = "informe_estudio_diagnostico"
    ORDEN_SOLICITUD_PROCEDIMIENTO = "orden_solicitud_procedimiento"
    EPICRISIS_INFORME_ALTA = "epicrisis_informe_alta"
    CERTIFICADO_MEDICO = "certificado_medico"
    NO_CLASIFICADO = "no_clasificado"


class ClassificationResult(BaseModel):
    """Resultado de clasificar un documento clinico."""

    tipo_documento: TipoDocumento
    especialidad: str = Field(
        ..., description="Especialidad clinica identificada, ej. 'Radiologia / Neumologia'"
    )
    confianza: float = Field(
        ..., ge=0.0, le=1.0, description="Confianza del modelo en la clasificacion (0-1)"
    )
    justificacion: str = Field(
        ..., description="Breve razon de la clasificacion, para auditoria/HITL"
    )
