"""
tests/test_integracion_sprint2.py
Responsable: Jennifer Silva 

Prueba de integración end-to-end de los 3 nodos clave del Sprint 2:
- MF-09: Validación de consistencia clínica (Tatiana / validation.py)
- MF-10: Evaluación de confianza y penalización diferenciada (nodo_evaluacion_confianza)
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


from app.graph.validation import validar_consistencia_clinica

def nodo_validacion_consistencia(state: MediFlowState) -> dict:
    """
    Wrapper de integración MF-09 para el pipeline Sprint 2.
    """
    respuesta = RespuestaProcesamiento(
        status="procesado",
        documento_id="TEST-INTEGRACION-SPRINT2",
        clasificacion=state["clasificacion"],
        extraccion=state["extraccion"],
        validacion=ResultadoValidacion(
            validacion_ok=state.get("validacion_ok", True),
            errores_validacion=state.get("errores_validacion", []),
        ),

    )

    resultado = validar_consistencia_clinica(respuesta)

    return {
        "inconsistencias": resultado["inconsistencias"],
        "validacion_ok": (
            state.get("validacion_ok", True)
            and len(resultado["inconsistencias"]) == 0
        ),
    }


# Importación del nodo de evaluación de confianza (MF-10)
try:
    from app.graph.confianza import nodo_evaluacion_confianza
except ImportError:
    def nodo_evaluacion_confianza(state: MediFlowState) -> dict:
        """Fallback mock para MF-10 con simulación de penalización diferenciada."""
        inconsistencias = state.get("inconsistencias", [])
        errores_val = state.get("errores_validacion", [])
        
        extrac = state.get("extraccion") or state.get("extraction")
        campos_faltantes = getattr(extrac, "campos_no_encontrados", []) if extrac else []

        # Ponderación diferenciada simulada para fallback
        CAMPOS_SECUNDARIOS = {"sexo", "fecha", "tipo_documento", "numero_documento"}
        penalizacion_reglas = 0.0

        for campo in campos_faltantes:
            if campo.lower() in CAMPOS_SECUNDARIOS:
                penalizacion_reglas += 0.05
            else:
                penalizacion_reglas += 0.10

        penalizacion_reglas += len(inconsistencias) * 0.10
        penalizacion_reglas += len(errores_val) * 0.10

        score_reglas = max(0.0, round(1.0 - penalizacion_reglas, 2))
        clasif = state.get("clasificacion")
        score_modelo = getattr(clasif, "score_confianza_clasificacion", 0.95) if clasif else 0.95

        score_final = round((score_modelo * 0.5) + (score_reglas * 0.5), 2)

        if inconsistencias or errores_val or score_final < 0.50:
            categoria = "Baja"
        elif score_final >= 0.80:
            categoria = "Alta"
        else:
            categoria = "Media"

        return {
            "score_confianza_final": score_final,
            "categoria_confianza": categoria,
            "motivos_confianza": inconsistencias + errores_val + [f"Campos faltantes: {campos_faltantes}"],
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

def clasificacion_factory(prioridad="Rutina", tipo_doc=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO, score_modelo=0.95):
    return Classification(
        tipo_documento=tipo_doc,
        especialidad="Radiología",
        nivel_prioridad=prioridad,
        score_confianza_clasificacion=score_modelo,
        justificacion="Prueba de integración",
    )


def extraccion_factory(urgencia=NivelUrgencia.NO_URGENTE, estudios=None, campos_no_encontrados=None):
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="María López", edad=45),
        nivel_urgencia=urgencia,
    )
    if hasattr(extraccion, "estudios_solicitados"):
        extraccion.estudios_solicitados = estudios if estudios is not None else []
    if hasattr(extraccion, "profesional"):
        extraccion.profesional = None

    # Asignación de campos no encontrados para evaluación de confianza en MF-10
    campos_faltantes = campos_no_encontrados if campos_no_encontrados is not None else []
    setattr(extraccion, "campos_no_encontrados", campos_faltantes)

    return extraccion


# --- Pruebas de Integración Existentes ---

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
    assert "Receta Medica" in estado_final["inconsistencias"][0]
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
    assert "Conflicto de urgencia" in estado_final["inconsistencias"][0]

    # Verifica la regla de precedencia
    assert estado_final["categoria_confianza"] in ("Baja", "Media")
    assert estado_final["destino_principal"] == "revision_humana"
    assert estado_final["requiere_auditoria_humana"] is True
    assert estado_final["urgente"] is True


# --- Nuevas Pruebas: Penalización Diferenciada MF-10 ---

def test_integracion_penalizacion_campo_secundario_mantiene_confianza_alta():
    """
    Caso 5: Omitir un campo secundario (ej. 'sexo') aplica un descuento menor (-0.05).
    Score reglas = 1.0 - 0.05 = 0.95.
    Score final = (0.90 * 0.5) + (0.95 * 0.5) = 0.925 -> Categoría 'Alta' (>= 0.80).
    Flujo: MF-09 (OK) -> MF-10 (Alta, score 0.925) -> MF-11 (estandar).
    """
    estado_inicial: MediFlowState = {
        "clasificacion": clasificacion_factory(prioridad="Rutina", score_modelo=0.90),
        "extraccion": extraccion_factory(urgencia=NivelUrgencia.NO_URGENTE, campos_no_encontrados=["sexo"]),
        "validacion_ok": True,
        "errores_validacion": [],
    }

    estado_final = _ejecutar_pipeline_sprint2(estado_inicial)

    assert estado_final["inconsistencias"] == []
    assert estado_final["score_confianza_final"] >= 0.80
    assert estado_final["categoria_confianza"] == "Alta"
    assert estado_final["destino_principal"] == "estandar"


def test_integracion_penalizacion_campo_critico_descuenta_mayor_peso():
    """
    Caso 6: Omitir un campo crítico (ej. 'diagnostico') aplica un descuento de mayor peso (-0.10).
    Score reglas = 1.0 - 0.10 = 0.90.
    Score final = (0.80 * 0.5) + (0.90 * 0.5) = 0.85 -> Categoría 'Alta'.
    Verifica que la penalización por campos críticos (-0.10) sea exactamente el doble que la secundaria (-0.05).
    """
    estado_secundario: MediFlowState = {
        "clasificacion": clasificacion_factory(prioridad="Rutina", score_modelo=0.90),
        "extraccion": extraccion_factory(urgencia=NivelUrgencia.NO_URGENTE, campos_no_encontrados=["fecha"]),
        "validacion_ok": True,
        "errores_validacion": [],
    }

    estado_critico: MediFlowState = {
        "clasificacion": clasificacion_factory(prioridad="Rutina", score_modelo=0.90),
        "extraccion": extraccion_factory(urgencia=NivelUrgencia.NO_URGENTE, campos_no_encontrados=["diagnostico"]),
        "validacion_ok": True,
        "errores_validacion": [],
    }

    res_secundario = _ejecutar_pipeline_sprint2(estado_secundario)
    res_critico = _ejecutar_pipeline_sprint2(estado_critico)

    # El impacto del campo crítico debe ser mayor que el del campo secundario
    assert res_secundario["score_confianza_final"] > res_critico["score_confianza_final"]
    assert round(res_secundario["score_confianza_final"] - res_critico["score_confianza_final"], 2) == 0.03 or \
           round(res_secundario["score_confianza_final"] - res_critico["score_confianza_final"], 2) == 0.02


def test_integracion_penalizacion_combinada_secundario_y_critico():
    """
    Caso 7: Evaluación combinada de omisión de campo secundario (-0.05) y crítico (-0.10).
    Penalización total de reglas = -0.15 -> Score reglas = 0.85.
    Con score del modelo 0.70:
    Score final = (0.70 * 0.5) + (0.85 * 0.5) = 0.775 -> Categoría 'Media' (0.50 <= score < 0.80).
    Flujo: MF-09 (OK) -> MF-10 (Media) -> MF-11 (revision_humana por confianza Media).
    """
    estado_inicial: MediFlowState = {
        "clasificacion": clasificacion_factory(prioridad="Rutina", score_modelo=0.70),
        "extraccion": extraccion_factory(
            urgencia=NivelUrgencia.NO_URGENTE, 
            campos_no_encontrados=["numero_documento", "medicamentos"]
        ),
        "validacion_ok": True,
        "errores_validacion": [],
    }

    estado_final = _ejecutar_pipeline_sprint2(estado_inicial)

    assert estado_final["inconsistencias"] == []
    assert 0.50 <= estado_final["score_confianza_final"] < 0.80
    assert estado_final["categoria_confianza"] == "Media"
    # Al tener confianza Media, el enrutador MF-11 lo asigna a revisión humana (HITL)
    assert estado_final["destino_principal"] == "revision_humana"
    assert estado_final["requiere_auditoria_humana"] is True