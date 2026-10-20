"""
Consulta de resultados del frontend (frontend/consulta_resultados.py y frontend/panel_consulta.py).

La lógica se prueba con eventos de historial; el contrato, contra el backend REAL (POST /documentos, decisiones
HITL y GET /documentos/{id}/historial con OCI simulado, como tests/test_hitl_flujo_integrado.py); y la pantalla
con AppTest y la API simulada.
"""
import os
import sys

import pytest

pytest.importorskip("streamlit")

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "frontend"))

import consulta_resultados as cr  # noqa: E402
import utils_frontend as u  # noqa: E402
from tests.test_hitl_flujo_integrado import entorno  # noqa: E402,F401  (fixture del flujo real)
from utils_frontend import ErrorClienteAPI  # noqa: E402


def _proc(estado="estandar", ts="2026-10-10T10:00:00+00:00", score=0.9, cat="Alta", urgencia="no_urgente", doc="DOC-1", **extra):
    return {
        "documento_id": doc, "estado": estado, "timestamp": ts, "nivel_urgencia": urgencia,
        "resumen": {"categoria_confianza": cat},
        "resultado": {
            "clasificacion": {"tipo_documento": "Receta Medica", "especialidad": "Medicina General",
                              "nivel_prioridad": "Rutina", "score_confianza_clasificacion": 0.95, "justificacion": "Receta."},
            "extraccion": {"paciente": {"nombre_completo": "Laura Martínez", "edad": 45}, "nivel_urgencia": urgencia,
                           "campos_no_encontrados": ["fecha_emision"]},
            "validacion_ok": True, "score_confianza_final": score, "categoria_confianza": cat,
            "motivos_confianza": ["Confianza alta del clasificador"], "justificacion_enrutamiento": "Ruta estándar.",
            **extra,
        },
    }


def _decision(decision="APROBADO", ts="2026-10-10T11:00:00+00:00", **extra):
    return {"tipo_evento": "decision_humana", "documento_id": "DOC-1", "decision": decision,
            "auditor": "kimberlyn.r", "timestamp": ts, **extra}


# --------------------------------------------------------------------------
# Lógica
# --------------------------------------------------------------------------
def test_validar_id_consulta():
    assert cr.validar_id_consulta("DOC-1") is None
    assert "Escriba" in cr.validar_id_consulta("   ")
    assert "largo" in cr.validar_id_consulta("X" * (cr.MAX_LARGO_ID + 1))


def test_resumen_procesado_automaticamente():
    r = cr.resumir_documento([_proc("estandar")])
    assert (r["situacion"], r["decision"], r["procesamientos"]) == ("automatico", None, 1)
    assert r["item"]["tipo_documento"] == "Receta Medica" and r["item"]["score_confianza_final"] == 0.9


def test_resumen_revision_pendiente_resuelta_y_rechazada():
    assert cr.resumir_documento([_proc("revision_humana")])["situacion"] == "pendiente"
    aprobado = cr.resumir_documento([_proc("revision_humana"), _decision("APROBADO")])
    assert aprobado["situacion"] == "resuelto" and aprobado["decision"]["decision"] == "APROBADO"
    rechazado = cr.resumir_documento([_proc("revision_humana"), _decision("RECHAZADO", motivo="INCONSISTENTE")])
    assert rechazado["decision"]["motivo"] == "INCONSISTENTE"


def test_resumen_reprocesado_despues_de_decidir_empieza_de_nuevo():
    eventos = [_proc("revision_humana"), _decision(), _proc("revision_humana", ts="2026-10-10T12:00:00+00:00")]
    r = cr.resumir_documento(eventos)
    assert (r["situacion"], r["decision"], r["procesamientos"]) == ("pendiente", None, 2)   # la decisión vieja no cuenta


def test_resumen_error_tecnico_y_solo_decisiones():
    assert cr.resumir_documento([_proc("error_tecnico")])["situacion"] == "error_tecnico"
    assert cr.resumir_documento([_decision()]) is None


