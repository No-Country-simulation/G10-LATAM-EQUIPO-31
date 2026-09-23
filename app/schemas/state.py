"""
app/schemas/state.py

Estado del grafo de MediFlow (LangGraph) — MF-07.
Responsable: Jennifer Silva (Automation Specialist) / Apoyo: Kimberlyn Carchi.

Este esquema es el "contrato de datos" que se acuerda con Manuel (Data
Analyst, MF-02): define exactamente qué campos viajan entre nodos, para
que Zahir (app/agents/Clasificador) y Mauricio (app/agents/Extractor)
conecten sus agentes reales sin que el grafo tenga que rediseñarse.

Fuente: ejemplo de salida del brief oficial de MediFlow + los 5 tipos de
documento definidos en el Plan de Trabajo v0.1 (prescripción, informe de
laboratorio/imágenes, orden de procedimiento, epicrisis/resumen de alta,
certificado médico) + el diagrama de arquitectura consolidada del equipo.

NOTA TÉCNICA IMPORTANTE (1):
LangGraph valida este esquema Pydantic solo en la ENTRADA al primer nodo.
Las salidas de nodos intermedios NO se validan automáticamente contra este
modelo, por eso el nodo de validación estructural (Pydantic, en el
diagrama consolidado) existe como paso explícito dentro del grafo, no
como un chequeo redundante.

NOTA TÉCNICA IMPORTANTE (2):
MediFlowState es un TypedDict, no un BaseModel — TypedDict es solo una
anotación de tipos para el editor y para LangGraph; NO tiene defaults en
tiempo de ejecución. Por eso los campos opcionales abajo NO llevan "= None"
ni "= Field(...)": escribir eso no crea ningún valor real, solo sugiere
un comportamiento que no existe y puede esconder un KeyError más adelante.
Cualquier nodo que lea un campo opcional debe usar state.get("campo", default)
en vez de state["campo"], hasta que ese campo haya sido asignado por un
nodo anterior en el flujo.

Este archivo cubre el alcance de Sprint 1 (Clasificador -> Extractor ->
validación básica). Los campos de score de confianza combinado,
enrutamiento y alertas (Sprint 2-3, ver diagrama consolidado) se agregan
en una siguiente iteración de este mismo archivo, no en uno nuevo.
"""
from typing import TypedDict, Optional, List
from pydantic import BaseModel, Field


# --- Modelos Pydantic para validación estricta de contratos ---
class DocumentoEntrada(BaseModel):
    """Esquema de validación para la entrada al API (Duvan, MF-03)."""
    documento_id: str
    tipo_archivo: str  # "PDF" | "Imagen" | "Texto" | "JSON"
    documento_contenido: str
    canal_origen: str


class ResultadoValidacion(BaseModel):
    """Esquema para el resultado de validación estructural (Sprint 1)."""
    validacion_ok: bool
    errores_validacion: List[str] = Field(default_factory=list)


# --- Estado oficial de LangGraph (TypedDict para flujo eficiente) ---
# total=False -> todos los campos son opcionales de estar presentes en el
# diccionario; por eso NINGÚN campo lleva "=" con un valor supuestamente
# "por defecto" (ver NOTA TÉCNICA IMPORTANTE (2) arriba).
class MediFlowState(TypedDict, total=False):
    # --- 1. Entrada (llega desde app/api/ Duvan, MF-03) ---
    documento_id: str
    tipo_archivo: str  # "PDF" | "Imagen" | "Texto" | "JSON"
    documento_contenido: str
    canal_origen: str

    # --- 2. Salida del Agente Clasificador (Zahir, MF-05) ---
    tipo_documento: Optional[str]
    # Uno de los 5 tipos del plan: "Prescripción", "Informe de Laboratorio/Imágenes",
    # "Orden de Procedimiento", "Epicrisis/Resumen de Alta", "Certificado Médico"
    especialidad: Optional[str]
    nivel_prioridad: Optional[str]  # "Urgente" | "Rutina" | "Normal"
    score_confianza_clasificacion: Optional[float]  # 0.0 a 1.0

    # --- 3. Salida del Agente Extractor (Mauricio, MF-06) ---
    # Varía según tipo_documento; por eso casi todos son opcionales.
    paciente_nombre: Optional[str]
    paciente_edad: Optional[int]
    medico_nombre: Optional[str]
    medico_matricula: Optional[str]
    diagnostico_principal: Optional[str]
    cie10_sugerido: Optional[str]
    medicamentos_dosis: Optional[List[str]]       # solo prescripción
    estudio_realizado: Optional[str]               # solo informe laboratorio/imágenes
    estudios_solicitados: Optional[List[str]]       # solo orden de procedimiento

    # --- 4. Validación básica (Sprint 1) ---
    # El score de confianza combinado con inconsistencias (Sprint 2, ver
    # diagrama consolidado) llega en una siguiente iteración de este mismo
    # esquema; esto es solo el chequeo de completitud del Sprint 1.
    # AUSENTE hasta que nodo_validacion_basica lo agregue -> usar .get() al leer.
    errores_validacion: List[str]
    validacion_ok: Optional[bool]