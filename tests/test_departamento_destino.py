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
    return ExtraccionClinica(paciente=Paciente(nombre_completo="Carlos Mendes", edad=52), nivel_urgencia=nivel_urgencia)


CASOS_ESTANDAR_POR_TIPO = [
    (DocumentType.RECETA_MEDICA, "farmacia_hospitalaria"),
    (DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO, "auditoria_autorizaciones"),
    (DocumentType.EPICRISIS_INFORME_ALTA, "historia_clinica_electronica"),
    (DocumentType.INFORME_ESTUDIO_DIAGNOSTICO, "historia_clinica_electronica"),
    (DocumentType.CERTIFICADO_MEDICO, "historia_clinica_electronica"),
]


def test_departamento_destino_presente_y_correcto_en_rama_estandar():
    for tipo_doc, departamento_esperado in CASOS_ESTANDAR_POR_TIPO:
        state = {
            "clasificacion": _clasificacion(tipo_doc, nivel_prioridad="Rutina"),
            "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.NO_URGENTE),
            "categoria_confianza": "Alta",
        }
        resultado = nodo_routing_condicional(state)
        # El contrato viejo NO cambia:
        assert resultado["destino_principal"] == "estandar"
        # El campo nuevo sí aparece, correcto:
        assert resultado["departamento_destino"] == departamento_esperado


def test_departamento_destino_ausente_cuando_es_urgente():
    """La urgencia no tiene departamento -- todo urgente es la misma cola."""
    state = {
        "clasificacion": _clasificacion(DocumentType.RECETA_MEDICA, nivel_prioridad="Urgente"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.EMERGENCIA),
        "categoria_confianza": "Alta",
    }
    resultado = nodo_routing_condicional(state)
    assert resultado["destino_principal"] == "urgente"
    assert "departamento_destino" not in resultado


def test_departamento_destino_ausente_cuando_es_revision_humana():
    state = {
        "clasificacion": _clasificacion(DocumentType.RECETA_MEDICA, nivel_prioridad="Rutina"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Baja",
    }
    resultado = nodo_routing_condicional(state)
    assert resultado["destino_principal"] == "revision_humana"
    assert "departamento_destino" not in resultado


def test_departamento_destino_ausente_si_tipo_no_mapeado():
    """Tipo NO_CLASIFICADO: estándar sigue funcionando igual que siempre,
    simplemente sin departamento sugerido (Katherine usa solo procesados/estandar/)."""
    state = {
        "clasificacion": _clasificacion(DocumentType.NO_CLASIFICADO, nivel_prioridad="Rutina"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Alta",
    }
    resultado = nodo_routing_condicional(state)
    assert resultado["destino_principal"] == "estandar"  # sin cambios de comportamiento
    assert "departamento_destino" not in resultado