def test_linea_de_tiempo():
    filas = cr.filas_linea_tiempo([_proc("revision_humana", cat="Media"), _decision("RECHAZADO", motivo="INCONSISTENTE", notas="Dosis")])
    assert [f["evento"] for f in filas] == ["Procesamiento", "Decisión humana"]
    assert "revision_humana" in filas[0]["detalle"] and "Media" in filas[0]["detalle"]
    assert "RECHAZADO por kimberlyn.r" in filas[1]["detalle"] and "Dosis" in filas[1]["detalle"]


def test_consultar_documento_usa_la_ruta_del_historial_y_escapa_el_id(monkeypatch):
    llamadas = []
    monkeypatch.setattr(u, "_solicitar", lambda m, ruta, **k: llamadas.append((m, ruta)) or {"eventos": [_proc()]})
    assert cr.consultar_documento("  DOC/1 ")[0]["documento_id"] == "DOC-1"
    assert llamadas == [("GET", "/documentos/DOC%2F1/historial")]


def test_es_no_encontrado():
    assert cr.es_no_encontrado(ErrorClienteAPI("404: Sin historial para 'X'."))
    assert not cr.es_no_encontrado(ErrorClienteAPI("500: boom"))


# --------------------------------------------------------------------------
# Contrato con el backend REAL: lo que el flujo guarda, la consulta lo interpreta bien
# --------------------------------------------------------------------------
def _puente(monkeypatch, client):
    def solicitar(metodo, ruta, **kw):
        r = client.request(metodo, ruta, **kw)
        if r.status_code >= 400:
            raise ErrorClienteAPI(f"{r.status_code}: {r.json().get('detail')}")
        return r.json()
    monkeypatch.setattr(u, "_solicitar", solicitar)


def test_contrato_backend_real_pendiente_aprobado_automatico_y_no_encontrado(entorno, monkeypatch):
    client, _bucket, procesar = entorno
    _puente(monkeypatch, client)
    procesar("CONS-REV", score=0.40)
    r = cr.resumir_documento(cr.consultar_documento("CONS-REV"))
    assert r["situacion"] == "pendiente" and r["item"]["estado"] == "revision_humana"
    assert r["item"]["tipo_documento"] == "Receta Medica"
    assert r["item"]["extraccion"]["paciente"]["nombre_completo"] == "Laura Martínez Gómez"

    assert client.post("/auditoria/CONS-REV/decision", json={"decision": "APROBADO", "auditor": "kim"}).status_code == 201
    r = cr.resumir_documento(cr.consultar_documento("CONS-REV"))
    assert r["situacion"] == "resuelto" and r["decision"]["auditor"] == "kim"
    assert [f["evento"] for f in cr.filas_linea_tiempo(cr.consultar_documento("CONS-REV"))] == ["Procesamiento", "Decisión humana"]

    procesar("CONS-STD", score=0.95)
    assert cr.resumir_documento(cr.consultar_documento("CONS-STD"))["situacion"] == "automatico"

    with pytest.raises(ErrorClienteAPI) as exc:
        cr.consultar_documento("NO-EXISTE")
    assert cr.es_no_encontrado(exc.value)


# --------------------------------------------------------------------------
# Pantalla (AppTest, API simulada)
# --------------------------------------------------------------------------
def _abrir(precarga=None):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(os.path.join(os.path.dirname(AQUI), "frontend", "panel_consulta.py"), default_timeout=60)
    if precarga:
        at.session_state["ultimo_documento_id"] = precarga
    return at.run()


def _consultar(at, texto):
    at.text_input[0].set_value(texto)
    [b for b in at.button if b.label == "Consultar"][0].click()
    return at.run()


def test_ui_renderiza_y_precarga_el_ultimo_id_enviado():
    at = _abrir()
    assert not at.exception, at.exception
    assert at.text_input[0].value == "" and [s.value for s in at.subheader] == ["Consultar resultado"]
    assert _abrir(precarga="DOC-ENVIADO").text_input[0].value == "DOC-ENVIADO"


