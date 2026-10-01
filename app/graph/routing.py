"""
app/graph/routing.py

Nodo de Urgencia y Routing — MF-11.
Responsable: Jennifer Silva.

Decide el destino final de cada documento, combinando:
- La urgencia clínica (dos señales que hay que reconciliar, ver abajo).
- La categoría de confianza calculada en MF-10 (evaluacion_confianza).

Contrato de salida acordado con Katherine (MF-13, persistencia en OCI):
    destino_principal: "estandar" | "urgente" | "revision_humana"
        -> usado directo como carpeta: procesados/{destino_principal}/
    requiere_auditoria_humana: bool
    urgente: bool -> señal reconciliada, independiente de la ruta final
    justificacion_enrutamiento: str

RECONCILIACIÓN DE LAS DOS SEÑALES DE URGENCIA (decisión de diseño, abierta
a revisión del equipo):
El Clasificador (MF-05) reporta clasificacion.nivel_prioridad (texto
libre: "Urgente" | "Rutina" | "Normal"). El Extractor (MF-06) reporta,
por separado, extraccion.nivel_urgencia (enum: no_urgente | prioritario |
urgente | emergencia). Pueden discrepar. Se adopta un criterio
conservador: si CUALQUIERA de las dos señales indica urgencia, el
documento se considera urgente. Es más seguro sobre-marcar un caso como
urgente (cuesta una revisión de más) que perder uno real.

REGLA DE PRECEDENCIA (obligatoria según el Plan v0.2):
La categoría de confianza manda sobre la urgencia para decidir la RUTA:
un documento urgente con confianza Media o Baja NO va a la cola de
emergencia sin revisar, va a revisión humana, pero CONSERVANDO la señal
de urgencia (campo `urgente`), para que quien lo revise en el panel HITL
sepa que es prioritario.
"""
from typing import Any
from app.schemas.state import MediFlowState

NIVELES_URGENCIA_EXTRACCION = ("urgente", "emergencia")


def _obtener_campo(obj: Any, campo: str) -> Any:
    """Extrae un campo tanto si obj es un objeto Pydantic/clase como si es un diccionario."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(campo)
    return getattr(obj, campo, None)


def _es_urgente(state: MediFlowState) -> bool:
    """Reconcilia clasificacion.nivel_prioridad y extraccion.nivel_urgencia.
    True si cualquiera de las dos señales indica urgencia."""
    clasificacion = state.get("clasificacion")
    extraccion = state.get("extraccion")

    # 1. Evaluación defensiva de la prioridad del Clasificador
    nivel_prioridad = _obtener_campo(clasificacion, "nivel_prioridad")
    prioridad_urgente = (
        nivel_prioridad is not None
        and str(nivel_prioridad).strip().lower() == "urgente"
    )

    # 2. Evaluación defensiva del nivel de urgencia del Extractor (soporta Enum o str)
    nivel_urgencia_raw = _obtener_campo(extraccion, "nivel_urgencia")
    if nivel_urgencia_raw is not None:
        val_urgencia = getattr(nivel_urgencia_raw, "value", nivel_urgencia_raw)
        urgencia_extractor = str(val_urgencia).strip().lower() in NIVELES_URGENCIA_EXTRACCION
    else:
        urgencia_extractor = False

    return prioridad_urgente or urgencia_extractor


def nodo_routing_condicional(state: MediFlowState) -> dict:
    """
    Lee categoria_confianza (MF-10) y la urgencia reconciliada, y decide
    destino_principal según la regla de precedencia: confianza manda sobre
    urgencia para la RUTA, pero la urgencia nunca se pierde.

    Si categoria_confianza todavía no existe en el estado (MF-10 no corrió
    o falló), se asume el caso más conservador ("Baja") para no enrutar
    a ciegas.
    """
    urgente = _es_urgente(state)
    categoria_confianza = state.get("categoria_confianza", "Baja")

    if categoria_confianza in ("Media", "Baja"):
        destino_principal = "revision_humana"
        requiere_auditoria_humana = True
        justificacion = (
            f"Confianza {categoria_confianza}: se deriva a revisión humana "
            f"independientemente de la urgencia (urgente={urgente})."
        )
    elif urgente:
        destino_principal = "urgente"
        requiere_auditoria_humana = False
        justificacion = "Confianza Alta y urgencia detectada: ruta a cola de emergencia."
    else:
        destino_principal = "estandar"
        requiere_auditoria_humana = False
        justificacion = "Confianza Alta y sin señales de urgencia: ruta estándar."

    return {
        "destino_principal": destino_principal,
        "requiere_auditoria_humana": requiere_auditoria_humana,
        "urgente": urgente,
        "justificacion_enrutamiento": justificacion,
    }