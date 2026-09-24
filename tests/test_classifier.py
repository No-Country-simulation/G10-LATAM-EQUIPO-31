"""Pruebas del Agente Clasificador (MF-05).

No llaman a la API real de Gemini: se mockea `generar_salida_estructurada`
para que el equipo pueda correr esto sin una API key configurada.

Adaptado en MF-08 para utilizar los contratos comunes definidos en MF-02.
"""

from __future__ import annotations

import pytest

from app.agents import classifier
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.documento import DocumentoEntrada


def test_clasificar_documento_devuelve_resultado_valido(monkeypatch):
    resultado_simulado = Classification(
        tipo_documento=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO,
        especialidad="Radiologia / Neumologia",
        nivel_prioridad="Urgente",
        score_confianza_clasificacion=0.99,
        justificacion="El texto menciona tomografia y hallazgo de TEP agudo.",
    )

    def _mock_generar(**kwargs):
        assert kwargs["schema"] is Classification
        assert kwargs["api_key_env"] == classifier.API_KEY_ENV
        return resultado_simulado

    monkeypatch.setattr(
        classifier,
        "generar_salida_estructurada",
        _mock_generar,
    )

    documento = DocumentoEntrada(
        documento_id="DOC-TEST-CLASS-001",
        tipo_archivo="JSON",
        canal_origen="test",
        nombre_archivo="informe_radiologico.txt",
        mime_type="text/plain",
        documento_texto=(
            "Informe radiologico. Paciente derivado por sospecha de embolia "
            "pulmonar. Tomografia: hallazgo compatible con TEP agudo."
        ),
    )

    resultado = classifier.clasificar_documento(documento)

    assert resultado.tipo_documento == DocumentType.INFORME_ESTUDIO_DIAGNOSTICO
    assert resultado.score_confianza_clasificacion == pytest.approx(0.99)


def test_classifier_node_acepta_dict_en_el_state(monkeypatch):
    resultado_simulado = Classification(
        tipo_documento=DocumentType.RECETA_MEDICA,
        especialidad="Medicina general",
        nivel_prioridad="Rutina",
        score_confianza_clasificacion=0.87,
        justificacion="El texto lista medicamentos y dosis.",
    )

    monkeypatch.setattr(
        classifier,
        "clasificar_documento",
        lambda _doc: resultado_simulado,
    )

    state = {
        "documento": {
            "documento_id": "DOC-TEST-CLASS-002",
            "tipo_archivo": "JSON",
            "canal_origen": "test",
            "nombre_archivo": "receta.txt",
            "mime_type": "text/plain",
            "documento_texto": "Paracetamol 500mg cada 8 horas por 5 dias.",
        }
    }

    salida = classifier.classifier_node(state)

    assert salida["clasificacion"] is resultado_simulado


def test_documento_entrada_requiere_contenido_o_texto():
    with pytest.raises(ValueError):
        DocumentoEntrada(
            documento_id="DOC-TEST-CLASS-003",
            tipo_archivo="PDF",
            canal_origen="test",
            nombre_archivo="vacio.pdf",
            mime_type="application/pdf",
        )