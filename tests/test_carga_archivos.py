"""
Carga de archivos del frontend (frontend/carga_archivos.py y frontend/panel_carga.py).

Sin API real, OCI ni LLM: la validación es lógica pura, el cliente HTTP se simula y el contrato con el
backend se prueba contra el router real de FastAPI con los agentes y OCI reemplazados (mismo patrón que
tests/test_routes.py).
"""
import json
import os
import sys

import pytest

pytest.importorskip("streamlit")
import requests  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "frontend"))
sys.path.insert(0, AQUI)

import carga_archivos as ca  # noqa: E402
from utils_frontend import ErrorClienteAPI  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PDF = b"%PDF-1.7\n%resto del pdf"


# --------------------------------------------------------------------------
# Validación del archivo
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "nombre, contenido, formato, mime",
    [
        ("receta.jpg", JPG, "JPG", "image/jpeg"),
        ("receta.JPEG", JPG, "JPG", "image/jpeg"),
        ("estudio.png", PNG, "PNG", "image/png"),
        ("orden.pdf", PDF, "PDF", "application/pdf"),
        ("datos.json", b'{"paciente": "Ana"}', "JSON", "text/plain"),
        ("nota.md", "# Informe\ncafé".encode("utf-8"), "Markdown", "text/plain"),
        ("nota.markdown", b"# Informe", "Markdown", "text/plain"),
        ("con_bom.json", b'\xef\xbb\xbf{"a": 1}', "JSON", "text/plain"),
    ],
)
def test_formatos_validos(nombre, contenido, formato, mime):
    v = ca.validar_archivo(nombre, contenido)
    assert v.ok and v.error is None
    assert (v.formato, v.mime) == (formato, mime)


@pytest.mark.parametrize("nombre", ["informe.docx", "hoja.xlsx", "nota.txt", "foto.gif", "ruta.exe", "sinextension", "archivo."])
def test_formato_no_valido_lista_los_formatos_permitidos(nombre):
    v = ca.validar_archivo(nombre, b"contenido")
    assert not v.ok
    assert "no válido" in v.error
    for permitido in ("JPG", "PNG", "PDF", "JSON", "Markdown"):
        assert permitido in v.error


def test_archivo_vacio():
    v = ca.validar_archivo("vacio.pdf", b"")
    assert not v.ok and "vacío" in v.error


def test_supera_el_tamano_maximo():
    v = ca.validar_archivo("grande.pdf", PDF + b"0" * (2 * 1024 * 1024), max_mb=1)
    assert not v.ok and "1 MB" in v.error


@pytest.mark.parametrize("nombre", ["falso.pdf", "falso.png", "falso.jpg"])
def test_extension_que_no_coincide_con_el_contenido(nombre):
    v = ca.validar_archivo(nombre, b"esto es texto plano renombrado")
    assert not v.ok and "no coincide" in v.error


def test_json_invalido_indica_la_posicion():
    v = ca.validar_archivo("roto.json", b'{"a": }')
    assert not v.ok and "JSON válido" in v.error and "línea 1" in v.error


def test_texto_que_no_es_utf8():
    v = ca.validar_archivo("latin.md", "información".encode("latin-1"))
    assert not v.ok and "UTF-8" in v.error


def test_markdown_solo_espacios():
    v = ca.validar_archivo("blanco.md", b"  \n \n")
    assert not v.ok and "no tiene contenido" in v.error


def test_las_muestras_del_proyecto_son_validas():
    entradas = os.path.join(os.path.dirname(AQUI), "samples", "entradas")
    for nombre in ("06_receta_medica.pdf", "07_informe_estudio.png", "08_orden_procedimiento.jpg"):
        with open(os.path.join(entradas, nombre), "rb") as f:
            assert ca.validar_archivo(nombre, f.read()).ok, nombre


# --------------------------------------------------------------------------
# Campos de texto
# --------------------------------------------------------------------------
def test_validar_campos():
    assert ca.validar_campos("DOC-CLIN-2026-0001", "Guardia_Emergencias") is None
    assert "ID" in ca.validar_campos("  ", "canal")
    assert "ID" in ca.validar_campos("DOC 001", "canal")           # espacio
    assert "ID" in ca.validar_campos("DOC/../001", "canal")        # separadores de ruta
    assert "ID" in ca.validar_campos("X" * (ca.MAX_LARGO_ID + 1), "canal")
    assert "canal" in ca.validar_campos("DOC-1", "  ")


