"""Pruebas del Agente Clasificador (MF-05).

No llaman a la API real de Gemini: se mockea `generar_salida_estructurada`
para que el equipo pueda correr esto sin una API key configurada. Para una
prueba end-to-end contra Gemini real, ver samples/probar_clasificador.py.
"""
from __future__ import annotations

import pytest

from app.agents import classifier
from app.schemas.classification import ClassificationResult, TipoDocumento
from app.schemas.document import DocumentoEntrada


def test_clasificar_documento_devuelve_resultado_valido(monkeypatch):
    resultado_simulado = ClassificationResult(
        tipo_documento=TipoDocumento.INFORME_ESTUDIO_DIAGNOSTICO,
        especialidad="Radiologia / Neumologia",
        confianza=0.99,
        justificacion="El texto menciona tomografia y hallazgo de TEP agudo.",
    )

    def _mock_generar(**kwargs):
        assert kwargs["schema"] is ClassificationResult
        assert kwargs["api_key_env"] == classifier.API_KEY_ENV
        return resultado_simulado

    monkeypatch.setattr(classifier, "generar_salida_estructurada", _mock_generar)

    documento = DocumentoEntrada(
        nombre_archivo="informe_radiologico.txt",
        mime_type="text/plain",
        texto=(
            "Informe radiologico. Paciente derivado por sospecha de embolia "
            "pulmonar. Tomografia: hallazgo compatible con TEP agudo."
        ),
    )

    resultado = classifier.clasificar_documento(documento)

    assert resultado.tipo_documento == TipoDocumento.INFORME_ESTUDIO_DIAGNOSTICO
    assert resultado.confianza == pytest.approx(0.99)


def test_classifier_node_acepta_dict_en_el_state(monkeypatch):
    resultado_simulado = ClassificationResult(
        tipo_documento=TipoDocumento.RECETA_MEDICA,
        especialidad="Medicina general",
        confianza=0.87,
        justificacion="El texto lista medicamentos y dosis.",
    )
    monkeypatch.setattr(classifier, "clasificar_documento", lambda _doc: resultado_simulado)

    state = {
        "documento": {
            "nombre_archivo": "receta.txt",
            "mime_type": "text/plain",
            "texto": "Paracetamol 500mg cada 8 horas por 5 dias.",
        }
    }

    salida = classifier.classifier_node(state)

    assert salida["clasificacion"] is resultado_simulado


def test_documento_entrada_requiere_contenido_o_texto():
    with pytest.raises(ValueError):
        DocumentoEntrada(nombre_archivo="vacio.pdf", mime_type="application/pdf")
