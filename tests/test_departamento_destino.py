"""
tests/test_departamento_destino.py

Pruebas del campo NUEVO departamento_destino adicional al
contrato ya aprobado de destino_principal, que no se modifica.
"""
from app.graph.routing import nodo_routing_condicional
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import ExtraccionClinica, Paciente, NivelUrgencia
 
 
def _clasificacion(tipo_doc, nivel_prioridad="Rutina"):
    return Classification(
        tipo_documento=tipo_doc, especialidad="Medicina General",
        nivel_prioridad=nivel_prioridad, score_confianza_clasificacion=0.9,
        justificacion="Prueba",
    )
 
 
def _extraccion(nivel_urgencia=None):
    return ExtraccionClinica(
        paciente=Paciente(nombre_completo="Carlos Mendes", edad=52),
        nivel_urgencia=nivel_urgencia,
    )
 
 
def test_receta_estandar_va_a_farmacia_hospitalaria():
    state = {
        "clasificacion": _clasificacion(DocumentType.RECETA_MEDICA, "Rutina"),
        "extraccion": _extraccion(NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Alta",
    }
    resultado = nodo_routing_condicional(state)
    assert resultado["destino_principal"] == "estandar"
    assert resultado["departamento_destino"] == "farmacia_hospitalaria"
 
 
def test_orden_procedimiento_estandar_va_a_auditoria_autorizaciones():
    state = {
        "clasificacion": _clasificacion(DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO, "Rutina"),
        "extraccion": _extraccion(NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Alta",
    }
    resultado = nodo_routing_condicional(state)
    assert resultado["destino_principal"] == "estandar"
    assert resultado["departamento_destino"] == "auditoria_autorizaciones"
 
 
def test_epicrisis_informe_estudio_y_certificado_estandar_van_a_hce():
    tipos = [
        DocumentType.EPICRISIS_INFORME_ALTA,
        DocumentType.INFORME_ESTUDIO_DIAGNOSTICO,
        DocumentType.CERTIFICADO_MEDICO,
    ]
    for tipo_doc in tipos:
        state = {
            "clasificacion": _clasificacion(tipo_doc, "Rutina"),
            "extraccion": _extraccion(NivelUrgencia.NO_URGENTE),
            "categoria_confianza": "Alta",
        }
        resultado = nodo_routing_condicional(state)
        assert resultado["destino_principal"] == "estandar"
        assert resultado["departamento_destino"] == "historia_clinica_electronica", f"falló para {tipo_doc}"
 
 
def test_casos_urgentes_de_diferentes_tipos_van_a_cola_de_urgencias_medicas():
    """La urgencia no depende del tipo: los 5 tipos, si son urgentes,
    deben dar el mismo departamento."""
    todos_los_tipos = [
        DocumentType.RECETA_MEDICA,
        DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO,
        DocumentType.EPICRISIS_INFORME_ALTA,
        DocumentType.INFORME_ESTUDIO_DIAGNOSTICO,
        DocumentType.CERTIFICADO_MEDICO,
    ]
    for tipo_doc in todos_los_tipos:
        state = {
            "clasificacion": _clasificacion(tipo_doc, "Urgente"),
            "extraccion": _extraccion(NivelUrgencia.EMERGENCIA),
            "categoria_confianza": "Alta",
        }
        resultado = nodo_routing_condicional(state)
        assert resultado["destino_principal"] == "urgente"
        assert resultado["departamento_destino"] == "cola_urgencias_medicas", f"falló para {tipo_doc}"
 
 
def test_tipo_desconocido_sin_departamento_inferido():
    state = {
        "clasificacion": _clasificacion(DocumentType.NO_CLASIFICADO, "Rutina"),
        "extraccion": _extraccion(NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Alta",
    }
    resultado = nodo_routing_condicional(state)
    assert resultado["destino_principal"] == "estandar"  # sin cambios de comportamiento
    assert "departamento_destino" not in resultado  # no se infiere a ciegas
 
 
def test_destino_principal_conserva_sus_valores_actuales():
    """Confirma explícitamente que los 3 valores de destino_principal
    (estandar/urgente/revision_humana) no cambiaron con MF-23."""
    casos = [
        ({"categoria_confianza": "Alta", "urgente_flag": "Rutina", "nivel_urg": NivelUrgencia.NO_URGENTE}, "estandar"),
        ({"categoria_confianza": "Alta", "urgente_flag": "Urgente", "nivel_urg": NivelUrgencia.EMERGENCIA}, "urgente"),
        ({"categoria_confianza": "Baja", "urgente_flag": "Rutina", "nivel_urg": NivelUrgencia.NO_URGENTE}, "revision_humana"),
    ]
    for datos, destino_esperado in casos:
        state = {
            "clasificacion": _clasificacion(DocumentType.RECETA_MEDICA, datos["urgente_flag"]),
            "extraccion": _extraccion(datos["nivel_urg"]),
            "categoria_confianza": datos["categoria_confianza"],
        }
        resultado = nodo_routing_condicional(state)
        assert resultado["destino_principal"] == destino_esperado
 
 
def test_revision_humana_sin_departamento_fuera_de_alcance_mf23():
    """departamento_destino NO se define para revision_humana en esta
    actividad (fuera de alcance de MF-23, confirmado con Jennifer)."""
    state = {
        "clasificacion": _clasificacion(DocumentType.RECETA_MEDICA, "Rutina"),
        "extraccion": _extraccion(NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Baja",
    }
    resultado = nodo_routing_condicional(state)
    assert resultado["destino_principal"] == "revision_humana"
    assert "departamento_destino" not in resultado
 