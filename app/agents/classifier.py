"""Agente Clasificador (MF-05).

Clasifica un documento clinico en uno de los tipos definidos por el
proyecto y determina la especialidad correspondiente. La salida
(`ClassificationResult`) es el contrato que consume el Agente Extractor
(MF-06, Mauricio) y el grafo de LangGraph (MF-07, Jennifer + Kimberlyn).

Pendiente de coordinar con Manuel (MF-02) para alinear
`ClassificationResult` y `DocumentoEntrada` con los schemas Pydantic
definitivos del proyecto una vez esten listos.

MF-19 | Fallback tecnico: reintentos (hasta MAX_INTENTOS) con el modelo
principal (Gemini, sin cambios), y si se agotan por un fallo TECNICO real
(`ErrorTecnicoProveedor`: 429/cuota, timeout, 5xx, respuesta vacia por
bloqueo), se prueba con `generador_fallback` si se proporciono uno.
`generador_fallback` es una funcion (documento, prompt) -> Classification
-- no un nombre de modelo -- para poder usar cualquier proveedor, no solo
otro modelo de Gemini (ver app/graph/graph.py y app/services/groq_client.py,
donde se conecta Groq/qwen3.8-27b como propuesta del equipo).

Baja confianza, ambiguedad o inconsistencias del contenido NO son un
fallo tecnico y por si solas NUNCA disparan el fallback (eso se evalua
en MF-09/MF-10) -- solo lo dispara `ErrorTecnicoProveedor`.

Si ambos modelos fallan, no se lanza excepcion: se devuelve una
`Classification` degradada (NO_CLASIFICADO, score 0.0, con el motivo en
`justificacion`) para que el flujo la mande a revision humana en vez de
presentarla como un resultado exitoso.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.documento import DocumentoEntrada
from app.services.errores_llm import ErrorTecnicoProveedor
from app.services.gemini_client import DEFAULT_MODEL, generar_salida_estructurada

logger = logging.getLogger("mediflow.app.agents.classifier")

API_KEY_ENV = "GEMINI_CLASSIFIER_API_KEY"
MAX_INTENTOS = 3

# (documento, prompt_ya_construido) -> Classification. Puede lanzar
# ErrorTecnicoProveedor (fallo tecnico) o cualquier otra excepcion
# (problema de contenido); clasificar_documento() maneja ambos casos.
GeneradorClasificacion = Callable[[DocumentoEntrada, str], Classification]

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


def _construir_prompt(documento: DocumentoEntrada) -> str:
    contenido_prompt = f"{_PROMPT_SISTEMA}\n\nDocumento a clasificar ({documento.nombre_archivo}):"
    if documento.documento_texto:
        contenido_prompt += f"\n\n{documento.documento_texto}"
    return contenido_prompt


def _clasificacion_no_disponible(motivo: str) -> Classification:
    """
    Salida degradada cuando se agotan todos los modelos disponibles:
    nunca se lanza excepcion ni se presenta el documento como clasificado
    con exito. `NO_CLASIFICADO` + score 0.0 fuerza que el flujo lo mande
    a revision humana (MF-10/MF-12), igual que `_extraccion_vacia` en el
    Extractor (MF-06).
    """
    return Classification(
        tipo_documento=DocumentType.NO_CLASIFICADO,
        especialidad="No determinada (fallo tecnico del clasificador)",
        nivel_prioridad="Prioritario",
        score_confianza_clasificacion=0.0,
        justificacion=f"No fue posible clasificar el documento: {motivo}",
    )


def _generar_con_gemini(documento: DocumentoEntrada, contenido_prompt: str) -> Classification:
    """Generador del modelo PRINCIPAL (Gemini) -- sin cambios de MF-05."""
    return generar_salida_estructurada(
        api_key_env=API_KEY_ENV,
        prompt=contenido_prompt,
        contenido_bytes=documento.contenido_bytes,
        mime_type=documento.mime_type,
        schema=Classification,
        model=DEFAULT_MODEL,
    )


def _intentar(
    generador: Callable[[], Classification],
    etiqueta: str,
    errores: list[str],
) -> Classification | None:
    """
    Intenta hasta MAX_INTENTOS veces con UN generador (principal o
    fallback). Devuelve el resultado si tiene exito, o None si hay que
    escalar (al fallback, o a la degradacion controlada si no hay mas
    opciones).
    """
    for intento in range(1, MAX_INTENTOS + 1):
        try:
            return generador()
        except ErrorTecnicoProveedor as exc:
            mensaje = f"[{etiqueta}] intento {intento}/{MAX_INTENTOS}: fallo tecnico ({exc})"
            logger.warning(mensaje)
            errores.append(mensaje)
        except Exception as exc:  # noqa: BLE001 - red de seguridad: ninguna excepcion debe escapar del agente
            # Cubre tanto "salida invalida" (el proveedor no respeto el
            # schema) como cualquier error no anticipado. Nunca debe
            # escaparse una excepcion fuera de este modulo.
            mensaje = f"[{etiqueta}] intento {intento}/{MAX_INTENTOS}: {type(exc).__name__}: {exc}"
            logger.warning(mensaje)
            errores.append(mensaje)
    return None


def clasificar_documento(
    documento: DocumentoEntrada,
    generador_fallback: GeneradorClasificacion | None = None,
) -> Classification:
    """
    Ejecuta la clasificacion de un `DocumentoEntrada` via LLM multimodal.

    generador_fallback: funcion (documento, prompt) -> Classification a
        usar si el principal (Gemini) agota sus reintentos por un fallo
        TECNICO. Opcional (default None): sin ella, el clasificador
        sigue funcionando igual que antes de MF-19, solo con reintentos
        + degradacion controlada. Ver app/graph/graph.py para como se
        conecta Groq como fallback real.
    """
    contenido_prompt = _construir_prompt(documento)
    errores: list[str] = []

    resultado = _intentar(lambda: _generar_con_gemini(documento, contenido_prompt), "principal", errores)
    if resultado is not None:
        return resultado

    if generador_fallback is not None:
        logger.warning(
            "Clasificador principal (Gemini/%s) no respondio correctamente; probando el fallback.",
            DEFAULT_MODEL,
        )
        resultado = _intentar(
            lambda: generador_fallback(documento, contenido_prompt), "fallback", errores
        )
        if resultado is not None:
            return resultado
    else:
        logger.warning(
            "No hay generador_fallback configurado para el Clasificador "
            "(falta GROQ_API_KEY en el .env); no se intenta fallback."
        )

    logger.error(
        "Se agotaron todos los modelos disponibles para el Clasificador; "
        "devolviendo clasificacion no disponible."
    )
    return _clasificacion_no_disponible("; ".join(errores))


def classifier_node(
    state: dict[str, Any], generador_fallback: GeneradorClasificacion | None = None
) -> dict[str, Any]:
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

    if generador_fallback is not None:
        clasificacion = clasificar_documento(documento, generador_fallback=generador_fallback)
    else:
        clasificacion = clasificar_documento(documento)
    return {"clasificacion": clasificacion}
