"""
app/graph/confianza.py

Nodo de Evaluación de Confianza — MF-10.
Responsable: Jennifer Silva

Implementa el criterio documentado en docs/MF-10-criterio-confianza.md:
combina la autoevaluación del modelo (Classification.score_confianza_clasificacion)
con las reglas de completitud (ExtraccionClinica.campos_no_encontrados +
errores_validacion del Sprint 1 + inconsistencias clínicas MF-09).

Aplica ponderación ponderada según criticidad:
- Campos faltantes secundarios (sexo, fecha, documento): penalizan 0.05.
- Campos faltantes críticos (paciente, profesional, diagnóstico, etc.): penalizan 0.10.
- Errores de validación e inconsistencias clínicas: penalizan 0.10 siempre.

Conectado en app/graph/graph.py, en la secuencia:
    ... -> validacion_pydantic -> consistencia -> evaluacion_confianza -> routing -> END
"""
from app.schemas.state import MediFlowState

PESO_MODELO = 0.5
PESO_REGLAS = 0.5

UMBRAL_ALTA = 0.80
UMBRAL_MEDIA = 0.50

PENALIZACION_CRITICA = 0.10
PENALIZACION_SECUNDARIA = 0.05

CAMPOS_SECUNDARIOS = {
    "sexo",
    "fecha",
    "tipo_documento",
    "numero_documento",
    "tipo_doc",
    "numero_doc",
    "documento",
    "fecha_emision",
    "fecha_nacimiento",
}


def _calcular_score_reglas(
    motivos: list[str] = None,
    campos_faltantes: list[str] = None,
    otros_motivos: list[str] = None,
) -> float:
    """
    Calcula el score de reglas aplicando la distinción de pesos:
    - Campos faltantes secundarios (sexo, fecha, doc): penalizan 0.05.
    - Campos faltantes críticos (paciente, profesional, etc.): penalizan 0.10.
    - Errores de validación e inconsistencias clínicas: penalizan 0.10 siempre.
    Ver docs/MF-10-criterio-confianza.md.
    """
    if campos_faltantes is None and otros_motivos is None:
        lista_motivos = motivos or []
        penalizacion = 0.0
        for item in lista_motivos:
            item_lower = item.lower()
            if any(sec in item_lower for sec in CAMPOS_SECUNDARIOS):
                penalizacion += PENALIZACION_SECUNDARIA
            else:
                penalizacion += PENALIZACION_CRITICA
        penalizacion = min(penalizacion, 1.0)
        return round(max(0.0, 1.0 - penalizacion), 2)

    cf = campos_faltantes or []
    om = otros_motivos or []

    penalizacion = 0.0
    for campo in cf:
        campo_lower = campo.lower()
        if any(sec in campo_lower for sec in CAMPOS_SECUNDARIOS):
            penalizacion += PENALIZACION_SECUNDARIA
        else:
            penalizacion += PENALIZACION_CRITICA

    # Errores estructurales e inconsistencias clínicas siempre penalizan 0.10
    penalizacion += len(om) * PENALIZACION_CRITICA

    penalizacion = min(penalizacion, 1.0)
    return round(max(0.0, 1.0 - penalizacion), 2)


def _categoria(score: float, tiene_inconsistencias: bool = False) -> str:
    """
    Determina la categoría de confianza (Alta, Media, Baja).
    Si existen inconsistencias o errores, degrada automáticamente a 'Media' o 'Baja'.
    """
    if tiene_inconsistencias and score >= UMBRAL_ALTA:
        return "Media"
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
    extraccion = state.get("extraccion") or state.get("extraction")

    score_autoeval = (
        clasificacion.score_confianza_clasificacion if clasificacion is not None else 0.0
    )

    campos_faltantes = list(extraccion.campos_no_encontrados) if extraccion is not None else []
    errores_estructurales = list(state.get("errores_validacion", []))
    inconsistencias_mf09 = list(state.get("inconsistencias", []))

    otros_motivos = errores_estructurales + inconsistencias_mf09
    motivos = campos_faltantes + otros_motivos

    score_reglas = _calcular_score_reglas(
        motivos=motivos,
        campos_faltantes=campos_faltantes,
        otros_motivos=otros_motivos,
    )

    score_final = round((score_autoeval * peso_modelo) + (score_reglas * peso_reglas), 2)

    tiene_inconsistencias = bool(errores_estructurales or inconsistencias_mf09)

    return {
        "score_confianza_final": score_final,
        "categoria_confianza": _categoria(score_final, tiene_inconsistencias),
        "motivos_confianza": motivos if motivos else ["Sin inconsistencias detectadas"],
    }