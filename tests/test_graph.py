"""
tests/test_graph.py

Pruebas del grafo de MediFlow (MF-07 / integración MF-08).

Valida el recorrido:
DocumentoEntrada -> Clasificador -> Extractor -> Validación Pydantic -> Fin.

Los agentes se mockean para que estas pruebas no dependan de Gemini
ni de credenciales externas.
"""

from types import SimpleNamespace

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
        # **kwargs porque nodo_clasificador (MF-19) siempre pasa
        # modelo_fallback=... (puede ser None si no hay fallback
        # configurado en el .env -- ver MODELO_CLASIFICADOR_FALLBACK).
        lambda _documento, **kwargs: CLASIFICACION_PRUEBA,
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


class TestCableadoDelFallbackMF19:
    """
    Gemini sigue siendo el modelo PRINCIPAL en ambos agentes. Groq entra
    como fallback SOLO si `GROQ_API_KEY` esta configurada. Estas pruebas
    validan que el GRAFO conecta (o no) el fallback segun esa variable --
    no hacen ninguna llamada real a Groq.
    """

    def test_sin_groq_api_key_no_se_intenta_fallback(self, monkeypatch):
        """Estado de hoy sin la key: todo sigue igual que antes de MF-19."""
        monkeypatch.setattr(graph, "_GROQ_API_KEY", None)

        capturado = {}

        def clasificador_mock(_documento, **kwargs):
            capturado["clasificador"] = kwargs
            return CLASIFICACION_PRUEBA

        def extractor_mock(**kwargs):
            capturado["extractor"] = kwargs
            return EXTRACCION_PRUEBA

        monkeypatch.setattr(
            graph,
            "clasificar_documento",
            clasificador_mock,
        )
        monkeypatch.setattr(
            graph,
            "extraer_datos_clinicos",
            extractor_mock,
        )
        monkeypatch.setattr(graph, "ProveedorGemini", lambda modelo=None: object())

        graph.grafo_mediflow.invoke({"documento": DOCUMENTO_PRUEBA})

        assert capturado["clasificador"]["generador_fallback"] is None
        assert capturado["extractor"]["proveedor_fallback"] is None

    def test_con_groq_api_key_se_propaga_a_ambos_agentes(self, monkeypatch):
        """Con GROQ_API_KEY configurada, el fallback SI se conecta en los dos agentes."""
        monkeypatch.setattr(graph, "_GROQ_API_KEY", "clave-de-prueba")

        capturado = {}

        def clasificador_mock(_documento, **kwargs):
            capturado["clasificador"] = kwargs
            return CLASIFICACION_PRUEBA

        def extractor_mock(**kwargs):
            capturado["extractor"] = kwargs
            return EXTRACCION_PRUEBA

        monkeypatch.setattr(
            graph,
            "clasificar_documento",
            clasificador_mock,
        )
        monkeypatch.setattr(
            graph,
            "extraer_datos_clinicos",
            extractor_mock,
        )
        monkeypatch.setattr(graph, "ProveedorGemini", lambda modelo=None: object())
        # ProveedorGroq real exige la API key al instanciarse; para esta
        # prueba de cableado basta con no llamar a Groq de verdad.
        monkeypatch.setattr(
            graph.groq_client,
            "ProveedorGroq",
            lambda api_key=None, modelo=None: SimpleNamespace(api_key=api_key, modelo=modelo),
        )

        graph.grafo_mediflow.invoke({"documento": DOCUMENTO_PRUEBA})

        assert capturado["clasificador"]["generador_fallback"] is graph._generador_fallback_clasificador
        assert capturado["extractor"]["proveedor_fallback"].modelo == graph._MODELO_EXTRACTOR_FALLBACK

    def test_el_generador_fallback_del_clasificador_llama_a_groq_con_los_parametros_correctos(
        self, monkeypatch
    ):
        """Prueba el adaptador _generador_fallback_clasificador en si, no solo el cableado."""
        capturado = {}

        def _mock_groq(**kwargs):
            capturado.update(kwargs)
            return CLASIFICACION_PRUEBA

        monkeypatch.setattr(graph.groq_client, "generar_estructurado_con_groq", _mock_groq)
        monkeypatch.setattr(graph, "_GROQ_API_KEY", "clave-de-prueba")

        resultado = graph._generador_fallback_clasificador(DOCUMENTO_PRUEBA, "prompt de prueba")

        assert resultado is CLASIFICACION_PRUEBA
        assert capturado["prompt"] == "prompt de prueba"
        assert capturado["schema"] is Classification
        assert capturado["api_key"] == "clave-de-prueba"
        assert capturado["modelo"] == graph._MODELO_CLASIFICADOR_FALLBACK


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