"""
app/graph/routing.py

Nodo de Urgencia y Routing — MF-11.

Decide el destino final de cada documento, combinando:
- La urgencia clínica (dos señales que hay que reconciliar, ver abajo).
- La categoría de confianza calculada en MF-10 (evaluacion_confianza).

OPCIÓN B (aprobada en Sprint Planning): alineación con los departamentos
que menciona el brief original (Cola de Urgencias Médicas, Auditoría de
Autorizaciones, Farmacia Hospitalaria, Historia Clínica Electrónica) SIN
tocar el contrato de destino_principal ya probado. destino_principal
sigue siendo exactamente "estandar" | "urgente" | "revision_humana",
igual que en develop. Se agrega un campo NUEVO y adicional,
departamento_destino, calculado solo cuando destino_principal ==
"estandar", según el tipo de documento (MF-05).

Contrato de salida (destino_principal/requiere_auditoria_humana/urgente/
justificacion_enrutamiento sin cambios respecto a la versión aprobada):
    destino_principal: "estandar" | "urgente" | "revision_humana"
        -> usado directo como carpeta: procesados/{destino_principal}/
    requiere_auditoria_humana: bool
    urgente: bool -> señal reconciliada, independiente de la ruta final
    justificacion_enrutamiento: str
    departamento_destino: str (NUEVO, opcional)
        -> presente solo si destino_principal == "estandar" y el tipo de
           documento tiene departamento conocido. Katherine puede usarlo
           para una subcarpeta opcional: procesados/estandar/{departamento_destino}/
           AUSENTE en cualquier otro caso (urgente, revision_humana, o
           tipo de documento sin departamento mapeado) -> usar .get().

RECONCILIACIÓN DE LAS DOS SEÑALES DE URGENCIA (sin cambios):
El Clasificador (MF-05) reporta clasificacion.nivel_prioridad (texto
libre: "Urgente" | "Rutina" | "Normal"). El Extractor (MF-06) reporta,
por separado, extraccion.nivel_urgencia (enum: no_urgente | prioritario |
urgente | emergencia). Pueden discrepar. Se adopta un criterio
conservador: si CUALQUIERA de las dos señales indica urgencia, el
documento se considera urgente.

REGLA DE PRECEDENCIA (sin cambios, obligatoria según el Plan v0.2):
La categoría de confianza manda sobre la urgencia para decidir la RUTA:
un documento urgente con confianza Media o Baja NO va a la cola de
emergencia sin revisar va a revisión humana, pero CONSERVANDO la señal
de urgencia (campo `urgente`).

MAPA DE DEPARTAMENTO (solo para destino_principal == "estandar"):
la urgencia es independiente del tipo de documento por eso el
departamento NUNCA se calcula para la rama "urgente" (todo urgente va a
la misma cola de emergencia, sin importar el tipo), ni para
"revision_humana" (un caso dudoso no tiene un departamento claro todavía
hasta que se resuelva). Solo tiene sentido en la rama estándar.
"""
from app.schemas.state import MediFlowState
from app.schemas.clasificacion import DocumentType

NIVELES_URGENCIA_EXTRACCION = ("urgente", "emergencia")

# Departamento sugerido cuando el documento es estándar (confianza Alta,
# sin urgencia), según el tipo de documento (MF-05). Si el tipo no está
# acá (NO_CLASIFICADO u otro no contemplado), simplemente no se agrega
# departamento_destino al resultado. Katherine usa solo
# procesados/estandar/ sin subcarpeta, como hoy.
MAPA_DESTINO_POR_TIPO: dict[DocumentType, str] = {
    DocumentType.RECETA_MEDICA: "farmacia_hospitalaria",
    DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO: "auditoria_autorizaciones",
    DocumentType.EPICRISIS_INFORME_ALTA: "historia_clinica_electronica",
    DocumentType.INFORME_ESTUDIO_DIAGNOSTICO: "historia_clinica_electronica",
    DocumentType.CERTIFICADO_MEDICO: "historia_clinica_electronica",
}


def _es_urgente(state: MediFlowState) -> bool:
    """Reconcilia clasificacion.nivel_prioridad y extraccion.nivel_urgencia.
    True si cualquiera de las dos señales indica urgencia."""
    clasificacion = state.get("clasificacion")
    extraccion = state.get("extraccion")

    prioridad_urgente = (
        clasificacion is not None and clasificacion.nivel_prioridad == "Urgente"
    )

    urgencia_extractor = (
        extraccion is not None
        and extraccion.nivel_urgencia is not None
        and extraccion.nivel_urgencia.value in NIVELES_URGENCIA_EXTRACCION
    )

    return prioridad_urgente or urgencia_extractor


def nodo_routing_condicional(state: MediFlowState) -> dict:
    """
    Lee categoria_confianza (MF-10) y la urgencia reconciliada, y decide
    destino_principal según la regla de precedencia (sin cambios respecto
    a la versión ya aprobada). Además, si el documento cae en la rama
    "estandar", agrega departamento_destino según el tipo de documento
    (MF-05) -- Opción B, campo nuevo y opcional.
    """
    urgente = _es_urgente(state)
    categoria_confianza = state.get("categoria_confianza", "Baja")

    if categoria_confianza in ("Media", "Baja"):
        resultado = {
            "destino_principal": "revision_humana",
            "requiere_auditoria_humana": True,
            "urgente": urgente,
            "justificacion_enrutamiento": (
                f"Confianza {categoria_confianza}: se deriva a revisión humana "
                f"independientemente de la urgencia (urgente={urgente})."
            ),
        }
    elif urgente:
        resultado = {
            "destino_principal": "urgente",
            "requiere_auditoria_humana": False,
            "urgente": urgente,
            "justificacion_enrutamiento": "Confianza Alta y urgencia detectada: ruta a cola de emergencia.",
        }
    else:
        resultado = {
            "destino_principal": "estandar",
            "requiere_auditoria_humana": False,
            "urgente": urgente,
            "justificacion_enrutamiento": "Confianza Alta y sin señales de urgencia: ruta estándar.",
        }

        # Opción B: solo en la rama estándar se agrega el departamento,
        # y solo si el tipo de documento está en el mapa.
        clasificacion = state.get("clasificacion")
        tipo_documento = clasificacion.tipo_documento if clasificacion is not None else None
        if tipo_documento in MAPA_DESTINO_POR_TIPO:
            resultado["departamento_destino"] = MAPA_DESTINO_POR_TIPO[tipo_documento]
            resultado["justificacion_enrutamiento"] += (
                f" Departamento sugerido: {resultado['departamento_destino']}."
            )

    return resultado