def test_ui_documento_pendiente_muestra_resultado_y_linea_de_tiempo(monkeypatch):
    monkeypatch.setattr(u, "_solicitar", lambda m, r, **k: {"eventos": [_proc("revision_humana", score=0.62, cat="Media")]})
    at = _consultar(_abrir(), "DOC-1")
    assert not at.exception, at.exception
    assert any("Pendiente de revisión humana" in w.value for w in at.warning)
    assert any("fecha_emision" in w.value for w in at.warning)                       # campos no encontrados
    assert [m.value for m in at.metric] == ["Auditoría humana", "no_urgente", "0.62 · Media"]
    assert [s.value for s in at.subheader] == ["Consultar resultado", "Documento DOC-1"]
    assert len(at.dataframe) == 2                                                    # datos extraídos + línea de tiempo


def test_ui_documento_rechazado_y_aprobado(monkeypatch):
    monkeypatch.setattr(u, "_solicitar", lambda m, r, **k: {"eventos": [
        _proc("revision_humana"), _decision("RECHAZADO", motivo="INCONSISTENTE", notas="Dosis incompatible")]})
    at = _consultar(_abrir(), "DOC-1")
    assert any("Rechazado" in e.value and "Dosis incompatible" in e.value for e in at.error)
    monkeypatch.setattr(u, "_solicitar", lambda m, r, **k: {"eventos": [_proc("revision_humana"), _decision("APROBADO")]})
    at = _consultar(_abrir(), "DOC-1")
    assert any("Aprobado" in s.value and "kimberlyn.r" in s.value for s in at.success)


def test_ui_no_encontrado_y_error_de_api(monkeypatch):
    def no_existe(m, r, **k):
        raise ErrorClienteAPI("404: Sin historial para 'X'.")
    monkeypatch.setattr(u, "_solicitar", no_existe)
    at = _consultar(_abrir(), "X")
    assert any("No se encontró ningún documento con el ID «X»" in w.value for w in at.warning) and not at.error

    def caida(m, r, **k):
        raise ErrorClienteAPI("No hay conexión con la API en http://localhost:8000.")
    monkeypatch.setattr(u, "_solicitar", caida)
    at = _consultar(_abrir(), "X")
    assert any("No se pudo consultar el documento" in e.value for e in at.error)


def test_ui_id_vacio_no_llama_a_la_api(monkeypatch):
    llamadas = []
    monkeypatch.setattr(u, "_solicitar", lambda *a, **k: llamadas.append(a) or {"eventos": []})
    at = _consultar(_abrir(), "   ")
    assert any("Escriba el ID" in e.value for e in at.error) and llamadas == []


# --------------------------------------------------------------------------
# Avisos repetidos y zona horaria (observaciones de la prueba con OCI y Gemini)
# --------------------------------------------------------------------------
REPETIDO = "El documento es una 'Receta Medica' pero incluye estudios complejos."


def test_avisos_sin_repetir_muestra_una_sola_vez_el_mismo_texto():
    item = cr.resumir_documento([_proc("revision_humana", motivos_confianza=[REPETIDO, REPETIDO],
                                       inconsistencias=[REPETIDO, "Dosis fuera de rango"])])["item"]
    motivos, advertencias = cr.avisos_sin_repetir(item)
    assert motivos == [REPETIDO]
    assert advertencias == ["Dosis fuera de rango"]       # la inconsistencia repetida ya salió como motivo


def test_ui_aviso_repetido_aparece_una_sola_vez_y_se_indica_la_zona_horaria(monkeypatch):
    monkeypatch.setattr(u, "_solicitar", lambda m, r, **k: {"eventos": [
        _proc("revision_humana", motivos_confianza=[REPETIDO], inconsistencias=[REPETIDO])]})
    at = _consultar(_abrir(), "DOC-1")
    assert not at.exception, at.exception
    texto = " ".join(m.value for m in at.markdown)
    assert texto.count(REPETIDO) == 1
    assert f"({u.ZONA_HORARIA})" in texto                  # «Procesado: 10/10/2026 05:00 (America/Bogota)»
    assert any(u.ZONA_HORARIA in c.value for c in at.caption)


