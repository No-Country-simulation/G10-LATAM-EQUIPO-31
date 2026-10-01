"""
Estado compartido del grafo de MediFlow (LangGraph) — MF-07.

Define la información que viaja entre los nodos durante el procesamiento
de un documento.

Los contratos específicos de entrada, clasificación y extracción se
definen en sus respectivos schemas Pydantic y se almacenan completos
dentro del estado para evitar duplicar estructuras.
"""

from typing import Any, TypedDict

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

    # MF-19: fallos técnicos NO recuperados (Gemini y el fallback fallaron).
    # Solo existe cuando hubo al menos uno; su presencia impide que la
    # validación marque el procesamiento como exitoso.
    fallos_tecnicos: list[str]

    # MF-15 | Trazabilidad: que proveedor/modelo respondio en cada agente,
    # si hubo fallback y cuantos intentos. Claves: proveedor_usado,
    # modelo_usado, fallback_utilizado, intentos_principal,
    # intentos_fallback. proveedor_usado y modelo_usado son None si
    # fallaron todos los modelos. No cambia los contratos de
    # Classification ni ExtraccionClinica.
    metadata_clasificacion: dict[str, Any]
    metadata_extraccion: dict[str, Any]

    # Resultado de la validación estructural del Sprint 1.
    validacion_ok: bool
    errores_validacion: list[str]

    # --- MF-09: Validación de consistencia ---
    # Lista de mensajes en texto simple, uno por cada inconsistencia
    # detectada (ej. formato de CIE-10 inválido, edad fuera de rango).
    # AUSENTE hasta que nodo_validacion_consistencia lo agregue -> usar .get().
    inconsistencias: list[str]

    # --- MF-10: Evaluación de confianza ---
    # Combina clasificacion.score_confianza_clasificacion (autoevaluación
    # del modelo) con extraccion.campos_no_encontrados + errores_validacion
    # + inconsistencias (reglas de completitud y consistencia),
    # AUSENTES hasta que nodo_evaluacion_confianza los agregue -> usar .get().
    score_confianza_final: float
    categoria_confianza: str  # "Alta" | "Media" | "Baja"
    motivos_confianza: list[str]

    # --- MF-11: Urgencia y routing ---
    # destino_principal se usa directamente como carpeta en OCI (MF-13,
    # Katherine): procesados/{destino_principal}/
    # urgente: señal reconciliada entre clasificacion.nivel_prioridad y
    # extraccion.nivel_urgencia, se conserva incluso si el documento termina en HITL.
    # AUSENTES hasta que nodo_routing_condicional los agregue -> usar .get().
    destino_principal: str  # "estandar" | "urgente" | "revision_humana"
    requiere_auditoria_humana: bool
    urgente: bool  # señal reconciliada; True incluso si destino_principal == "revision_humana"
    justificacion_enrutamiento: str