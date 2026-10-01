"""
app/graph/graph.py

Esqueleto del grafo de estado de MediFlow — MF-07, Sprint 1.
Responsable: Jennifer Silva / Apoyo: Kimberlyn Carchi (integración).

Secuencia de este Sprint (según la actividad asignada):
    Inicio -> Clasificador -> Extractor -> Validación Pydantic -> Fin

IMPORTANTE: MediFlowState es un TypedDict (ver app/schemas/state.py), no
tiene defaults en tiempo de ejecución. Por eso todas las lecturas de campos
opcionales usan state.get("campo", default) en vez de state["campo"],
un campo que ningún nodo anterior asignó todavía simplemente NO existe en
el diccionario, y acceder con [] directo lanzaría KeyError.
"""
import os

from langgraph.graph import END, START, StateGraph

from app.agents.classifier import clasificar_documento
from app.agents.extractor import extraer_datos_clinicos
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import ExtraccionClinica
from app.schemas.state import MediFlowState, ResultadoValidacion
from app.services import groq_client
from app.services.gemini_client import DEFAULT_MODEL as _MODELO_GEMINI_CLASIFICADOR
from app.services.gemini_provider import ProveedorGemini

# MF-19 | Fallback tecnico: Gemini sigue siendo el modelo PRINCIPAL en
# los dos agentes, sin cambios. Groq (qwen/qwen3.8-27b) es el proveedor
# SECUNDARIO propuesto por el equipo -- solo se usa si Gemini agota sus
# reintentos por un fallo TECNICO (ver app/agents/classifier.py y
# app/agents/extractor.py).
#
# GROQ_API_KEY vacia = el fallback simplemente no se activa y todo sigue
# funcionando igual que antes de MF-19 (solo reintentos + degradacion
# controlada). Asi, cualquiera puede correr el proyecto sin tener una
# cuenta de Groq. Generar una key gratis en https://console.groq.com/keys
_GROQ_API_KEY = os.getenv("GROQ_API_KEY") or None
_MODELO_CLASIFICADOR_FALLBACK = (
    os.getenv("GROQ_CLASSIFIER_MODEL_FALLBACK") or groq_client.MODELO_GROQ_POR_DEFECTO
)
_MODELO_EXTRACTOR_FALLBACK = (
    os.getenv("GROQ_EXTRACTOR_MODEL_FALLBACK") or groq_client.MODELO_GROQ_POR_DEFECTO
)


class _ProveedorContado:
    """
    MF-15 | Envuelve un proveedor LLM y cuenta cuantas veces se lo invoca
    (cada llamada es un intento), sin cambiar su comportamiento. Los
    demas atributos (modelo, api_key, ...) se delegan al proveedor real.
    """

    def __init__(self, proveedor):
        self._proveedor = proveedor
        self.llamadas = 0

    def generar(self, *args, **kwargs):
        self.llamadas += 1
        return self._proveedor.generar(*args, **kwargs)

    def __getattr__(self, nombre):
        return getattr(self._proveedor, nombre)


def _metadata_llm(origen, intentos_principal, intentos_fallback, modelo_principal, modelo_fallback) -> dict:
    """
    MF-15 | Arma el detalle de trazabilidad de un agente.
    origen: "principal", "fallback" o None (fallaron todos los modelos).
    fallback_utilizado = True si se llego a intentar el fallback, aunque
    tambien haya fallado.
    """
    por_fallback = origen == "fallback"
    return {
        "proveedor_usado": None if origen is None else ("groq" if por_fallback else "gemini"),
        "modelo_usado": None if origen is None else (modelo_fallback if por_fallback else modelo_principal),
        "fallback_utilizado": intentos_fallback > 0,
        "intentos_principal": intentos_principal,
        "intentos_fallback": intentos_fallback,
    }


def _generador_fallback_clasificador(documento, contenido_prompt: str) -> Classification:
    """Adapta `groq_client` a la firma `GeneradorClasificacion` que espera classifier.py."""
    return groq_client.generar_estructurado_con_groq(
        prompt=contenido_prompt,
        contenido_bytes=documento.contenido_bytes,
        mime_type=documento.mime_type,
        schema=Classification,
        modelo=_MODELO_CLASIFICADOR_FALLBACK,
        api_key=_GROQ_API_KEY,
    )