def _mostrando_documento(at, documento_id):
    return f"Documento {documento_id}" in [s.value for s in at.subheader]


def test_ui_cambiar_el_id_a_mano_oculta_el_resultado_anterior(monkeypatch):
    monkeypatch.setattr(u, "_solicitar", lambda m, r, **k: {"eventos": [_proc("revision_humana", score=0.62, cat="Media")]})
    at = _consultar(_abrir(), "DOC-A")
    assert _mostrando_documento(at, "DOC-A")
    at.text_input[0].set_value("DOC-B").run()                      # se edita el ID, sin pulsar «Consultar»
    assert not _mostrando_documento(at, "DOC-A") and not at.metric and not at.dataframe
    at = _consultar(at, "DOC-B")                                   # y al consultar muestra el nuevo
    assert _mostrando_documento(at, "DOC-B")


def test_ui_id_precargado_tras_un_envio_nuevo_oculta_el_resultado_anterior(monkeypatch):
    monkeypatch.setattr(u, "_solicitar", lambda m, r, **k: {"eventos": [_proc("revision_humana", score=0.62, cat="Media")]})
    at = _consultar(_abrir(precarga="DOC-A"), "DOC-A")
    assert _mostrando_documento(at, "DOC-A")
    at.session_state["ultimo_documento_id"] = "DOC-NUEVO"          # lo que hace la pantalla de carga tras un envío
    at.run()
    assert at.text_input[0].value == "DOC-NUEVO"
    assert not _mostrando_documento(at, "DOC-A") and not at.metric and not at.dataframe


def test_categoria_degradada_a_media_solo_cuando_el_puntaje_alcanza_el_umbral_de_alta():
    assert cr.categoria_degradada_a_media({"score_confianza_final": 0.93, "categoria_confianza": "Media"})
    assert cr.categoria_degradada_a_media({"score_confianza_final": 0.80, "categoria_confianza": "Media"})
    assert not cr.categoria_degradada_a_media({"score_confianza_final": 0.93, "categoria_confianza": "Alta"})
    assert not cr.categoria_degradada_a_media({"score_confianza_final": 0.64, "categoria_confianza": "Media"})
    assert not cr.categoria_degradada_a_media({"score_confianza_final": None, "categoria_confianza": "Media"})


def test_umbral_de_confianza_alta_coincide_con_el_backend():
    """Si el backend cambia el umbral, la explicación de la pantalla dejaría de ser cierta."""
    from app.graph.confianza import UMBRAL_ALTA
    assert cr.UMBRAL_CONFIANZA_ALTA == UMBRAL_ALTA

def _hay_explicacion_de_categoria(at):
    return any("La categoría es Media aunque el puntaje" in c.value for c in at.caption)


def test_ui_explica_por_que_la_categoria_es_media_con_puntaje_alto(monkeypatch):
    monkeypatch.setattr(u, "_solicitar", lambda m, r, **k: {"eventos": [_proc("revision_humana", score=0.93, cat="Media")]})
    at = _consultar(_abrir(), "DOC-1")
    assert not at.exception, at.exception
    assert [m.value for m in at.metric][2] == "0.93 · Media"
    assert _hay_explicacion_de_categoria(at)


def test_ui_no_explica_la_categoria_cuando_no_hubo_degradacion(monkeypatch):
    for score, cat in [(0.93, "Alta"), (0.64, "Media")]:
        monkeypatch.setattr(u, "_solicitar", lambda m, r, s=score, c=cat, **k: {"eventos": [_proc("estandar", score=s, cat=c)]})
        at = _consultar(_abrir(), "DOC-1")
        assert not at.exception, at.exception
        assert not _hay_explicacion_de_categoria(at), (score, cat)