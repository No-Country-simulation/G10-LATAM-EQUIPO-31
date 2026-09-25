"""
tests/test_graph.py

Pruebas del grafo de MediFlow (MF-07 / integración MF-08).

Valida el recorrido:
DocumentoEntrada -> Clasificador -> Extractor -> Validación Pydantic -> Fin.

Los agentes se mockean para que estas pruebas no dependan de Gemini
ni de credenciales externas.
"""

from app.graph import graph
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.documento import DocumentoEntrada
from app.schemas.extraccion import (
    Diagnostico,
    ExtraccionClinica,
    NivelUrgencia,
    Paciente,
    Profesional,
)


DOCUMENTO_PRUEBA = DocumentoEntrada(
    documento_id="DOC-CLIN-2026-8942",
    tipo_archivo="PDF",
    canal_origen="Guardia_Emergencias",
    nombre_archivo="informe_radiologico.pdf",
    mime_type="application/pdf",
    contenido_bytes=b"contenido-pdf-simulado",
)


CLASIFICACION_PRUEBA = Classification(
    tipo_documento=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO,
    especialidad="Radiologia",
    nivel_prioridad="Urgente",
    score_confianza_clasificacion=0.99,
    justificacion="Documento radiologico con hallazgo urgente.",
)


EXTRACCION_PRUEBA = ExtraccionClinica(
    paciente=Paciente(
        nombre_completo="Carlos Eduardo Mendes",
        edad=52,
    ),
    profesional=Profesional(
        nombre_completo="Dra. Renata Silveira",
        registro_profesional="145892",
        especialidad="Radiologia",
    ),
    diagnosticos=[
        Diagnostico(
            descripcion="Tromboembolismo Pulmonar Agudo",
            codigo_cie10="I26.9",
        )
    ],
    nivel_urgencia=NivelUrgencia.URGENTE,
    senales_gravedad=[
        "Cuadro compatible con Tromboembolismo Pulmonar Agudo."
    ],
)


def _configurar_agentes_mock(monkeypatch):
    """Evita llamadas reales a Gemini durante las pruebas del grafo."""

    monkeypatch.setattr(
        graph,
        "clasificar_documento",
        lambda _documento: CLASIFICACION_PRUEBA,
    )

    monkeypatch.setattr(
        graph,
        "extraer_datos_clinicos",
        lambda **kwargs: EXTRACCION_PRUEBA,
    )

    monkeypatch.setattr(
        graph,
        "ProveedorGemini",
        lambda: object(),
    )


def test_grafo_corre_de_punta_a_punta(monkeypatch):
    """El grafo debe recorrer clasificador, extractor y validación."""

    _configurar_agentes_mock(monkeypatch)

    resultado = graph.grafo_mediflow.invoke(
        {"documento": DOCUMENTO_PRUEBA}
    )

    assert resultado["documento"].documento_id == "DOC-CLIN-2026-8942"

    assert (
        resultado["clasificacion"].tipo_documento
        == DocumentType.INFORME_ESTUDIO_DIAGNOSTICO
    )
    assert resultado["clasificacion"].nivel_prioridad == "Urgente"

    assert (
        resultado["extraccion"].paciente.nombre_completo
        == "Carlos Eduardo Mendes"
    )
    assert resultado["extraccion"].diagnosticos[0].codigo_cie10 == "I26.9"


def test_validacion_ok_con_datos_completos(monkeypatch):
    """Con clasificación y extracción válidas no debe haber errores."""

    _configurar_agentes_mock(monkeypatch)

    resultado = graph.grafo_mediflow.invoke(
        {"documento": DOCUMENTO_PRUEBA}
    )

    assert resultado["validacion_ok"] is True
    assert resultado["errores_validacion"] == []


def test_validacion_detecta_clasificacion_faltante():
    """La validación debe detectar que no se ejecutó el clasificador."""

    estado_incompleto = {
        "documento": DOCUMENTO_PRUEBA,
        "extraccion": EXTRACCION_PRUEBA,
    }

    resultado = graph.nodo_validacion_pydantic(estado_incompleto)

    assert resultado["validacion_ok"] is False
    assert "No se generó un resultado de clasificación." in (
        resultado["errores_validacion"]
    )


def test_validacion_detecta_extraccion_faltante():
    """La validación debe detectar que no se ejecutó el extractor."""

    estado_incompleto = {
        "documento": DOCUMENTO_PRUEBA,
        "clasificacion": CLASIFICACION_PRUEBA,
    }

    resultado = graph.nodo_validacion_pydantic(estado_incompleto)

    assert resultado["validacion_ok"] is False
    assert "No se generó un resultado de extracción." in (
        resultado["errores_validacion"]
    )