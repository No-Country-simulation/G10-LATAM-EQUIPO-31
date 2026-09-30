"""
tests/test_routing.py

Pruebas del nodo de Urgencia y Routing — MF-11.
Casos según la condición de cierre del Sprint 3 (Plan v0.2, sección 9),
validados aquí en Sprint 2 para la derivación (el ciclo de revisión en
el panel HITL se completa con MF-12 en Sprint 3).

Ejecutar: pytest tests/test_routing.py -v
"""
from app.graph.routing import nodo_routing_condicional
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import ExtraccionClinica, Paciente, NivelUrgencia


def _clasificacion(nivel_prioridad="Rutina"):
    return Classification(
        tipo_documento=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO,
        especialidad="Radiología",
        nivel_prioridad=nivel_prioridad,
        score_confianza_clasificacion=0.9,
        justificacion="Prueba",
    )


def _extraccion(nivel_urgencia=None):
    return ExtraccionClinica(
        paciente=Paciente(nombre_completo="Carlos Mendes", edad=52),
        nivel_urgencia=nivel_urgencia,
    )


def test_ruta_estandar():
    """Sin urgencia, confianza Alta -> ruta estándar, sin HITL."""
    state = {
        "clasificacion": _clasificacion(nivel_prioridad="Rutina"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Alta",
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["destino_principal"] == "estandar"
    assert resultado["requiere_auditoria_humana"] is False
    assert resultado["urgente"] is False


def test_ruta_urgente():
    """Urgencia detectada, confianza Alta -> cola de emergencia, sin HITL."""
    state = {
        "clasificacion": _clasificacion(nivel_prioridad="Urgente"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.EMERGENCIA),
        "categoria_confianza": "Alta",
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["destino_principal"] == "urgente"
    assert resultado["requiere_auditoria_humana"] is False
    assert resultado["urgente"] is True


def test_ruta_revision_humana_por_baja_confianza():
    """Sin urgencia, pero confianza Baja -> revisión humana."""
    state = {
        "clasificacion": _clasificacion(nivel_prioridad="Rutina"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Baja",
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["destino_principal"] == "revision_humana"
    assert resultado["requiere_auditoria_humana"] is True
    assert resultado["urgente"] is False


def test_precedencia_urgente_con_baja_confianza_va_a_hitl_pero_conserva_urgencia():
    """EL CASO MÁS IMPORTANTE: un documento urgente con confianza Baja NO
    va directo a la cola de emergencia — va a revisión humana, pero la
    señal de urgencia se conserva para que el panel HITL lo priorice."""
    state = {
        "clasificacion": _clasificacion(nivel_prioridad="Urgente"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.EMERGENCIA),
        "categoria_confianza": "Baja",
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["destino_principal"] == "revision_humana"  # la confianza manda la ruta
    assert resultado["requiere_auditoria_humana"] is True
    assert resultado["urgente"] is True  # ...pero la urgencia NO se pierde


def test_precedencia_urgente_con_media_confianza_va_a_hitl_pero_conserva_urgencia():
    """Confianza Media se comporta igual que Baja: requiere revisión humana
    y preserva la urgencia."""
    state = {
        "clasificacion": _clasificacion(nivel_prioridad="Urgente"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.URGENTE),
        "categoria_confianza": "Media",
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["destino_principal"] == "revision_humana"
    assert resultado["requiere_auditoria_humana"] is True
    assert resultado["urgente"] is True


def test_reconciliacion_discrepancia_entre_senales_de_urgencia():
    """Si el Clasificador dice 'Rutina' pero el Extractor detecta
    'emergencia' (o viceversa), el criterio conservador debe ganar:
    se considera urgente si CUALQUIERA de las dos señales lo indica."""
    state = {
        "clasificacion": _clasificacion(nivel_prioridad="Rutina"),  # dice que NO es urgente
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.EMERGENCIA),  # dice que SÍ
        "categoria_confianza": "Alta",
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["urgente"] is True
    assert resultado["destino_principal"] == "urgente"


def test_reconciliacion_discrepancia_clasificador_urgente_extractor_normal():
    """Inverso: Clasificador dice 'Urgente' pero Extractor 'no_urgente' -> Criterio conservador gana."""
    state = {
        "clasificacion": _clasificacion(nivel_prioridad="Urgente"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.NO_URGENTE),
        "categoria_confianza": "Alta",
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["urgente"] is True
    assert resultado["destino_principal"] == "urgente"


def test_categoria_confianza_ausente_usa_default_conservador():
    """Si MF-10 todavía no corrió (categoria_confianza no existe en el
    estado), el routing no debe asumir alta confianza a ciegas."""
    state = {
        "clasificacion": _clasificacion(nivel_prioridad="Rutina"),
        "extraccion": _extraccion(nivel_urgencia=NivelUrgencia.NO_URGENTE),
        # sin categoria_confianza a propósito
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["destino_principal"] == "revision_humana"


def test_manejo_defensivo_con_estado_incompleto_o_none():
    """Verifica que el nodo no falle con AttributeError si los objetos
    del estado vienen como None o diccionarios vacíos."""
    state = {
        "clasificacion": None,
        "extraccion": None,
        "categoria_confianza": "Baja",
    }

    resultado = nodo_routing_condicional(state)

    assert resultado["destino_principal"] == "revision_humana"
    assert resultado["requiere_auditoria_humana"] is True
    assert resultado["urgente"] is False