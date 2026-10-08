"""MF-12: lógica del panel HITL con Streamlit AppTest y datos simulados (sin API, OCI ni LLM)."""
import os

import pytest

pytest.importorskip("streamlit")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


def _mocks():
    import _mocks_panel
    return _mocks_panel


@pytest.fixture
def abrir():
    import sys
    sys.path.insert(0, AQUI)

    def _abrir():
        st.cache_data.clear()
        _mocks().reset()
        at = AppTest.from_file(os.path.join(AQUI, "_harness_panel.py"), default_timeout=60).run()
        assert not at.exception, at.exception
        return at

    return _abrir


def _boton(at, etiqueta):
    return [b for b in at.button if b.label == etiqueta][0]


def _poner_auditor(at, nombre="kimberlyn.r"):
    at.sidebar.text_input(key="auditor").set_value(nombre).run()


def test_muestra_pendientes_resueltos_y_urgentes_primero(abrir):
    at = abrir()
    assert [t.label for t in at.tabs] == ["Pendientes (2)", "Resueltos recientemente"]
    assert at.expander[0].label.startswith("🚨 URGBAJA-001")
    assert at.expander[1].label.startswith("📄 DOC-0417")
    assert any("Confianza media (0.64)" in m.value for m in at.markdown)       # motivos de confianza, tal cual
    filas = [r for df in at.dataframe for r in df.value.to_dict("records")] if at.dataframe else []
    assert any(f.get("Decisión") == "Aprobado" for f in filas) and any(f.get("Decisión") == "Rechazado" for f in filas)


def test_no_hay_manera_de_corregir_datos_clinicos(abrir):
    at = abrir()
    etiquetas = {b.label for b in at.button}
    assert etiquetas == {"🔄 Actualizar bandeja", "✅ Aprobar", "❌ Rechazar"}
    assert not at.radio                                              # sin selector de decisión extra (CORREGIR)
    assert {t.key for t in at.text_input} == {"auditor"}             # ningún campo de texto edita la extracción
    assert not any("orregir" in b.label or "ditar" in b.label for b in at.button)


def test_decidir_exige_nombre_de_auditor(abrir):
    at = abrir()
    _boton(at, "✅ Aprobar").click().run()
    assert any("nombre" in e.value for e in at.error) and not _mocks().LLAMADAS


def test_rechazar_exige_motivo_y_notas(abrir):
    at = abrir()
    _poner_auditor(at)
    _boton(at, "❌ Rechazar").click().run()
    assert any("motivo" in e.value.lower() for e in at.error) and not _mocks().LLAMADAS
    at.selectbox(key="motivo_URGBAJA-001").set_value("INCOMPLETO").run()
    _boton(at, "❌ Rechazar").click().run()
    assert any("notas" in e.value.lower() for e in at.error) and not _mocks().LLAMADAS


def test_rechazar_con_motivo_y_notas_envia_la_decision(abrir):
    at = abrir()
    _poner_auditor(at)
    at.selectbox(key="motivo_URGBAJA-001").set_value("INCOMPLETO").run()
    at.text_area[0].set_value("faltan datos").run()
    _boton(at, "❌ Rechazar").click().run()
    assert _mocks().LLAMADAS == [("decision", "URGBAJA-001", "RECHAZADO", "faltan datos", "kimberlyn.r", "INCOMPLETO")]


def test_aprobar_envia_la_decision_sin_motivo(abrir):
    at = abrir()
    _poner_auditor(at, "ana")
    _boton(at, "✅ Aprobar").click().run()
    assert _mocks().LLAMADAS == [("decision", "URGBAJA-001", "APROBADO", "", "ana", None)]


def test_un_conflicto_avisa_que_otro_auditor_ya_decidio(abrir):
    at = abrir()
    _poner_auditor(at)
    _mocks().ESTADO["conflicto"] = True
    _boton(at, "✅ Aprobar").click().run()
    assert any("ya no está pendiente" in w.value for w in at.warning) and not _mocks().LLAMADAS
