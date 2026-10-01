"""Pruebas del Agente Clasificador (MF-05).

No llaman a la API real de Gemini: se mockea `generar_salida_estructurada`
para que el equipo pueda correr esto sin una API key configurada.

Adaptado en MF-08 para utilizar los contratos comunes definidos en MF-02.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents import classifier
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.documento import DocumentoEntrada
from app.services.errores_llm import ErrorTecnicoProveedor


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

# --------------------------------------------------------------------------
# MF-19 | Fallback tecnico del Clasificador
#
# Gemini sigue siendo el modelo PRINCIPAL, sin cambios de MF-05. Estas
# pruebas validan el MECANISMO (reintentos, cambio a generador_fallback
# solo ante un fallo TECNICO, degradacion controlada si ambos fallan, y
# que la ambiguedad/baja confianza -contenido valido- NO dispare nada de
# esto) usando un generador_fallback simulado -- no la integracion real
# con Groq, que tiene su propia suite en tests/test_groq_client.py.
#
# Se usa el contenido de samples/ejemplo_receta_medica.txt (documento
# real del proyecto) como "documento utilizado para la validacion".
# --------------------------------------------------------------------------

_RUTA_SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _documento_de_muestra(nombre_archivo: str) -> DocumentoEntrada:
    texto = (_RUTA_SAMPLES / nombre_archivo).read_text(encoding="utf-8")
    return DocumentoEntrada(
        documento_id=f"DOC-TEST-CLASS-FB-{nombre_archivo}",
        tipo_archivo="JSON",
        canal_origen="test",
        nombre_archivo=nombre_archivo,
        mime_type="text/plain",
        documento_texto=texto,
    )


def _clasificacion_valida(
    tipo: DocumentType = DocumentType.RECETA_MEDICA,
    score: float = 0.9,
) -> Classification:
    return Classification(
        tipo_documento=tipo,
        especialidad="Medicina General",
        nivel_prioridad="Rutina",
        score_confianza_clasificacion=score,
        justificacion="Documento con datos suficientes para clasificar.",
    )


class TestFallbackTecnicoClasificador:
    def test_fallo_tecnico_agota_reintentos_del_principal_antes_del_fallback(self, monkeypatch):
        llamadas = {"principal": 0, "fallback": 0}

        def _mock_gemini(**kwargs):
            llamadas["principal"] += 1
            raise ErrorTecnicoProveedor("503 simulado")

        def _generador_fallback(documento, contenido_prompt):
            llamadas["fallback"] += 1
            return _clasificacion_valida()

        monkeypatch.setattr(classifier, "generar_salida_estructurada", _mock_gemini)

        resultado = classifier.clasificar_documento(
            _documento_de_muestra("ejemplo_receta_medica.txt"),
            generador_fallback=_generador_fallback,
        )

        assert llamadas["principal"] == classifier.MAX_INTENTOS
        assert llamadas["fallback"] == 1
        assert resultado.tipo_documento == DocumentType.RECETA_MEDICA

    def test_sin_generador_fallback_configurado_tambien_reintenta_antes_de_degradar(self, monkeypatch):
        """Refleja el estado sin GROQ_API_KEY configurada: solo reintentos + degradacion."""
        llamadas = {"n": 0}

        def _mock_gemini(**kwargs):
            llamadas["n"] += 1
            raise ErrorTecnicoProveedor("503 simulado")

        monkeypatch.setattr(classifier, "generar_salida_estructurada", _mock_gemini)

        resultado = classifier.clasificar_documento(
            _documento_de_muestra("ejemplo_receta_medica.txt")
        )  # sin generador_fallback

        assert llamadas["n"] == classifier.MAX_INTENTOS
        assert resultado.tipo_documento == DocumentType.NO_CLASIFICADO

    def test_ambos_fallan_no_lanza_excepcion_y_no_se_presenta_como_exito(self, monkeypatch):
        def _mock_gemini(**kwargs):
            raise ErrorTecnicoProveedor("503 simulado")

        def _generador_fallback(documento, contenido_prompt):
            raise ErrorTecnicoProveedor("Groq tambien fallo (simulado)")

        monkeypatch.setattr(classifier, "generar_salida_estructurada", _mock_gemini)

        resultado = classifier.clasificar_documento(
            _documento_de_muestra("ejemplo_receta_medica.txt"),
            generador_fallback=_generador_fallback,
        )

        assert resultado.tipo_documento == DocumentType.NO_CLASIFICADO
        assert resultado.score_confianza_clasificacion == 0.0
        assert "fallo t" in resultado.justificacion.lower()

    def test_baja_confianza_o_ambiguedad_no_dispara_fallback(self, monkeypatch):
        """
        Una clasificacion VALIDA (aunque de baja confianza / ambigua) no es
        un fallo tecnico: se acepta tal cual, sin reintentar ni tocar el
        fallback. Esta es la regla central de MF-19.
        """
        llamadas = {"principal": 0, "fallback": 0}
        ambigua = Classification(
            tipo_documento=DocumentType.NO_CLASIFICADO,
            especialidad="Indeterminada",
            nivel_prioridad="Rutina",
            score_confianza_clasificacion=0.12,
            justificacion="El documento no tiene informacion suficiente para clasificar con certeza.",
        )

        def _mock_gemini(**kwargs):
            llamadas["principal"] += 1
            return ambigua

        def _generador_fallback(documento, contenido_prompt):
            llamadas["fallback"] += 1
            return _clasificacion_valida()

        monkeypatch.setattr(classifier, "generar_salida_estructurada", _mock_gemini)

        resultado = classifier.clasificar_documento(
            _documento_de_muestra("ejemplo_informe_radiologico.txt"),
            generador_fallback=_generador_fallback,
        )

        assert llamadas["principal"] == 1
        assert llamadas["fallback"] == 0
        assert resultado is ambigua

    def test_salida_invalida_reintenta_con_el_mismo_modelo_antes_de_escalar(self, monkeypatch):
        """Gemini que no respeta el schema (ValueError) se trata igual que
        el JSON invalido del Extractor: reintenta con el MISMO modelo
        antes de escalar al fallback."""
        llamadas = {"principal": 0, "fallback": 0}

        def _mock_gemini(**kwargs):
            llamadas["principal"] += 1
            raise ValueError("Gemini no devolvio un JSON valido contra Classification")

        def _generador_fallback(documento, contenido_prompt):
            llamadas["fallback"] += 1
            return _clasificacion_valida()

        monkeypatch.setattr(classifier, "generar_salida_estructurada", _mock_gemini)

        resultado = classifier.clasificar_documento(
            _documento_de_muestra("ejemplo_receta_medica.txt"),
            generador_fallback=_generador_fallback,
        )

        assert llamadas["principal"] == classifier.MAX_INTENTOS
        assert llamadas["fallback"] == 1
        assert resultado.tipo_documento == DocumentType.RECETA_MEDICA

    def test_classifier_node_propaga_generador_fallback(self, monkeypatch):
        capturado = {}

        def _mock_clasificar(documento, generador_fallback=None):
            capturado["generador_fallback"] = generador_fallback
            return _clasificacion_valida()

        marcador = lambda documento, prompt: _clasificacion_valida()
        monkeypatch.setattr(classifier, "clasificar_documento", _mock_clasificar)

        salida = classifier.classifier_node(
            {"documento": _documento_de_muestra("ejemplo_receta_medica.txt")},
            generador_fallback=marcador,
        )

        assert capturado["generador_fallback"] is marcador
        assert salida["clasificacion"].tipo_documento == DocumentType.RECETA_MEDICA
