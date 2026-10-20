from enum import Enum

from pydantic import BaseModel, Field


# Tipos de documentos clínicos soportados por MediFlow.
class DocumentType(str, Enum):
    RECETA_MEDICA = "Receta Medica"
    INFORME_ESTUDIO_DIAGNOSTICO = (
        "Informe de Estudio de Diagnostico por Imagenes/Laboratorio"
    )
    ORDEN_SOLICITUD_PROCEDIMIENTO = "Orden de Solicitud de Procedimiento"
    EPICRISIS_INFORME_ALTA = "Epicrisis / Informe de Alta"
    CERTIFICADO_MEDICO = "Certificado Medico"

    # Estado técnico para documentos que no puedan clasificarse
    NO_CLASIFICADO = "No Clasificado"


# Contrato de salida del Agente Clasificador.
# Este resultado será consumido posteriormente por el Agente Extractor
# y por los siguientes nodos del flujo de LangGraph.
class Classification(BaseModel):
    tipo_documento: DocumentType
    especialidad: str
    nivel_prioridad: str
    score_confianza_clasificacion: float = Field(ge=0, le=1)

    # Explicación breve de por qué el documento recibió esta clasificación.
    # Facilita trazabilidad, auditoría y futura revisión humana (HITL).
    justificacion: str