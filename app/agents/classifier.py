"""Agente Clasificador (MF-05).

Clasifica un documento clinico en uno de los tipos definidos por el
proyecto y determina la especialidad correspondiente. La salida
(`ClassificationResult`) es el contrato que consume el Agente Extractor
(MF-06, Mauricio) y el grafo de LangGraph (MF-07, Jennifer + Kimberlyn).

Pendiente de coordinar con Manuel (MF-02) para alinear
`ClassificationResult` y `DocumentoEntrada` con los schemas Pydantic
definitivos del proyecto una vez esten listos.
"""
from __future__ import annotations

from typing import Any

from app.schemas.classification import ClassificationResult
from app.schemas.document import DocumentoEntrada
from app.services.gemini_client import generar_salida_estructurada

API_KEY_ENV = "GEMINI_CLASSIFIER_API_KEY"

_PROMPT_SISTEMA = """Eres el Agente Clasificador de MediFlow, un sistema de triaje de \
documentos clinicos. Tu unica tarea es identificar el tipo de documento y la \
especialidad clinica asociada, sin extraer datos del paciente todavia.

Tipos de documento validos:
- receta_medica: prescripcion de medicamentos.
- informe_estudio_diagnostico: informe de imagenes (radiografia, tomografia, \
resonancia, ecografia) o de laboratorio.
- orden_solicitud_procedimiento: orden o solicitud de un estudio/procedimiento \
que todavia no se realizo.
- epicrisis_informe_alta: resumen de una hospitalizacion o informe de alta.
- certificado_medico: certificado o constancia medica.
- no_clasificado: usa este valor solo si el documento no encaja claramente en \
ninguna categoria anterior o el contenido es insuficiente.

Responde siempre con una confianza entre 0 y 1, y una justificacion breve \
(1-2 frases) de por que elegiste ese tipo y esa especialidad."""


def clasificar_documento(documento: DocumentoEntrada) -> ClassificationResult:
    """Ejecuta la clasificacion de un `DocumentoEntrada` via LLM multimodal."""
    contenido_prompt = f"{_PROMPT_SISTEMA}\n\nDocumento a clasificar ({documento.nombre_archivo}):"
    if documento.texto:
        contenido_prompt += f"\n\n{documento.texto}"

    resultado = generar_salida_estructurada(
        api_key_env=API_KEY_ENV,
        prompt=contenido_prompt,
        contenido_bytes=documento.contenido_bytes,
        mime_type=documento.mime_type,
        schema=ClassificationResult,
    )
    return resultado


def classifier_node(state: dict[str, Any]) -> dict[str, Any]:
    """Nodo compatible con LangGraph.

    Asume que `state["documento"]` es un `DocumentoEntrada` (o un dict que
    puede convertirse en uno). Devuelve la actualizacion de estado con la
    clasificacion en `state["clasificacion"]`.

    Nota para Kimberlyn/Jennifer (MF-07): las claves del state son una
    propuesta inicial, ajustar segun el state definitivo del grafo.
    """
    documento = state["documento"]
    if isinstance(documento, dict):
        documento = DocumentoEntrada(**documento)

    clasificacion = clasificar_documento(documento)
    return {"clasificacion": clasificacion}
