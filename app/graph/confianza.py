"""
app/graph/confianza.py

Nodo de Evaluación de Confianza — MF-10.

Implementa el criterio documentado en docs/MF-10-criterio-confianza.md,
ajustado según la matriz de criticidad por tipo documental propuesta por
Katherine (MF-21): un documento no debe penalizarse por la ausencia de
entidades que no le corresponden a su tipo (ej. un certificado médico no
necesita medicamentos).

DECISIÓN DE DISEÑO (MF-21): la criticidad de una entidad de contenido
(diagnósticos, medicamentos, estudios/procedimientos solicitados) se
determina inspeccionando directamente los ATRIBUTOS REALES del objeto
`extraccion` (ej. `extraccion.medicamentos == []`), NO interpretando los
strings de `campos_no_encontrados`. Esto evita depender de que el LLM o
el extractor nombren los campos de forma consistente (verificado contra
app/agents/extractor.py: solo los 4 campos que calcula por código siguen
una convención fija "entidad.subcampo"/"entidad"; lo que el LLM agregue
por su cuenta no tiene ese contrato garantizado).
 
De las 6 entidades de contenido, solo 2 varían según el tipo de
documento (medicamentos, procedimientos_solicitados); las otras 4
(paciente, profesional, diagnósticos, estudios_solicitados) tienen el
mismo nivel de criticidad en los 5 tipos de la tabla de Katherine, así
que no necesitan matriz: paciente/profesional/diagnósticos son siempre
críticos.
 
Conectado en app/graph/graph.py, en la secuencia:
    ... -> validacion_pydantic -> evaluacion_confianza -> routing_condicional -> END
"""
from app.schemas.state import MediFlowState
from app.schemas.clasificacion import DocumentType

PESO_MODELO = 0.5
PESO_REGLAS = 0.5

UMBRAL_ALTA = 0.80
UMBRAL_MEDIA = 0.50

PENALIZACION_CRITICA = 0.10
PENALIZACION_SECUNDARIA = 0.05
PENALIZACION_MAXIMA_SECUNDARIA = 0.15

PALABRAS_CLAVE_SECUNDARIAS = ("sexo", "fecha", "tipo_documento", "numero_documento")
 
# --- MF-21: matriz de criticidad ---
# Entidades de contenido cuya ausencia se evalúa de forma ESTRUCTURAL
# (atributo real de `extraccion`), no por texto en campos_no_encontrados.
ENTIDADES_LISTA = ("diagnosticos", "medicamentos", "estudios_solicitados", "procedimientos_solicitados")
 
# Entidades que SÍ varían según el tipo de documento (ver docstring).
# diagnosticos no está acá porque es siempre crítico en los 5 tipos.
# estudios_solicitados es crítico específicamente para Informe de Estudio
# (un informe de estudio diagnóstico debe traer los estudios solicitados).
MATRIZ_CRITICIDAD_VARIABLE: dict[DocumentType, set[str]] = {
    DocumentType.RECETA_MEDICA: {"medicamentos"},
    DocumentType.INFORME_ESTUDIO_DIAGNOSTICO: {"estudios_solicitados"},
    DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO: {"procedimientos_solicitados"},
    DocumentType.EPICRISIS_INFORME_ALTA: {"medicamentos"},
    DocumentType.CERTIFICADO_MEDICO: set(),
}
 
ENTIDADES_SIEMPRE_CRITICAS = {"diagnosticos"}  # paciente/profesional se tratan aparte (ver abajo)
ENTIDADES_NUNCA_CRITICAS: set[str] = set()  # ya no queda ninguna fija en "nunca crítico"
 
 
def _entidades_requeridas(tipo_documento) -> set[str]:
    """Para un tipo de documento, qué entidades de ENTIDADES_LISTA son
    críticas si están vacías. Un tipo desconocido (NO_CLASIFICADO o algo
    que no esté en la matriz) trata TODO como crítico, por seguridad."""
    if tipo_documento not in MATRIZ_CRITICIDAD_VARIABLE:
        return set(ENTIDADES_LISTA)
 
    variables_criticas = MATRIZ_CRITICIDAD_VARIABLE[tipo_documento]
    return ENTIDADES_SIEMPRE_CRITICAS | variables_criticas
 
 
def _entidades_lista_faltantes_criticas(extraccion, tipo_documento) -> list[str]:
    """Revisa diagnosticos/medicamentos/estudios_solicitados/
    procedimientos_solicitados directamente como atributos (listas
    vacías = ausentes), y penaliza solo las que son críticas para ESE
    tipo de documento."""
    requeridas = _entidades_requeridas(tipo_documento)
    faltantes = []
    for entidad in ENTIDADES_LISTA:
        if entidad in ENTIDADES_NUNCA_CRITICAS:
            continue
        valor = getattr(extraccion, entidad, None)
        if not valor and entidad in requeridas:
            faltantes.append(entidad)
    return faltantes
 
 
def _profesional_faltante(extraccion) -> bool:
    """profesional es siempre crítico (no varía por tipo). Se revisa
    estructuralmente: el objeto completo ausente, o sin nombre."""
    if extraccion.profesional is None:
        return True
    return not extraccion.profesional.nombre_completo
 
 
