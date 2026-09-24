"""
Estado compartido del grafo de MediFlow (LangGraph) — MF-07.

Define la información que viaja entre los nodos durante el procesamiento
de un documento.

Los contratos específicos de entrada, clasificación y extracción se
definen en sus respectivos schemas Pydantic y se almacenan completos
dentro del estado para evitar duplicar estructuras.
"""

from typing import TypedDict

from pydantic import BaseModel, Field

from app.schemas.documento import DocumentoEntrada
from app.schemas.clasificacion import Classification
from app.schemas.extraccion import ExtraccionClinica


class ResultadoValidacion(BaseModel):
    """
    Resultado de la validación estructural realizada al finalizar
    el flujo básico del Sprint 1.
    """

    validacion_ok: bool
    errores_validacion: list[str] = Field(default_factory=list)


class MediFlowState(TypedDict, total=False):
    """
    Estado compartido entre los nodos del grafo de MediFlow.

    total=False permite que el estado se vaya completando progresivamente
    a medida que cada nodo ejecuta su responsabilidad.
    """

    # Documento recibido y preparado por la capa de entrada.
    documento: DocumentoEntrada

    # Resultado generado por el Agente Clasificador.
    clasificacion: Classification

    # Resultado generado por el Agente Extractor.
    extraccion: ExtraccionClinica

    # Resultado de la validación estructural del Sprint 1.
    validacion_ok: bool
    errores_validacion: list[str]