def test_id_generado_es_valido_y_unico():
    a, b = ca.generar_id_documento(), ca.generar_id_documento()
    assert a != b
    assert ca.validar_campos(a, "canal") is None


# --------------------------------------------------------------------------
# Cliente HTTP
# --------------------------------------------------------------------------
class _Respuesta:
    def __init__(self, status=200, cuerpo=None):
        self.status_code, self._cuerpo = status, cuerpo if cuerpo is not None else {}
        self.ok = status < 400
        self.reason = "x"

    def json(self):
        return self._cuerpo


class _Sesion:
    def __init__(self, resultado):
        self.resultado, self.llamadas = resultado, []

    def post(self, url, **kwargs):
        self.llamadas.append((url, kwargs))
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


def _con_sesion(monkeypatch, resultado):
    sesion = _Sesion(resultado)
    monkeypatch.setattr(ca, "obtener_sesion", lambda: sesion)
    return sesion


def test_enviar_documento_arma_el_multipart_esperado_por_la_api(monkeypatch):
    sesion = _con_sesion(monkeypatch, _Respuesta(200, {"status": "procesado"}))
    resp = ca.enviar_documento(" DOC-1 ", " Guardia ", "orden.pdf", PDF, "application/pdf")
    url, kw = sesion.llamadas[0]
    assert resp == {"status": "procesado"}
    assert url.endswith("/documentos")
    assert kw["data"] == {"documento_id": "DOC-1", "canal_origen": "Guardia"}
    assert kw["files"]["archivo"] == ("orden.pdf", PDF, "application/pdf")
    assert kw["timeout"][1] >= 60  # el pipeline llama a un LLM: no sirve el timeout de 15 s de las consultas


def test_error_de_la_api_se_muestra_con_su_detalle(monkeypatch):
    _con_sesion(monkeypatch, _Respuesta(415, {"detail": "Tipo de archivo no soportado: application/json"}))
    with pytest.raises(ErrorClienteAPI, match="415: Tipo de archivo no soportado"):
        ca.enviar_documento("DOC-1", "c", "a.json", b"{}", "application/json")


def test_fallo_tecnico_500_muestra_el_error_del_flujo(monkeypatch):
    _con_sesion(monkeypatch, _Respuesta(500, {"mensaje": "Fallo técnico al procesar el documento", "error": "RuntimeError: x"}))
    with pytest.raises(ErrorClienteAPI, match="Fallo técnico"):
        ca.enviar_documento("DOC-1", "c", "a.pdf", PDF, "application/pdf")


def test_sin_conexion_y_timeout(monkeypatch):
    _con_sesion(monkeypatch, requests.exceptions.ConnectionError())
    with pytest.raises(ErrorClienteAPI, match="No hay conexión"):
        ca.enviar_documento("DOC-1", "c", "a.pdf", PDF, "application/pdf")
    _con_sesion(monkeypatch, requests.exceptions.ReadTimeout())
    with pytest.raises(ErrorClienteAPI, match="antes de reenviarlo"):
        ca.enviar_documento("DOC-1", "c", "a.pdf", PDF, "application/pdf")