# Campos que la Validación Pydantic exige para considerar el documento
# "completo" al cierre del Sprint 1 (Clasificador + Extractor).
CAMPOS_OBLIGATORIOS_CLASIFICACION = [
    "tipo_documento",
    "especialidad",
    "nivel_prioridad",
    "score_confianza_clasificacion",
]
CAMPOS_OBLIGATORIOS_EXTRACCION = [
    "paciente_nombre",
    "paciente_edad",
    "medico_nombre",
    "medico_matricula",
]


# MF-19 | Prefijo con el que classifier._clasificacion_no_disponible()
# marca la salida degradada cuando Gemini Y el fallback fallaron. Debe
# coincidir con ese texto; tests/test_mf19_fallo_total.py lo verifica.
PREFIJO_CLASIFICACION_NO_DISPONIBLE = "No fue posible clasificar el documento:"


def _clasificacion_fallo_tecnico_total(clasificacion) -> bool:
    """
    True solo si la clasificacion es la salida DEGRADADA por fallo tecnico
    de todos los modelos. Una clasificacion NO_CLASIFICADO con baja
    confianza devuelta por un LLM que SI respondio es un caso funcional
    (ambiguedad) y NO cuenta: sigue por confianza/HITL, no como fallo.
    """
    return (
        isinstance(clasificacion, Classification)
        and clasificacion.tipo_documento == DocumentType.NO_CLASIFICADO
        and clasificacion.score_confianza_clasificacion == 0.0
        and clasificacion.justificacion.startswith(PREFIJO_CLASIFICACION_NO_DISPONIBLE)
    )


# MF-19 | Igual que arriba, para el Extractor: extractor._extraccion_vacia()
# devuelve una extraccion vacia con esta observacion cuando fallaron TODOS
# los proveedores. Se compara solo la parte ASCII del texto (sin tildes)
# para no depender de la codificacion del archivo. Lo verifica
# tests/test_mf19_extractor_fallo_total.py.
PREFIJO_EXTRACCION_NO_DISPONIBLE = "No fue posible obtener una extrac"


def _extraccion_fallo_tecnico_total(extraccion) -> bool:
    """
    True solo si la extraccion es la salida DEGRADADA por fallo tecnico de
    todos los proveedores. Una extraccion incompleta devuelta por un LLM
    que SI respondio (datos faltantes en el documento) NO cuenta: sigue
    por validacion/confianza/HITL, no como fallo tecnico.
    """
    return isinstance(extraccion, ExtraccionClinica) and (
        extraccion.observaciones or ""
    ).startswith(PREFIJO_EXTRACCION_NO_DISPONIBLE)


def nodo_clasificador(state: MediFlowState) -> dict:
    """
    Ejecuta el Agente Clasificador (MF-05) sobre el documento
    almacenado en el estado del grafo.
    """

    documento = state["documento"]

    meta: dict = {}
    clasificacion = clasificar_documento(
        documento,
        generador_fallback=_generador_fallback_clasificador if _GROQ_API_KEY else None,
        metadata=meta,
    )

    resultado = {"clasificacion": clasificacion}

    # MF-15: trazabilidad de que modelo respondio (solo si el agente la informo).
    if meta:
        resultado["metadata_clasificacion"] = _metadata_llm(
            meta.get("origen"),
            meta.get("intentos_principal", 0),
            meta.get("intentos_fallback", 0),
            _MODELO_GEMINI_CLASIFICADOR,
            _MODELO_CLASIFICADOR_FALLBACK,
        )

    # MF-19: si fallaron el principal y el fallback, se deja constancia en
    # el estado para que el procesamiento NO se marque como exitoso.
    if _clasificacion_fallo_tecnico_total(clasificacion):
        resultado["fallos_tecnicos"] = [
            "Clasificador: fallaron el modelo principal y el fallback. "
            + clasificacion.justificacion
        ]

    return resultado