def _filtrar_motivos_de_entidades_manejadas_estructuralmente(motivos: list[str]) -> list[str]:
    """Si el extractor o el LLM ya reportaron como texto plano alguna de
    las entidades que ahora evaluamos por atributo real (ej. el string
    suelto "medicamentos" o "profesional" en campos_no_encontrados),
    se descarta de la lista de texto para no penalizar dos veces lo
    mismo: una vez acá y otra en _entidades_lista_faltantes_criticas /
    _profesional_faltante."""
    nombres_manejados_aparte = set(ENTIDADES_LISTA) | {"profesional"}
    return [m for m in motivos if m not in nombres_manejados_aparte]
 
 
def _es_campo_secundario(nombre_campo: str) -> bool:
    nombre = nombre_campo.lower()
    return any(palabra in nombre for palabra in PALABRAS_CLAVE_SECUNDARIAS)
 
 
def _calcular_score_reglas(
    entidades_criticas_faltantes: list[str],
    profesional_faltante: bool,
    campos_faltantes_restantes: list[str],
    otros_motivos: list[str],
) -> float:
    """
    Penaliza:
    - otros_motivos (errores_validacion + inconsistencias MF-09): 0.10 c/u.
    - entidades_criticas_faltantes (diagnosticos/medicamentos/
      procedimientos_solicitados, cuando aplican al tipo): 0.10 c/u.
    - profesional_faltante: 0.10 si aplica (siempre crítico).
    - campos_faltantes_restantes (subcampos puntuales: paciente.*, fecha,
      sexo, tipo/número de documento, etc.): 0.10 si es un campo no
      reconocido como secundario, 0.05 si lo es, con tope de 0.15 para
      el conjunto de secundarios.
    """
    penalizacion_otros = len(otros_motivos) * PENALIZACION_CRITICA
    penalizacion_entidades = len(entidades_criticas_faltantes) * PENALIZACION_CRITICA
    penalizacion_profesional = PENALIZACION_CRITICA if profesional_faltante else 0.0
 
    campos_criticos = [c for c in campos_faltantes_restantes if not _es_campo_secundario(c)]
    campos_secundarios = [c for c in campos_faltantes_restantes if _es_campo_secundario(c)]
 
    penalizacion_campos_criticos = len(campos_criticos) * PENALIZACION_CRITICA
    penalizacion_campos_secundarios = min(
        len(campos_secundarios) * PENALIZACION_SECUNDARIA,
        PENALIZACION_MAXIMA_SECUNDARIA,
    )
 
    penalizacion_total = (
        penalizacion_otros
        + penalizacion_entidades
        + penalizacion_profesional
        + penalizacion_campos_criticos
        + penalizacion_campos_secundarios
    )
    penalizacion_total = min(penalizacion_total, 1.0)
 
    return round(max(0.0, 1.0 - penalizacion_total), 2)
 
 
def _categoria(score: float, tiene_inconsistencias: bool = False) -> str:
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
    el score de confianza final, su categoría y los motivos detrás,
    ahora ajustado por tipo de documento (MF-21).
    """
    clasificacion = state.get("clasificacion")
    extraccion = state.get("extraccion") or state.get("extraction")
 
    score_autoeval = (
        clasificacion.score_confianza_clasificacion if clasificacion is not None else 0.0
    )
    tipo_documento = clasificacion.tipo_documento if clasificacion is not None else None
 
    if extraccion is not None:
        entidades_criticas_faltantes = _entidades_lista_faltantes_criticas(extraccion, tipo_documento)
        profesional_faltante = _profesional_faltante(extraccion)
        campos_no_encontrados_crudos = list(extraccion.campos_no_encontrados)
    else:
        entidades_criticas_faltantes = []
        profesional_faltante = False
        campos_no_encontrados_crudos = []
 
    campos_faltantes_restantes = _filtrar_motivos_de_entidades_manejadas_estructuralmente(
        campos_no_encontrados_crudos
    )
 
    errores_estructurales = list(state.get("errores_validacion", []))
    inconsistencias_mf09 = list(state.get("inconsistencias", []))
    otros_motivos = errores_estructurales + inconsistencias_mf09
 
    score_reglas = _calcular_score_reglas(
        entidades_criticas_faltantes,
        profesional_faltante,
        campos_faltantes_restantes,
        otros_motivos,
    )
 
    score_final = round((score_autoeval * peso_modelo) + (score_reglas * peso_reglas), 2)
 
    # La degradación de categoría (Alta -> Media si hay inconsistencias)
    # debe disparar tanto por errores/inconsistencias (MF-09) como por
    # entidades críticas que el tipo de documento SÍ necesita y no están
    # (ej. una receta sin medicamentos). Un score alto no debe esconder
    # que falta justo el dato que define a ese tipo de documento.
    tiene_inconsistencias = bool(
        otros_motivos or entidades_criticas_faltantes or profesional_faltante
    )
 
    motivos_profesional = ["profesional"] if profesional_faltante else []
    motivos = (
        entidades_criticas_faltantes
        + motivos_profesional
        + campos_faltantes_restantes
        + otros_motivos
    )
 
    return {
        "score_confianza_final": score_final,
        "categoria_confianza": _categoria(score_final, tiene_inconsistencias),
        "motivos_confianza": motivos if motivos else ["Sin inconsistencias detectadas"],
    }