# --------------------------------------------------------------------------
# Contrato con el backend REAL: todo lo que el frontend acepta, la API lo acepta (y nada llega a 415)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "nombre, contenido",
    [
        ("a.jpg", JPG), ("a.png", PNG), ("a.pdf", PDF),
        ("a.json", json.dumps({"paciente": "Ana"}).encode()), ("a.md", "# Nota".encode()),
    ],
)
def test_contrato_backend_acepta_cada_formato_permitido(monkeypatch, nombre, contenido):
    import test_routes as tr

    tr._configurar_agentes_mock(monkeypatch)
    cliente = tr._crear_client(monkeypatch, tr.FakeOCIStorageService())
    v = ca.validar_archivo(nombre, contenido)
    assert v.ok
    r = cliente.post(
        "/documentos",
        data={"documento_id": "DOC-CARGA-1", "canal_origen": "Panel_Web"},
        files={"archivo": (nombre, contenido, v.mime)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "procesado"


def test_contrato_backend_application_json_daria_415(monkeypatch):
    """Documenta POR QUÉ JSON viaja como text/plain: con su MIME 'natural' la API lo rechaza."""
    import test_routes as tr

    tr._configurar_agentes_mock(monkeypatch)
    cliente = tr._crear_client(monkeypatch, tr.FakeOCIStorageService())
    r = cliente.post(
        "/documentos",
        data={"documento_id": "DOC-CARGA-2", "canal_origen": "Panel_Web"},
        files={"archivo": ("a.json", b"{}", "application/json")},
    )
    assert r.status_code == 415


# --------------------------------------------------------------------------
# La página se dibuja sin errores
# --------------------------------------------------------------------------
def test_pagina_de_carga_renderiza():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(os.path.join(os.path.dirname(AQUI), "frontend", "panel_carga.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert [s.value for s in at.subheader] == ["Enviar documento"]
    assert [t.label for t in at.text_input] == ["ID del documento", "Canal de origen"]
    boton = [b for b in at.button if b.label == "Enviar al pipeline"][0]
    assert boton.disabled                                  # sin archivo no se puede enviar
    assert ca.validar_campos(at.text_input[0].value, at.text_input[1].value) is None  # valores por defecto válidos


# --------------------------------------------------------------------------
# Flujo completo de la interfaz (subir -> validar -> enviar), con la API simulada
# --------------------------------------------------------------------------
def _abrir_pagina():
    from streamlit.testing.v1 import AppTest

    ruta = os.path.join(os.path.dirname(AQUI), "frontend", "panel_carga.py")
    return AppTest.from_file(ruta, default_timeout=60).run()


def _boton_enviar(at):
    return [b for b in at.button if b.label == "Enviar al pipeline"][0]


def test_ui_formato_no_valido_muestra_aviso_con_la_lista_y_bloquea_el_envio():
    at = _abrir_pagina()
    at.file_uploader[0].upload("informe.docx", b"PK\x03\x04 contenido").run()
    assert not at.exception, at.exception
    assert len(at.error) == 1
    assert "no válido" in at.error[0].value and "JPG, PNG, PDF, JSON y Markdown" in at.error[0].value
    assert _boton_enviar(at).disabled


def test_ui_envio_exitoso_muestra_resultado_y_reinicia_el_formulario(monkeypatch):
    respuesta = {
        "status": "procesado", "documento_id": "DOC-CLIN-2026-0001", "estado": "revision_humana",
        "persistencia_ok": True, "mensaje": "Documento procesado correctamente por MediFlow",
        "clasificacion": {"tipo_documento": "Receta Medica"}, "extraccion": {"nivel_urgencia": "no_urgente"},
    }
    sesion = _con_sesion(monkeypatch, _Respuesta(200, respuesta))
    at = _abrir_pagina()
    at.text_input[0].set_value("DOC-CLIN-2026-0001")
    at.text_input[1].set_value("Guardia_Emergencias")
    at.file_uploader[0].upload("orden.pdf", PDF, "application/pdf").run()
    assert not _boton_enviar(at).disabled and not at.error

    _boton_enviar(at).click().run()

    assert not at.exception, at.exception
    _, kw = sesion.llamadas[0]
    assert kw["data"] == {"documento_id": "DOC-CLIN-2026-0001", "canal_origen": "Guardia_Emergencias"}
    assert kw["files"]["archivo"] == ("orden.pdf", PDF, "application/pdf")
    assert [m.value for m in at.metric] == ["DOC-CLIN-2026-0001", "Auditoría humana", "no_urgente"]
    assert at.success and not at.error
    assert at.file_uploader[0].value is None               # formulario listo para el siguiente documento
    assert at.text_input[0].value != "DOC-CLIN-2026-0001"  # ID nuevo: no se pisa el resultado anterior


def test_ui_error_de_la_api_no_pierde_el_formulario(monkeypatch):
    _con_sesion(monkeypatch, _Respuesta(503, {"mensaje": "No se pudo guardar el documento original en OCI Object Storage."}))
    at = _abrir_pagina()
    at.file_uploader[0].upload("a.json", b'{"x": 1}', "application/json").run()
    _boton_enviar(at).click().run()
    assert not at.exception, at.exception
    assert any("503" in e.value and "OCI" in e.value for e in at.error)
    assert at.file_uploader[0].value is not None           # puede reintentar sin volver a seleccionar el archivo


def test_ui_id_invalido_se_avisa_antes_de_enviar(monkeypatch):
    sesion = _con_sesion(monkeypatch, _Respuesta(200, {}))
    at = _abrir_pagina()
    at.text_input[0].set_value("DOC 001 con espacios")
    at.file_uploader[0].upload("a.md", b"# Nota", "text/markdown").run()
    _boton_enviar(at).click().run()
    assert any("ID del documento" in e.value for e in at.error)
    assert sesion.llamadas == []                           # no se llamó a la API