def nodo_extractor(state: MediFlowState) -> dict:
    """
    Ejecuta el Agente Extractor (MF-06) utilizando el contenido
    del documento y la clasificación generada por el Agente 1.
    """

    documento = state["documento"]
    clasificacion = state["clasificacion"]

    # MF-19: sin clasificacion no tiene sentido extraer (y gastaria cuota
    # del Extractor). No se genera extraccion: la validacion lo reporta.
    if state.get("fallos_tecnicos"):
        return {}

    proveedor_principal = _ProveedorContado(ProveedorGemini())
    proveedor_fallback = (
        _ProveedorContado(
            groq_client.ProveedorGroq(api_key=_GROQ_API_KEY, modelo=_MODELO_EXTRACTOR_FALLBACK)
        )
        if _GROQ_API_KEY
        else None
    )

    extraccion = extraer_datos_clinicos(
        documento=documento,
        clasificacion=clasificacion,
        proveedor=proveedor_principal,
        proveedor_fallback=proveedor_fallback,
    )

    resultado = {"extraccion": extraccion}

    # MF-15: trazabilidad de que proveedor respondio (cada llamada = un intento).
    llamadas_fallback = proveedor_fallback.llamadas if proveedor_fallback else 0
    if proveedor_principal.llamadas or llamadas_fallback:
        if _extraccion_fallo_tecnico_total(extraccion):
            origen = None
        else:
            origen = "fallback" if llamadas_fallback else "principal"
        resultado["metadata_extraccion"] = _metadata_llm(
            origen,
            proveedor_principal.llamadas,
            llamadas_fallback,
            getattr(proveedor_principal, "modelo", None),
            _MODELO_EXTRACTOR_FALLBACK,
        )

    # MF-19: si fallaron el principal y el fallback, se deja constancia en
    # el estado para que el procesamiento NO se marque como exitoso.
    if _extraccion_fallo_tecnico_total(extraccion):
        resultado["fallos_tecnicos"] = [
            "Extractor: fallaron el modelo principal y el fallback. "
            + (extraccion.observaciones or "")
        ]

    return resultado


def nodo_validacion_pydantic(state: MediFlowState) -> dict:
    """
    Verifica que los resultados de clasificación y extracción
    existan y cumplan con sus contratos Pydantic.

    La evaluación clínica de inconsistencias, confianza y decisión
    de HITL pertenece a los siguientes Sprints.
    """

    errores = []

    # MF-19: un fallo tecnico total (principal + fallback) nunca es exito.
    errores.extend(state.get("fallos_tecnicos") or [])

    clasificacion = state.get("clasificacion")
    extraccion = state.get("extraccion")

    if clasificacion is None:
        errores.append(
            "No se generó un resultado de clasificación."
        )
    else:
        try:
            Classification.model_validate(clasificacion)
        except Exception as exc:
            errores.append(
                f"Clasificación inválida: {exc}"
            )

    if extraccion is None:
        errores.append(
            "No se generó un resultado de extracción."
        )
    else:
        try:
            ExtraccionClinica.model_validate(extraccion)
        except Exception as exc:
            errores.append(
                f"Extracción inválida: {exc}"
            )

    resultado = ResultadoValidacion(
        validacion_ok=len(errores) == 0,
        errores_validacion=errores,
    )

    return resultado.model_dump()


def construir_grafo():
    """Arma y compila el grafo. Sprint 2 le agregará ramas condicionales
    (score de confianza combinado, urgencia, HITL) después de este nodo,
    tal como muestra el diagrama de arquitectura consolidada."""
    builder = StateGraph(MediFlowState)

    builder.add_node("clasificador", nodo_clasificador)
    builder.add_node("extractor", nodo_extractor)
    builder.add_node("validacion_pydantic", nodo_validacion_pydantic)

    builder.add_edge(START, "clasificador")
    builder.add_edge("clasificador", "extractor")
    builder.add_edge("extractor", "validacion_pydantic")
    builder.add_edge("validacion_pydantic", END)

    return builder.compile()


# Instancia lista para usar desde app/api/ o desde las pruebas locales.
grafo_mediflow = construir_grafo()