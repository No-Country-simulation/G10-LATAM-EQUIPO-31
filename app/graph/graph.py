"""
app/graph/graph.py

Esqueleto del grafo de estado de MediFlow — MF-07, Sprint 1.
Responsable: Jennifer Silva / Apoyo: Kimberlyn Carchi (integración).

Secuencia de este Sprint (según la actividad asignada):
    Inicio -> Clasificador -> Extractor -> Validación Pydantic -> Fin

Los nodos `nodo_clasificador` y `nodo_extractor` son PLACEHOLDERS: devuelven
datos simulados para poder probar el recorrido completo del grafo sin
depender de que Zahir y Mauricio ya tengan sus versiones reales listas.
Cuando las tengan, solo reemplazan el CUERPO de estas dos funciones, la
firma (recibe MediFlowState, devuelve dict) y su lugar en el grafo no
cambian.

IMPORTANTE: MediFlowState es un TypedDict (ver app/schemas/state.py), no
tiene defaults en tiempo de ejecución. Por eso todas las lecturas de campos
opcionales usan state.get("campo", default) en vez de state["campo"],
un campo que ningún nodo anterior asignó todavía simplemente NO existe en
el diccionario, y acceder con [] directo lanzaría KeyError.
"""
from langgraph.graph import StateGraph, START, END

from app.schemas.state import MediFlowState, ResultadoValidacion

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
    PLACEHOLDER, Se reemplaza el cuerpo de esta función por la
    llamada real al LLM (Gemini) que clasifica state["documento_contenido"].
    """
    return {
        "tipo_documento": "Informe de Estudio por Imágenes",
        "especialidad": "Radiología / Neumonología",
        "nivel_prioridad": "Urgente",
        "score_confianza_clasificacion": 0.99,
    }


def nodo_extractor(state: MediFlowState) -> dict:
    """
    PLACEHOLDER, Se reemplaza el cuerpo de esta función por la
    extracción real, que además debería variar según
    state.get("tipo_documento") (plantilla distinta por cada uno de los
    5 tipos del plan).
    """
    return {
        "paciente_nombre": "Carlos Eduardo Mendes",
        "paciente_edad": 52,
        "medico_nombre": "Dra. Renata Silveira",
        "medico_matricula": "145892",
        "diagnostico_principal": "Tromboembolismo Pulmonar Agudo (TEP)",
        "cie10_sugerido": "I26.9",
    }


def nodo_validacion_pydantic(state: MediFlowState) -> dict:
    """
    Verifica, usando el modelo Pydantic ResultadoValidacion (definido en
    app/schemas/state.py), que los campos obligatorios de Clasificador y
    Extractor llegaron completos antes de cerrar el resultado del Sprint 1.

    (El score de confianza combinado con detección de inconsistencias —
    Sprint 2, ver diagrama consolidado, se integra como un nodo adicional
    después de este, no lo reemplaza.)
    """
    errores = []
    campos_a_revisar = CAMPOS_OBLIGATORIOS_CLASIFICACION + CAMPOS_OBLIGATORIOS_EXTRACCION

    for campo in campos_a_revisar:
        valor = state.get(campo)
        if valor in (None, ""):
            errores.append(f"Falta el campo obligatorio: {campo}")

    resultado = ResultadoValidacion(
        validacion_ok=(len(errores) == 0),
        errores_validacion=errores,
    )

    # .model_dump() entrega un dict con las mismas claves que MediFlowState
    # espera (errores_validacion, validacion_ok), listo para fusionarse
    # como actualización parcial del estado.
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