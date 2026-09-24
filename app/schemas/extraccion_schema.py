"""
schemas/extraccion_schema.py

Esquema Pydantic para la salida del Agente Extractor (MF-06).

Version borrador basada en los campos descritos en la actividad MF-06
(paciente, profesional, diagnóstico/CIE-10, medicamentos, estudios
solicitados, urgencia). Ajustar / reemplazar cuando Manuel entregue el
schema definitivo acordado con el resto de agentes del grafo.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class NivelUrgencia(str, Enum):
    NO_URGENTE = "no_urgente"
    PRIORITARIO = "prioritario"
    URGENTE = "urgente"
    EMERGENCIA = "emergencia"


class Paciente(BaseModel):
    nombre_completo: Optional[str] = Field(
        None, description="Nombre completo del paciente tal como aparece en el documento"
    )
    tipo_documento: Optional[str] = Field(None, description="Ej: CC, TI, CE, pasaporte")
    numero_documento: Optional[str] = None
    edad: Optional[int] = None
    sexo: Optional[str] = None


class Profesional(BaseModel):
    nombre_completo: Optional[str] = None
    registro_profesional: Optional[str] = Field(
        None, description="Número de tarjeta profesional / matrícula"
    )
    especialidad: Optional[str] = None
    institucion: Optional[str] = None


class Diagnostico(BaseModel):
    descripcion: str
    codigo_cie10: Optional[str] = Field(
        None,
        description=(
            "Código CIE-10 solo si aparece explícito en el documento o si puede "
            "inferirse con alta confianza a partir de un diagnóstico inequívoco"
        ),
    )
    tipo: Optional[str] = Field(None, description="principal | secundario | presuntivo")


class Medicamento(BaseModel):
    nombre: str
    dosis: Optional[str] = None
    via_administracion: Optional[str] = None
    frecuencia: Optional[str] = None
    duracion: Optional[str] = None


class EstudioSolicitado(BaseModel):
    tipo: str = Field(..., description="Ej: laboratorio, imagenología, interconsulta")
    descripcion: str
    prioridad: Optional[str] = None


class ExtraccionClinica(BaseModel):
    """Salida completa del Agente Extractor (nodo AGENTE 2 del grafo)."""

    tipo_documento: str = Field(..., description="Heredado de la clasificación del Agente 1")
    especialidad: Optional[str] = Field(
        None, description="Heredado de la clasificación del Agente 1"
    )
    paciente: Paciente
    profesional: Profesional
    diagnosticos: List[Diagnostico] = Field(default_factory=list)
    medicamentos: List[Medicamento] = Field(default_factory=list)
    estudios_solicitados: List[EstudioSolicitado] = Field(default_factory=list)
    nivel_urgencia: Optional[NivelUrgencia] = None
    senales_gravedad: List[str] = Field(
        default_factory=list,
        description=(
            "Frases o hallazgos textuales del documento que respaldan el nivel de "
            "urgencia; insumo directo para el nodo '¿Urgente?' del grafo"
        ),
    )
    fecha_documento: Optional[str] = None
    observaciones: Optional[str] = None
    campos_no_encontrados: List[str] = Field(
        default_factory=list,
        description=(
            "Campos esperados que el modelo no pudo extraer del documento; insumo "
            "para el nodo 'Evaluación de confianza y consistencia'"
        ),
    )
