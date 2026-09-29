"""
tests/test_routes.py

Pruebas de la ruta POST /documentos, incluyendo la persistencia del
resultado en OCI (MF-13). Los agentes del grafo y el servicio de OCI se
mockean/reemplazan para no depender de Gemini ni de credenciales reales,
siguiendo el mismo patrón que tests/test_graph.py.
"""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.graph import graph
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import (
    Diagnostico,
    ExtraccionClinica,
    NivelUrgencia,
    Paciente,
    Profesional,
)
from app.services.oci_storage_service import PersistenciaOCIError

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples" / "entradas"


def test_routes_importa_correctamente():
    assert routes.router is not None


class FakeOCIStorageService:
    """Reemplaza a OCIStorageService en las pruebas de la ruta: guarda en
    memoria lo que la ruta intentó persistir, sin tocar OCI real."""

    def __init__(self, fallar_upload_resultado=False, fallar_upload_document=False):
        self.documentos_subidos = []
        self.resultados_subidos = []
        self._fallar_upload_resultado = fallar_upload_resultado
        self._fallar_upload_document = fallar_upload_document

    def upload_document(self, document_id, content, filename):
        if self._fallar_upload_document:
            raise RuntimeError("bucket no disponible (fallo simulado)")
        object_name = f"recibidos/{document_id}_{filename}"
        self.documentos_subidos.append(object_name)
        return object_name

    def upload_resultado(self, documento_id, estado, resultado):
        if self._fallar_upload_resultado:
            raise PersistenciaOCIError("fallo simulado de OCI")
        object_name = f"{estado}/{documento_id}.json"
        self.resultados_subidos.append((documento_id, estado, resultado))
        return object_name


CLASIFICACION_PRUEBA = Classification(
    tipo_documento=DocumentType.RECETA_MEDICA,
    especialidad="Medicina General",
    nivel_prioridad="Rutina",
    score_confianza_clasificacion=0.95,
    justificacion="El documento se identifica como receta médica.",
)

EXTRACCION_PRUEBA = ExtraccionClinica(
    paciente=Paciente(nombre_completo="Laura Martínez Gómez", edad=45),
    profesional=Profesional(
        nombre_completo="Dr. Andrés Ramírez", registro_profesional="MP-45821"
    ),
    diagnosticos=[Diagnostico(descripcion="Hipertensión arterial esencial", codigo_cie10="I10")],
    nivel_urgencia=NivelUrgencia.NO_URGENTE,
)


def _configurar_agentes_mock(monkeypatch, clasificar=None, extraer=None):
    monkeypatch.setattr(
        graph, "clasificar_documento", clasificar or (lambda _documento: CLASIFICACION_PRUEBA)
    )
    monkeypatch.setattr(
        graph, "extraer_datos_clinicos", extraer or (lambda **kwargs: EXTRACCION_PRUEBA)
    )
    monkeypatch.setattr(graph, "ProveedorGemini", lambda: object())


def _crear_client(monkeypatch, fake_storage: FakeOCIStorageService):
    monkeypatch.setattr(routes, "OCIStorageService", lambda: fake_storage)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def _enviar_documento(client, documento_id="DOC-TEST-001", filename="01_receta_medica.txt", content_type="text/plain"):
    contenido = (SAMPLES_DIR / filename).read_bytes()
    return client.post(
        "/documentos",
        data={"documento_id": documento_id, "canal_origen": "test"},
        files={"archivo": (filename, contenido, content_type)},
    )


def test_post_documentos_exitoso_persiste_en_procesados(monkeypatch):
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client)

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "procesado_exitoso"
    assert body["persistencia_ok"] is True
    assert body["oci_object_name_resultado"] == "procesado_exitoso/DOC-TEST-001.json"
    # La respuesta HTTP mantiene su forma previa (compatibilidad hacia atrás).
    assert body["validacion"]["validacion_ok"] is True

    assert len(fake_storage.resultados_subidos) == 1
    documento_id, estado, resultado = fake_storage.resultados_subidos[0]
    assert documento_id == "DOC-TEST-001"
    assert estado == "procesado_exitoso"

    # El envelope persistido guarda el estado COMPLETO del grafo (plano,
    # tal como lo devuelve grafo_mediflow.invoke), no un subconjunto de
    # campos elegidos a mano.
    estado_persistido = resultado["resultado"]
    assert estado_persistido["extraccion"]["nivel_urgencia"] == "no_urgente"
    assert estado_persistido["validacion_ok"] is True
    assert estado_persistido["errores_validacion"] == []
    assert resultado["oci_object_name_original"] == fake_storage.documentos_subidos[0]

    # El documento original se serializa como metadata liviana: sin bytes
    # ni texto completo (eso ya vive en recibidos/).
    documento_persistido = estado_persistido["documento"]
    assert documento_persistido["documento_id"] == "DOC-TEST-001"
    assert documento_persistido["tipo_archivo"] == "JSON"
    assert "contenido_bytes" not in documento_persistido
    assert "documento_texto" not in documento_persistido


