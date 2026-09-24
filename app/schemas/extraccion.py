from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class NivelUrgencia(str, Enum):
    """
    Niveles de urgencia clínica identificados durante la extracción.
    """

    NO_URGENTE = "no_urgente"
    PRIORITARIO = "prioritario"
    URGENTE = "urgente"
    EMERGENCIA = "emergencia"


class Paciente(BaseModel):
    """
    Información identificativa y demográfica del paciente
    encontrada en el documento clínico.
    """

    nombre_completo: Optional[str] = None
    tipo_documento: Optional[str] = None
    numero_documento: Optional[str] = None
    edad: Optional[int] = None
    sexo: Optional[str] = None


class Profesional(BaseModel):
    """
    Información del profesional de salud asociado al documento.
    """

    nombre_completo: Optional[str] = None
    registro_profesional: Optional[str] = None
    especialidad: Optional[str] = None
    institucion: Optional[str] = None


class Diagnostico(BaseModel):
    """
    Diagnóstico identificado en el documento clínico.
    """

    descripcion: str

    codigo_cie10: Optional[str] = Field(
        default=None,
        description=(
            "Código CIE-10 cuando aparece explícitamente en el documento "
            "o puede determinarse con alta confianza."
        ),
    )

    tipo: Optional[str] = Field(
        default=None,
        description="Tipo de diagnóstico: principal, secundario o presuntivo.",
    )


class Medicamento(BaseModel):
    """
    Medicamento y datos asociados a su administración.
    """

    nombre: str
    dosis: Optional[str] = None
    via_administracion: Optional[str] = None
    frecuencia: Optional[str] = None
    duracion: Optional[str] = None


class EstudioSolicitado(BaseModel):
    """
    Estudio clínico solicitado en el documento.
    """

    tipo: str
    descripcion: str
    prioridad: Optional[str] = None


class ProcedimientoSolicitado(BaseModel):
    """
    Procedimiento clínico solicitado en el documento.
    """

    descripcion: str
    prioridad: Optional[str] = None


class ExtraccionClinica(BaseModel):
    """
    Resultado estructurado generado por el Agente Extractor.

    Contiene únicamente información extraída del documento.
    La clasificación del documento se mantiene en el resultado
    independiente del Agente Clasificador.
    """

    paciente: Paciente

    profesional: Optional[Profesional] = None

    diagnosticos: list[Diagnostico] = Field(
        default_factory=list
    )

    medicamentos: list[Medicamento] = Field(
        default_factory=list
    )

    estudios_solicitados: list[EstudioSolicitado] = Field(
        default_factory=list
    )

    procedimientos_solicitados: list[ProcedimientoSolicitado] = Field(
        default_factory=list
    )

    nivel_urgencia: Optional[NivelUrgencia] = None

    senales_gravedad: list[str] = Field(
        default_factory=list,
        description=(
            "Hallazgos textuales que respaldan el nivel de urgencia "
            "identificado."
        ),
    )

    fecha_documento: Optional[str] = None

    observaciones: Optional[str] = None

    campos_no_encontrados: list[str] = Field(
        default_factory=list,
        description=(
            "Campos esperados que no pudieron extraerse del documento. "
            "Servirán como insumo para la evaluación posterior de "
            "confianza, consistencia y revisión humana."
        ),
    )