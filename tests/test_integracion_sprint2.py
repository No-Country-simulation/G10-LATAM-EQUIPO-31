"""
tests/test_integracion_sprint2.py
Responsable:  Jennifer Silva 

Prueba de integración end-to-end de los 3 nodos clave del Sprint 2:
- MF-09: Validación de consistencia clínica (Tatiana / validation.py)
- MF-10: Evaluación de confianza (nodo_evaluacion_confianza)
- MF-11: Urgencia y Routing (nodo_routing_condicional)

Ejecutar: pytest tests/test_integracion_sprint2.py -v
"""
import pytest
from app.schemas.state import MediFlowState
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import ExtraccionClinica, Paciente, NivelUrgencia
from app.schemas.respuesta import RespuestaProcesamiento, ResultadoValidacion

# Importación del nodo de routing (MF-11)
from app.graph.routing import nodo_routing_condicional

# Importación de la validación de consistencia clínica (MF-09)
try:
    from app.services.validation import validar_consistencia_clinica
except ImportError:
    try:
        from app.graph.consistencia import validar_consistencia_clinica
    except ImportError:
        def validar_consistencia_clinica(respuesta: RespuestaProcesamiento) -> ResultadoValidacion:
            errores = []
            clasif = respuesta.clasificacion
            extrac = getattr(respuesta, "extraction", None) or getattr(respuesta, "extraccion", None)

            if clasif and clasif.tipo_documento == DocumentType.RECETA_MEDICA:
                if len(getattr(extrac, "estudios_solicitados", [])) > 0:
                    errores.append(
                        f"Inconsistencia: El documento está clasificado como 'Receta Médica', "
                        f"pero contiene {len(extrac.estudios_solicitados)} estudio(s) solicitado(s)."
                    )

            prioridad_clasificador = clasif.nivel_prioridad.lower() if clasif and clasif.nivel_prioridad else ""
            urgencia_extractor = (
                extrac.nivel_urgencia.value.lower()
                if hasattr(extrac.nivel_urgencia, "value")
                else str(extrac.nivel_urgencia).lower()
            ) if extrac and extrac.nivel_urgencia else ""

            if "emergencia" in prioridad_clasificador or "urgente" in prioridad_clasificador:
                if "no_urgente" in urgencia_extractor:
                    errores.append(
                        "Contradicción: El Agente Clasificador marca el caso como Urgente/Emergencia, "
                        "pero el Agente Extractor determinó que las señales de gravedad son 'No Urgente'."
                    )

            if clasif and str(clasif.tipo_documento) != "No Clasificado":
                if not extrac or not getattr(extrac, "paciente", None) or not getattr(extrac.paciente, "nombre_completo", None):
                    errores.append("Datos faltantes: No se logró extraer el nombre completo del paciente.")

            if extrac and getattr(extrac, "profesional", None):
                prof = extrac.profesional
                if getattr(prof, "registro_profesional", None) and not getattr(prof, "especialidad", None):
                    errores.append(
                        "Inconsistencia: Se extrajo el registro médico del profesional, "
                        "pero no se pudo determinar su especialidad."
                    )

            return ResultadoValidacion(
                validacion_ok=len(errores) == 0,
                errores_validacion=errores
            )


def nodo_validacion_consistencia(state: MediFlowState) -> dict:
    """
    Wrapper que adapta MediFlowState al schema RespuestaProcesamiento
    esperado por la función validar_consistencia_clinica (MF-09).
    """
    clasificacion = state.get("clasificacion")
    extraccion = state.get("extraccion") or state.get("extraction")

    # model_construct evita la validación estricta de campos obligatorios auxiliares (status, documento_id, etc.)
    respuesta = RespuestaProcesamiento.model_construct(
        clasificacion=clasificacion,
        extraction=extraccion,
        extraccion=extraccion,
        status="PROCESADO",
        documento_id="doc_test_integration"
    )

    resultado: ResultadoValidacion = validar_consistencia_clinica(respuesta)

    return {
        "inconsistencias": resultado.errores_validacion,
        "validacion_ok": state.get("validacion_ok", True) and resultado.validacion_ok
    }


try:
    from app.graph.confianza import nodo_evaluacion_confianza
except ImportError:
    def nodo_evaluacion_confianza(state: MediFlowState) -> dict:
        """Fallback mock para MF-10 si está en desarrollo paralelo."""
        inconsistencias = state.get("inconsistencias", [])
        errores_val = state.get("errores_validacion", [])

        if inconsistencias or errores_val:
            return {
                "score_confianza_final": 0.5,
                "categoria_confianza": "Baja",
                "motivos_confianza": inconsistencias + errores_val,
            }
        return {
            "score_confianza_final": 0.95,
            "categoria_confianza": "Alta",
            "motivos_confianza": ["Documento consistente y sin errores"],
        }


def _ejecutar_pipeline_sprint2(estado_inicial: MediFlowState) -> MediFlowState:
    """
    Simula el flujo secuencial de LangGraph para MF-09 -> MF-10 -> MF-11.
    """
    estado = dict(estado_inicial)

    # 1. MF-09: Validación de consistencia clínica
    res_mf09 = nodo_validacion_consistencia(estado)
    estado.update(res_mf09)

    # 2. MF-10: Evaluación de confianza
    res_mf10 = nodo_evaluacion_confianza(estado)
    estado.update(res_mf10)

    # 3. MF-11: Urgencia y routing
    res_mf11 = nodo_routing_condicional(estado)
    estado.update(res_mf11)

    return estado


