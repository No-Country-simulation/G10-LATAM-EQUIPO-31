import pytest
from app.schemas.respuesta import RespuestaProcesamiento
from app.validation import validar_consistencia_clinica, RutaDestino

def test_escenario_1_estandar():
    """Escenario estándar: documento procesado correctamente -> ruta estándar."""
    mock_data = {
        "documento_id": "DOC-12345",
        "status": "procesado",
        "clasificacion": {
            "tipo_documento": "Receta Medica",
            "nivel_prioridad": "No Urgente",
            "justificacion": "Paciente estable en consulta de rutina.",
            "especialidad": "Pediatria",
            "score_confianza_clasificacion": 0.95
        },
        "extraccion": {
            "paciente": {"nombre_completo": "Carlos Gómez"},
            "profesional": {"registro_profesional": "12345", "especialidad": "Pediatría"},
            "estudios_solicitados": [],
            "nivel_urgencia": "no_urgente"
        },
        "validacion": {"validacion_ok": True, "errores_validacion": []}
    }
    mock_respuesta = RespuestaProcesamiento.model_validate(mock_data)
    res = validar_consistencia_clinica(mock_respuesta)
    assert res["validacion_ok"] is True
    assert res["ruta_destino"] == RutaDestino.STANDARD

def test_escenario_2_urgente():
    """Escenario urgente: documento procesado -> urgencia -> cola de emergencia."""
    mock_data = {
        "documento_id": "DOC-67890",
        "status": "procesado",
        "clasificacion": {
            "tipo_documento": "Epicrisis / Informe de Alta",
            "nivel_prioridad": "Urgente",
            "justificacion": "Paciente presenta sintomatología severa.",
            "especialidad": "Cardiologia",
            "score_confianza_clasificacion": 0.92
        },
        "extraccion": {
            "paciente": {"nombre_completo": "Ana Martínez"},
            "profesional": None,
            "estudios_solicitados": [],
            "nivel_urgencia": "urgente"
        },
        "validacion": {"validacion_ok": True, "errores_validacion": []}
    }
    mock_respuesta = RespuestaProcesamiento.model_validate(mock_data)
    res = validar_consistencia_clinica(mock_respuesta)
    assert res["validacion_ok"] is True
    assert res["ruta_destino"] == RutaDestino.EMERGENCY

def test_escenario_3_inconsistente_hitl():
    """Escenario ambiguo/inconsistente: documento procesado -> HITL (revisión humana)."""
    mock_data = {
        "documento_id": "DOC-99999",
        "status": "error_consistencia",
        "clasificacion": {
            "tipo_documento": "Receta Medica",
            "nivel_prioridad": "Emergencia",
            "justificacion": "Solicitud prioritaria.",
            "especialidad": "Neurologia",
            "score_confianza_clasificacion": 0.88
        },
        "extraccion": {
            "paciente": {"nombre_completo": "Luis Pérez"},
            "profesional": None,
            "estudios_solicitados": [{
                "tipo": "Imagenologia",
                "descripcion": "Resonancia Magnetica de cerebro"
            }], 
            "nivel_urgencia": "no_urgente"
        },
        "validacion": {"validacion_ok": False, "errores_validacion": []}
    }
    mock_respuesta = RespuestaProcesamiento.model_validate(mock_data)
    res = validar_consistencia_clinica(mock_respuesta)
    assert res["validacion_ok"] is False
    assert res["ruta_destino"] == RutaDestino.HITL
