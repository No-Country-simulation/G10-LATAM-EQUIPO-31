"""
app/graph/confianza.py

Nodo de Evaluación de Confianza — MF-10.
Responsable: 

Implementa el criterio documentado en docs/MF-10-criterio-confianza.md:
combina la autoevaluación del modelo (Classification.score_confianza_clasificacion)
con las reglas de completitud (ExtraccionClinica.campos_no_encontrados +
errores_validacion del Sprint 1).

Conectado en app/graph/graph.py, en la secuencia:
    ... -> validacion_pydantic -> evaluacion_confianza -> END

MF-11 (Urgencia y routing) reemplazará "evaluacion_confianza -> END" por
"evaluacion_confianza -> <nodo_routing_condicional>", usando
categoria_confianza y la señal de urgencia (clasificacion.nivel_prioridad
y/o extraccion.nivel_urgencia) para decidir la ruta.
"""
from app.schemas.state import MediFlowState

PESO_MODELO = 0.5
PESO_REGLAS = 0.5

UMBRAL_ALTA = 0.80
UMBRAL_MEDIA = 0.50


def _calcular_score_reglas(motivos: list[str]) -> float:
    """Penaliza 0.1 por cada motivo (campo faltante o error de validación),
    sin bajar de 0.0. Ver docs/MF-10-criterio-confianza.md, sección 4.2."""
    penalizacion = min(0.1 * len(motivos), 1.0)
    return round(max(0.0, 1.0 - penalizacion), 2)


def _categoria(score: float) -> str:
    if score >= UMBRAL_ALTA:
        return "Alta"
    if score >= UMBRAL_MEDIA:
        return "Media"
    return "Baja"


def nodo_evaluacion_confianza(
    state: MediFlowState,
    peso_modelo: float = PESO_MODELO,
    peso_reglas: float = PESO_REGLAS,
) -> dict:
    """
    Lee state["clasificacion"] (Classification) y state["extraccion"]
    (ExtraccionClinica), ya producidos por los nodos anteriores, y calcula
    el score de confianza final, su categoría y los motivos detrás.

    Usa .get() en todo el acceso al estado porque MediFlowState es un
    TypedDict sin defaults en tiempo de ejecución.
    """
    clasificacion = state.get("clasificacion")
    extraccion = state.get("extraccion")

    score_autoeval = (
        clasificacion.score_confianza_clasificacion if clasificacion is not None else 0.0
    )

    campos_faltantes = list(extraccion.campos_no_encontrados) if extraccion is not None else []
    errores_estructurales = list(state.get("errores_validacion", []))
    inconsistencias_mf09 = list(state.get("inconsistencias", []))

    motivos = campos_faltantes + errores_estructurales + inconsistencias_mf09
    score_reglas = _calcular_score_reglas(motivos)

    score_final = round((score_autoeval * peso_modelo) + (score_reglas * peso_reglas), 2)

    return {
        "score_confianza_final": score_final,
        "categoria_confianza": _categoria(score_final),
        "motivos_confianza": motivos if motivos else ["Sin inconsistencias detectadas"],
    }