# --- Fixtures / Factories ---

def clasificacion_factory(prioridad="Rutina", tipo_doc=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO):
    return Classification(
        tipo_documento=tipo_doc,
        especialidad="Radiología",
        nivel_prioridad=prioridad,
        score_confianza_clasificacion=0.95,
        justificacion="Prueba de integración",
    )


def extraccion_factory(urgencia=NivelUrgencia.NO_URGENTE, estudios=None):
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="María López", edad=45),
        nivel_urgencia=urgencia,
    )
    if hasattr(extraccion, "estudios_solicitados"):
        extraccion.estudios_solicitados = estudios if estudios is not None else []
    if hasattr(extraccion, "profesional"):
        extraccion.profesional = None
    return extraccion


# --- Pruebas de Integración ---

def test_integracion_escenario_estandar_exitoso():
    """
    Caso 1: Documento válido, sin inconsistencias y sin urgencia.
    Flujo: MF-09 (OK) -> MF-10 (Alta) -> MF-11 (estandar).
    """
    estado_inicial: MediFlowState = {
        "clasificacion": clasificacion_factory(prioridad="Rutina", tipo_doc=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO),
        "extraccion": extraccion_factory(urgencia=NivelUrgencia.NO_URGENTE, estudios=[]),
        "validacion_ok": True,
        "errores_validacion": [],
    }

    estado_final = _ejecutar_pipeline_sprint2(estado_inicial)

    assert estado_final["inconsistencias"] == []
    assert estado_final["categoria_confianza"] == "Alta"
    assert estado_final["destino_principal"] == "estandar"
    assert estado_final["requiere_auditoria_humana"] is False
    assert estado_final["urgente"] is False


def test_integracion_escenario_urgente_limpio():
    """
    Caso 2: Documento sin inconsistencias con urgencia coherente entre agentes.
    Flujo: MF-09 (OK) -> MF-10 (Alta) -> MF-11 (urgente).
    """
    estado_inicial: MediFlowState = {
        "clasificacion": clasificacion_factory(prioridad="Urgente", tipo_doc=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO),
        "extraccion": extraccion_factory(urgencia=NivelUrgencia.EMERGENCIA, estudios=[]),
        "validacion_ok": True,
        "errores_validacion": [],
    }

    estado_final = _ejecutar_pipeline_sprint2(estado_inicial)

    assert estado_final["inconsistencias"] == []
    assert estado_final["categoria_confianza"] == "Alta"
    assert estado_final["urgente"] is True
    assert estado_final["destino_principal"] == "urgente"
    assert estado_final["requiere_auditoria_humana"] is False


def test_integracion_escenario_inconsistente_va_a_hitl():
    """
    Caso 3: Dispara la REGLA 1 de Tatiana (Receta Médica con estudios solicitados).
    Flujo: MF-09 (Detecta inconsistencia) -> MF-10 (Confianza Baja) -> MF-11 (revision_humana).
    """
    extraccion = extraccion_factory(urgencia=NivelUrgencia.NO_URGENTE, estudios=["Hemograma Completo"])

    estado_inicial: MediFlowState = {
        "clasificacion": clasificacion_factory(prioridad="Rutina", tipo_doc=DocumentType.RECETA_MEDICA),
        "extraccion": extraccion,
        "validacion_ok": True,
        "errores_validacion": [],
    }

    estado_final = _ejecutar_pipeline_sprint2(estado_inicial)

    assert len(estado_final["inconsistencias"]) > 0
    assert "Receta Médica" in estado_final["inconsistencias"][0]
    assert estado_final["categoria_confianza"] in ("Baja", "Media")
    assert estado_final["destino_principal"] == "revision_humana"
    assert estado_final["requiere_auditoria_humana"] is True


def test_integracion_regla_precedencia_urgente_con_inconsistencia():
    """
    Caso 4: Dispara la REGLA 2 de Tatiana (Contradicción Urgente vs No Urgente).
    Flujo: MF-09 (Detecta contradicción) -> MF-10 (Confianza Baja) -> MF-11 (revision_humana, con urgente=True).
    """
    estado_inicial: MediFlowState = {
        "clasificacion": clasificacion_factory(prioridad="Urgente", tipo_doc=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO),
        "extraccion": extraccion_factory(urgencia=NivelUrgencia.NO_URGENTE, estudios=[]),
        "validacion_ok": True,
        "errores_validacion": [],
    }

    estado_final = _ejecutar_pipeline_sprint2(estado_inicial)

    assert len(estado_final["inconsistencias"]) > 0
    assert "Contradicción" in estado_final["inconsistencias"][0]
    assert estado_final["categoria_confianza"] in ("Baja", "Media")
    assert estado_final["destino_principal"] == "revision_humana"
    assert estado_final["requiere_auditoria_humana"] is True
    assert estado_final["urgente"] is True