def test_post_documentos_validacion_falla_persiste_en_auditoria_humana(monkeypatch):
    # clasificar_documento devuelve None -> nodo_validacion_pydantic detecta
    # que falta la clasificación y marca validacion_ok=False.
    _configurar_agentes_mock(monkeypatch, clasificar=lambda _documento: None)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-002")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "auditoria_humana"
    assert body["persistencia_ok"] is True

    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "auditoria_humana"
    assert resultado["resultado"]["validacion_ok"] is False
    assert resultado["resultado"]["clasificacion"] is None


def test_post_documentos_excepcion_en_el_grafo_persiste_en_errores_tecnicos(monkeypatch):
    def clasificar_que_falla(_documento):
        raise RuntimeError("El proveedor Gemini no respondió (fallo técnico simulado)")

    _configurar_agentes_mock(monkeypatch, clasificar=clasificar_que_falla)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-003")

    assert response.status_code == 500
    body = response.json()
    assert body["estado"] == "error_tecnico"
    assert body["persistencia_ok"] is True

    documento_id, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "error_tecnico"
    assert "RuntimeError" in resultado["error"]
    assert resultado["resultado"] is None


def test_post_documentos_tipo_no_soportado_no_persiste_nada(monkeypatch):
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = client.post(
        "/documentos",
        data={"documento_id": "DOC-TEST-004", "canal_origen": "test"},
        files={"archivo": ("archivo.bin", b"\x00\x01\x02", "application/octet-stream")},
    )

    assert response.status_code == 415
    assert fake_storage.documentos_subidos == []
    assert fake_storage.resultados_subidos == []


def test_post_documentos_fallo_de_persistencia_no_tumba_la_respuesta(monkeypatch):
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService(fallar_upload_resultado=True)
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-005")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "procesado_exitoso"
    assert body["persistencia_ok"] is False
    assert body["oci_object_name_resultado"] is None


@pytest.mark.parametrize(
    "filename,content_type,tipo_esperado",
    [
        ("06_receta_medica.pdf", "application/pdf", "PDF"),
        ("07_informe_estudio.png", "image/png", "Imagen"),
        ("08_orden_procedimiento.jpg", "image/jpeg", "Imagen"),
    ],
)
def test_post_documentos_formatos_binarios_de_samples_entradas(
    monkeypatch, filename, content_type, tipo_esperado
):
    """PDF/PNG/JPG de samples/entradas/ deben procesarse igual que el texto,
    y el documento persistido no debe incluir el contenido binario (ya vive
    en recibidos/)."""

    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(
        client,
        documento_id=f"DOC-TEST-{tipo_esperado.upper()}",
        filename=filename,
        content_type=content_type,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "procesado_exitoso"
    assert body["persistencia_ok"] is True

    _, _, resultado = fake_storage.resultados_subidos[0]
    documento_persistido = resultado["resultado"]["documento"]
    assert documento_persistido["tipo_archivo"] == tipo_esperado
    assert documento_persistido["nombre_archivo"] == filename
    assert documento_persistido["mime_type"] == content_type
    assert "contenido_bytes" not in documento_persistido
    assert "documento_texto" not in documento_persistido


def test_post_documentos_fallo_al_guardar_original_devuelve_503_estructurado(monkeypatch):
    """Si falla la subida del documento ORIGINAL, no tiene sentido correr el
    grafo ni intentar persistir un resultado contra el mismo OCI caído."""

    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService(fallar_upload_document=True)
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-006")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["documento_id"] == "DOC-TEST-006"
    assert "error" in body

    assert fake_storage.documentos_subidos == []
    assert fake_storage.resultados_subidos == []
