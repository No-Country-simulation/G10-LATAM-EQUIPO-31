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
from langgraph.graph import StateGraph, START, END

from app.schemas.state import MediFlowState, ResultadoValidacion
from app.agents.classifier import clasificar_documento
from app.agents.extractor import extraer_datos_clinicos
from app.services.gemini_provider import ProveedorGemini
from app.schemas.clasificacion import Classification
from app.schemas.extraccion import ExtraccionClinica

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


def nodo_clasificador(state: MediFlowState) -> dict:
    """
    Ejecuta el Agente Clasificador (MF-05) sobre el documento
    almacenado en el estado del grafo.
    """

    documento = state["documento"]

    clasificacion = clasificar_documento(documento)

    return {
        "clasificacion": clasificacion
    }


def nodo_extractor(state: MediFlowState) -> dict:
    """
    Ejecuta el Agente Extractor (MF-06) utilizando el contenido
    del documento y la clasificación generada por el Agente 1.
    """

    documento = state["documento"]
    clasificacion = state["clasificacion"]

    extraccion = extraer_datos_clinicos(
        documento=documento,
        clasificacion=clasificacion,
        proveedor=ProveedorGemini(),
    )

    return {
        "extraccion": extraccion
    }


def nodo_validacion_pydantic(state: MediFlowState) -> dict:
    """
    Verifica que los resultados de clasificación y extracción
    existan y cumplan con sus contratos Pydantic.

    La evaluación clínica de inconsistencias, confianza y decisión
    de HITL pertenece a los siguientes Sprints.
    """

    errores = []

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