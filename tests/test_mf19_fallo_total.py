"""
tests/test_mf19_fallo_total.py

MF-19: si el modelo principal Y el fallback fallan, el procesamiento NO
debe marcarse como exitoso (validacion_ok=False) y el error debe quedar
registrado. Una clasificacion ambigua o de baja confianza devuelta por un
LLM que SI respondio NO es un fallo tecnico: sigue el flujo normal.

Prueba el GRAFO completo (no solo el agente) con los agentes mockeados.
"""

from app.agents import classifier
from app.graph import graph
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.documento import DocumentoEntrada
from app.schemas.extraccion import ExtraccionClinica

DOCUMENTO = DocumentoEntrada(
    documento_id="DOC-TEST-MF19-TOTAL",
    tipo_archivo="JSON",
    canal_origen="test",
    nombre_archivo="ejemplo_receta_medica.txt",
    mime_type="text/plain",
    documento_texto="Documento clinico de prueba.",
)


def _sin_groq(monkeypatch):
    monkeypatch.setattr(graph, "_GROQ_API_KEY", None)
    monkeypatch.setattr(graph, "ProveedorGemini", lambda modelo=None: object())


def test_fallo_total_del_clasificador_no_se_marca_como_exito(monkeypatch, caplog):
    _sin_groq(monkeypatch)
    degradada = classifier._clasificacion_no_disponible("503 simulado (principal y fallback)")
    monkeypatch.setattr(graph, "clasificar_documento", lambda _d, **kw: degradada)

    def _no_debe_llamarse(**kwargs):
        raise AssertionError("El Extractor no debe correr sin clasificacion")

    monkeypatch.setattr(graph, "extraer_datos_clinicos", _no_debe_llamarse)

    resultado = graph.grafo_mediflow.invoke({"documento": DOCUMENTO})

    assert resultado["validacion_ok"] is False
    assert resultado["fallos_tecnicos"]
    assert any("fallaron el modelo principal y el fallback" in e for e in resultado["errores_validacion"])
    assert "extraccion" not in resultado


def test_clasificacion_ambigua_de_un_llm_que_respondio_no_es_fallo_tecnico(monkeypatch):
    _sin_groq(monkeypatch)
    ambigua = Classification(
        tipo_documento=DocumentType.NO_CLASIFICADO,
        especialidad="Indeterminada",
        nivel_prioridad="Rutina",
        score_confianza_clasificacion=0.0,
        justificacion="El documento no tiene informacion suficiente para clasificar.",
    )
    llamadas = {"extractor": 0}

    def _extractor(**kwargs):
        llamadas["extractor"] += 1
        return ExtraccionClinica.model_construct()

    monkeypatch.setattr(graph, "clasificar_documento", lambda _d, **kw: ambigua)
    monkeypatch.setattr(graph, "extraer_datos_clinicos", _extractor)

    resultado = graph.grafo_mediflow.invoke({"documento": DOCUMENTO})

    assert not resultado.get("fallos_tecnicos")
    assert llamadas["extractor"] == 1  # el flujo sigue: es asunto de confianza/HITL


def test_detector_del_grafo_coincide_con_la_salida_degradada_del_clasificador():
    """Si alguien cambia el texto de _clasificacion_no_disponible, esto avisa."""
    degradada = classifier._clasificacion_no_disponible("cualquier motivo")
    assert graph._clasificacion_fallo_tecnico_total(degradada) is True
