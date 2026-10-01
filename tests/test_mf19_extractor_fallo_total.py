"""
tests/test_mf19_extractor_fallo_total.py

MF-19: si el proveedor principal Y el fallback del EXTRACTOR fallan, el
procesamiento NO debe marcarse como exitoso (validacion_ok=False) y el
motivo debe quedar registrado. Una extraccion incompleta devuelta por un
LLM que SI respondio NO es un fallo tecnico: sigue el flujo normal.
"""

from types import SimpleNamespace

from app.agents import extractor
from app.graph import graph
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.documento import DocumentoEntrada
from app.schemas.extraccion import ExtraccionClinica

DOCUMENTO = DocumentoEntrada(
    documento_id="DOC-TEST-MF19-EXTRACTOR",
    tipo_archivo="JSON",
    canal_origen="test",
    nombre_archivo="ejemplo_receta_medica.txt",
    mime_type="text/plain",
    documento_texto="Documento clinico de prueba.",
)

CLASIFICACION_OK = Classification(
    tipo_documento=DocumentType.RECETA_MEDICA,
    especialidad="Medicina General",
    nivel_prioridad="Rutina",
    score_confianza_clasificacion=0.9,
    justificacion="Documento con datos suficientes para clasificar.",
)


def _preparar(monkeypatch, extraccion):
    monkeypatch.setattr(graph, "_GROQ_API_KEY", None)
    monkeypatch.setattr(graph, "ProveedorGemini", lambda modelo=None: object())
    monkeypatch.setattr(graph, "clasificar_documento", lambda _d, **kw: CLASIFICACION_OK)
    monkeypatch.setattr(graph, "extraer_datos_clinicos", lambda **kw: extraccion)


def test_fallo_total_del_extractor_no_se_marca_como_exito(monkeypatch):
    degradada = extractor._extraccion_vacia(CLASIFICACION_OK, "503 simulado (principal y fallback)")
    _preparar(monkeypatch, degradada)

    resultado = graph.grafo_mediflow.invoke({"documento": DOCUMENTO})

    assert resultado["validacion_ok"] is False
    assert resultado["fallos_tecnicos"]
    assert any(
        "Extractor: fallaron el modelo principal y el fallback" in e
        for e in resultado["errores_validacion"]
    )


def test_extraccion_incompleta_de_un_llm_que_respondio_no_es_fallo_tecnico(monkeypatch):
    incompleta = ExtraccionClinica.model_construct(
        observaciones="El documento esta parcialmente ilegible."
    )
    _preparar(monkeypatch, incompleta)

    resultado = graph.grafo_mediflow.invoke({"documento": DOCUMENTO})

    assert not resultado.get("fallos_tecnicos")
    assert resultado["validacion_ok"] is True


def test_detector_del_grafo_coincide_con_la_salida_degradada_del_extractor():
    """Si alguien cambia el texto de _extraccion_vacia, esto avisa."""
    clasificacion = SimpleNamespace(tipo_documento=DocumentType.RECETA_MEDICA, especialidad="x")
    degradada = extractor._extraccion_vacia(clasificacion, "cualquier motivo")
    assert graph._extraccion_fallo_tecnico_total(degradada) is True
