"""
tests/test_routes.py

Pruebas de la ruta POST /documentos, incluyendo la persistencia del
resultado en OCI (MF-13). Los agentes del grafo y el servicio de OCI se
mockean/reemplazan para no depender de Gemini ni de credenciales reales,
siguiendo el mismo patrón que tests/test_graph.py.
"""
import hashlib
from datetime import datetime, timezone
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
    Medicamento,
    NivelUrgencia,
    Paciente,
    Profesional,
)
from app.services.oci_storage_service import ESTADOS_A_PREFIJO, PersistenciaOCIError

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples" / "entradas"


def test_routes_importa_correctamente():
    assert routes.router is not None


class FakeOCIStorageService:
    """Reemplaza a OCIStorageService en las pruebas de la ruta: guarda en
    memoria lo que la ruta intentó persistir, sin tocar OCI real."""

    def __init__(
        self,
        fallar_upload_resultado=False,
        fallar_upload_document=False,
        fallar_upload_historial=False,
    ):
        self.documentos_subidos = []
        self.resultados_subidos = []
        self.historial_subido = []
        self._fallar_upload_resultado = fallar_upload_resultado
        self._fallar_upload_document = fallar_upload_document
        self._fallar_upload_historial = fallar_upload_historial

    def upload_document(self, document_id, content, filename):
        if self._fallar_upload_document:
            raise RuntimeError("bucket no disponible (fallo simulado)")
        object_name = f"recibidos/{document_id}_{filename}"
        self.documentos_subidos.append(object_name)
        return object_name

    def upload_resultado(self, documento_id, estado, resultado):
        if self._fallar_upload_resultado:
            raise PersistenciaOCIError("fallo simulado de OCI")
        object_name = f"{ESTADOS_A_PREFIJO[estado]}{documento_id}.json"
        self.resultados_subidos.append((documento_id, estado, resultado))
        return object_name

    def upload_historial(self, documento_id, momento, evento):
        if self._fallar_upload_historial:
            raise PersistenciaOCIError("fallo simulado de OCI (historial)")
        object_name = f"historial/{documento_id}/{momento.isoformat()}.json"
        self.historial_subido.append((documento_id, momento, evento))
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
    medicamentos=[Medicamento(nombre="Enalapril", dosis="10mg")],
    nivel_urgencia=NivelUrgencia.NO_URGENTE,
)


def _configurar_agentes_mock(monkeypatch, clasificar=None, extraer=None):
    monkeypatch.setattr(
        graph,
        "clasificar_documento",
        clasificar or (lambda _documento, **_kwargs: CLASIFICACION_PRUEBA),
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


def test_post_documentos_exitoso_persiste_en_estandar(monkeypatch):
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client)

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "estandar"
    assert body["persistencia_ok"] is True
    assert body["oci_object_name_resultado"] == "procesados/estandar/DOC-TEST-001.json"
    assert body["validacion"]["validacion_ok"] is True

    assert len(fake_storage.resultados_subidos) == 1
    documento_id, estado, resultado = fake_storage.resultados_subidos[0]
    assert documento_id == "DOC-TEST-001"
    assert estado == "estandar"

    estado_persistido = resultado["resultado"]
    assert estado_persistido["extraccion"]["nivel_urgencia"] == "no_urgente"

    assert body["historial_ok"] is True
    assert body["oci_object_name_historial"] is not None
    assert len(fake_storage.historial_subido) == 1
    _, _, evento = fake_storage.historial_subido[0]
    assert evento["recorrido"]["agentes_ejecutados"] == [
        "clasificador", "extractor", "validacion_pydantic",
    ]
    assert evento["recorrido"]["fallos_tecnicos"] is None
    assert evento["resumen"]["score_confianza_final"] == 0.97
    assert evento["resumen"]["categoria_confianza"] == "Alta"
    assert evento["resumen"]["departamento_destino"] == "farmacia_hospitalaria"

    assert estado_persistido["validacion_ok"] is True
    assert estado_persistido["errores_validacion"] == []
    assert resultado["oci_object_name_original"] == fake_storage.documentos_subidos[0]

    assert resultado["urgente"] is False

    documento_persistido = estado_persistido["documento"]
    assert documento_persistido["documento_id"] == "DOC-TEST-001"
    assert documento_persistido["tipo_archivo"] == "JSON"
    assert "contenido_bytes" not in documento_persistido
    assert "documento_texto" not in documento_persistido


def test_post_documentos_validacion_falla_persiste_en_revision_humana(monkeypatch):
    _configurar_agentes_mock(monkeypatch, clasificar=lambda _documento, **_kwargs: None)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-002")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "revision_humana"
    assert body["persistencia_ok"] is True

    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "revision_humana"
    assert resultado["resultado"]["validacion_ok"] is False
    assert resultado["resultado"]["clasificacion"] is None


def test_post_documentos_excepcion_en_el_grafo_persiste_en_errores_tecnicos(monkeypatch):
    def clasificar_que_falla(_documento, **_kwargs):
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


@pytest.mark.parametrize(
    "validacion_ok,hubo_excepcion,destino_principal,esperado",
    [
        (True, True, "urgente", "error_tecnico"),
        (False, True, None, "error_tecnico"),
        (True, False, "estandar", "estandar"),
        (True, False, "urgente", "urgente"),
        (True, False, "revision_humana", "revision_humana"),
        (False, False, "urgente", "urgente"),
        (True, False, None, "estandar"),
        (False, False, None, "revision_humana"),
        (True, False, "cualquier_cosa", "revision_humana"),
        (False, False, "cualquier_cosa", "revision_humana"),
        (True, False, "error_tecnico", "revision_humana"),
        (True, False, "Urgente", "revision_humana"),
        (True, False, "URGENTE", "revision_humana"),
        (True, False, " urgente", "revision_humana"),
        (True, False, "estándar", "revision_humana"),
        (True, False, "revision humana", "revision_humana"),
        (True, False, "", "revision_humana"),
    ],
)
def test_determinar_estado(validacion_ok, hubo_excepcion, destino_principal, esperado):
    assert routes.determinar_estado(
        validacion_ok=validacion_ok,
        hubo_excepcion=hubo_excepcion,
        destino_principal=destino_principal,
    ) == esperado


@pytest.mark.parametrize(
    "hubo_excepcion,destino_principal,fallos_tecnicos",
    [
        (False, "urgente", ["timeout llamando al proveedor Gemini"]),
        (False, "estandar", [{"nodo": "extraccion", "error": "timeout"}]),
        (False, None, ["timeout llamando al proveedor Gemini"]),
        (True, "estandar", ["timeout llamando al proveedor Gemini"]),
    ],
)
def test_determinar_estado_fallos_tecnicos_de_mf19_manda_a_error_tecnico(
    hubo_excepcion, destino_principal, fallos_tecnicos
):
    assert routes.determinar_estado(
        validacion_ok=True,
        hubo_excepcion=hubo_excepcion,
        destino_principal=destino_principal,
        fallos_tecnicos=fallos_tecnicos,
    ) == "error_tecnico"


@pytest.mark.parametrize("fallos_tecnicos", [None, []])
def test_determinar_estado_fallos_tecnicos_vacio_no_afecta(fallos_tecnicos):
    assert routes.determinar_estado(
        validacion_ok=True,
        hubo_excepcion=False,
        destino_principal="estandar",
        fallos_tecnicos=fallos_tecnicos,
    ) == "estandar"


class GrafoFalso:
    """Reemplaza a grafo_mediflow para simular el estado que va a devolver el
    grafo una vez integrado MF-11 (destino_principal, urgente,
    requiere_auditoria_humana, departamento_destino)."""

    def __init__(self, campos_extra):
        self._campos_extra = campos_extra

    def invoke(self, estado_inicial):
        return {
            **estado_inicial,
            "clasificacion": CLASIFICACION_PRUEBA,
            "extraccion": EXTRACCION_PRUEBA,
            "validacion_ok": True,
            "errores_validacion": [],
            **self._campos_extra,
        }


@pytest.mark.parametrize(
    "destino_principal,urgente,requiere_auditoria_humana,departamento_destino",
    [
        ("estandar", False, False, "Farmacia"),
        ("urgente", True, False, "Urgencias / Guardia"),
        ("revision_humana", False, True, "Auditoría Médica"),
    ],
)
def test_post_documentos_con_destino_principal_y_departamento_de_mf11(
    monkeypatch, destino_principal, urgente, requiere_auditoria_humana, departamento_destino
):
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "destino_principal": destino_principal,
            "urgente": urgente,
            "requiere_auditoria_humana": requiere_auditoria_humana,
            "departamento_destino": departamento_destino,
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-MF11")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == destino_principal
    assert body["persistencia_ok"] is True
    assert body["departamento_destino"] == departamento_destino

    assert body["oci_object_name_resultado"] == (
        f"procesados/{destino_principal}/DOC-TEST-MF11.json"
    )

    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == destino_principal
    assert resultado["estado"] == destino_principal
    assert resultado["urgente"] is urgente
    assert resultado["departamento_destino"] == departamento_destino
    assert resultado["resultado"]["destino_principal"] == destino_principal
    assert resultado["resultado"]["urgente"] is urgente
    assert resultado["resultado"]["requiere_auditoria_humana"] is requiere_auditoria_humana
    assert resultado["resultado"]["departamento_destino"] == departamento_destino

    _, _, evento = fake_storage.historial_subido[0]
    assert evento["resumen"]["departamento_destino"] == departamento_destino


def test_post_documentos_urgente_true_con_destino_revision_humana(monkeypatch):
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "destino_principal": "revision_humana",
            "urgente": True,
            "requiere_auditoria_humana": True,
            "departamento_destino": "Urgencias",
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-MF11-URG")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "revision_humana"
    assert body["departamento_destino"] == "Urgencias"
    assert body["oci_object_name_resultado"] == (
        "procesados/revision_humana/DOC-TEST-MF11-URG.json"
    )

    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "revision_humana"
    assert resultado["urgente"] is True
    assert resultado["departamento_destino"] == "Urgencias"
    assert resultado["resultado"]["urgente"] is True
    assert resultado["resultado"]["destino_principal"] == "revision_humana"
    assert resultado["resultado"]["requiere_auditoria_humana"] is True


def test_post_documentos_destino_principal_desconocido_va_a_revision_humana(
    monkeypatch, caplog
):
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({"destino_principal": "Urgente", "urgente": True}),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    with caplog.at_level("WARNING", logger="mediflow.app.api.routes"):
        response = _enviar_documento(client, documento_id="DOC-TEST-MF11-X")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "revision_humana"
    assert body["oci_object_name_resultado"] == (
        "procesados/revision_humana/DOC-TEST-MF11-X.json"
    )
    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "revision_humana"
    assert resultado["resultado"]["destino_principal"] == "Urgente"
    assert resultado["urgente"] is True
    assert any("destino_principal desconocido" in r.getMessage() for r in caplog.records)


def test_post_documentos_fallos_tecnicos_de_mf19_sin_excepcion_va_a_error_tecnico(
    monkeypatch,
):
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "destino_principal": "estandar",
            "fallos_tecnicos": [
                {"nodo": "extraccion", "error": "timeout llamando al proveedor Gemini"},
            ],
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-MF19")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert body["estado"] == "error_tecnico"
    assert body["mensaje"] == "Fallo técnico al procesar el documento"
    assert body["persistencia_ok"] is True
    assert body["oci_object_name_resultado"] == "errores_tecnicos/DOC-TEST-MF19.json"

    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "error_tecnico"
    assert resultado["error"] == (
        "{'nodo': 'extraccion', 'error': 'timeout llamando al proveedor Gemini'}"
    )
    assert resultado["resultado"]["fallos_tecnicos"] == [
        {"nodo": "extraccion", "error": "timeout llamando al proveedor Gemini"},
    ]
    assert resultado["resultado"]["destino_principal"] == "estandar"


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
    assert fake_storage.historial_subido == []


def test_post_documentos_fallo_de_persistencia_no_tumba_la_respuesta(monkeypatch):
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService(fallar_upload_resultado=True)
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-005")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "estandar"
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
    assert body["estado"] == "estandar"
    assert body["persistencia_ok"] is True

    _, _, resultado = fake_storage.resultados_subidos[0]
    documento_persistido = resultado["resultado"]["documento"]
    assert documento_persistido["tipo_archivo"] == tipo_esperado
    assert documento_persistido["nombre_archivo"] == filename
    assert documento_persistido["mime_type"] == content_type
    assert "contenido_bytes" not in documento_persistido
    assert "documento_texto" not in documento_persistido

    assert body["historial_ok"] is True
    _, _, evento = fake_storage.historial_subido[0]
    documento_en_historial = evento["resultado"]["documento"]
    assert "contenido_bytes" not in documento_en_historial
    assert "documento_texto" not in documento_en_historial


def test_post_documentos_fallo_al_guardar_original_devuelve_503_estructurado(monkeypatch):
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
    assert fake_storage.historial_subido == []


# --- MF-15: historial de triaje ---------------------------------------------


def test_post_documentos_reprocesado_dos_veces_historial_no_se_pisa(monkeypatch):
    momentos = iter([
        datetime(2026, 1, 1, 12, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 12, 0, 0, 1, tzinfo=timezone.utc),
    ])

    class _DatetimeControlado(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(momentos)

    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)
    monkeypatch.setattr(routes, "datetime", _DatetimeControlado)

    respuesta_1 = _enviar_documento(client, documento_id="DOC-TEST-HIST-001")
    respuesta_2 = _enviar_documento(client, documento_id="DOC-TEST-HIST-001")

    assert respuesta_1.status_code == 200
    assert respuesta_2.status_code == 200

    assert len(fake_storage.resultados_subidos) == 2
    assert fake_storage.resultados_subidos[0][0] == fake_storage.resultados_subidos[1][0]

    assert len(fake_storage.historial_subido) == 2
    object_name_1 = respuesta_1.json()["oci_object_name_historial"]
    object_name_2 = respuesta_2.json()["oci_object_name_historial"]
    assert object_name_1 is not None and object_name_2 is not None
    assert object_name_1 != object_name_2


def test_post_documentos_excepcion_en_el_grafo_historial_registra_sin_agentes_ejecutados(
    monkeypatch,
):
    def clasificar_que_falla(_documento, **_kwargs):
        raise RuntimeError("El proveedor Gemini no respondió (fallo técnico simulado)")

    _configurar_agentes_mock(monkeypatch, clasificar=clasificar_que_falla)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-HIST-002")

    assert response.status_code == 500
    body = response.json()
    assert body["estado"] == "error_tecnico"
    assert body["historial_ok"] is True

    assert len(fake_storage.historial_subido) == 1
    _, _, evento = fake_storage.historial_subido[0]
    assert evento["recorrido"]["agentes_ejecutados"] == []
    assert evento["resultado"] is None
    assert "RuntimeError" in evento["error"]


def test_post_documentos_fallo_al_guardar_historial_no_tumba_la_respuesta(monkeypatch):
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService(fallar_upload_historial=True)
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-HIST-003")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "estandar"
    assert body["persistencia_ok"] is True
    assert body["oci_object_name_resultado"] == "procesados/estandar/DOC-TEST-HIST-003.json"
    assert body["historial_ok"] is False
    assert body["oci_object_name_historial"] is None
    assert fake_storage.historial_subido == []


class GrafoFalsoClasificadorFallaTotal:
    def invoke(self, estado_inicial):
        return {
            **estado_inicial,
            "clasificacion": CLASIFICACION_PRUEBA,
            "fallos_tecnicos": [
                "Clasificador: fallaron el modelo principal y el fallback."
            ],
            "validacion_ok": False,
            "errores_validacion": [
                "Clasificador: fallaron el modelo principal y el fallback.",
                "No se generó un resultado de extracción.",
            ],
            "metadata_clasificacion": {
                "proveedor_usado": None,
                "modelo_usado": None,
                "fallback_utilizado": True,
                "intentos_principal": 3,
                "intentos_fallback": 3,
            },
        }


def test_post_documentos_clasificador_falla_total_excluye_extractor_de_agentes_ejecutados(
    monkeypatch,
):
    monkeypatch.setattr(routes, "grafo_mediflow", GrafoFalsoClasificadorFallaTotal())
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-HIST-004")

    assert response.status_code == 500
    assert response.json()["estado"] == "error_tecnico"

    assert len(fake_storage.historial_subido) == 1
    _, _, evento = fake_storage.historial_subido[0]
    assert evento["recorrido"]["agentes_ejecutados"] == [
        "clasificador", "validacion_pydantic",
    ]
    assert "extraccion" not in evento["resultado"]


def test_post_documentos_extractor_falla_total_incluye_extractor_en_agentes_ejecutados(
    monkeypatch,
):
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "fallos_tecnicos": [
                "Extractor: fallaron el modelo principal y el fallback."
            ],
            "validacion_ok": False,
            "errores_validacion": [
                "Extractor: fallaron el modelo principal y el fallback."
            ],
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-HIST-005")

    assert response.status_code == 500
    assert response.json()["estado"] == "error_tecnico"

    assert len(fake_storage.historial_subido) == 1
    _, _, evento = fake_storage.historial_subido[0]
    assert evento["recorrido"]["agentes_ejecutados"] == [
        "clasificador", "extractor", "validacion_pydantic",
    ]
    assert "extraccion" in evento["resultado"]


def test_post_documentos_con_confianza_de_mf10_historial_incluye_resumen(monkeypatch):
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "destino_principal": "revision_humana",
            "urgente": False,
            "requiere_auditoria_humana": True,
            "categoria_confianza": "Media",
            "score_confianza_final": 0.7,
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-HIST-006")

    assert response.status_code == 200
    assert response.json()["estado"] == "revision_humana"

    assert len(fake_storage.historial_subido) == 1
    _, _, evento = fake_storage.historial_subido[0]
    assert evento["resumen"]["categoria_confianza"] == "Media"
    assert evento["resumen"]["score_confianza_final"] == 0.7
    assert evento["resumen"]["score_confianza_clasificacion"] == 0.95
    assert evento["resumen"]["destino_principal"] == "revision_humana"


def test_post_documentos_con_metadata_de_mf19_historial_copia_proveedor_modelo(monkeypatch):
    metadata_clasificacion = {
        "proveedor_usado": "groq", "modelo_usado": "qwen/qwen3.8-27b",
        "fallback_utilizado": True, "intentos_principal": 3, "intentos_fallback": 1,
    }
    metadata_extraccion = {
        "proveedor_usado": "gemini", "modelo_usado": "gemini-3.5-flash-lite",
        "fallback_utilizado": False, "intentos_principal": 1, "intentos_fallback": 0,
    }
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "metadata_clasificacion": metadata_clasificacion,
            "metadata_extraccion": metadata_extraccion,
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-HIST-007")

    assert response.status_code == 200

    assert len(fake_storage.historial_subido) == 1
    _, _, evento = fake_storage.historial_subido[0]
    assert evento["recorrido"]["proveedor_modelo"]["clasificador"] == metadata_clasificacion
    assert evento["recorrido"]["proveedor_modelo"]["extractor"] == metadata_extraccion


def test_post_documentos_clasificador_falla_total_no_hay_metadata_de_extractor(monkeypatch):
    monkeypatch.setattr(routes, "grafo_mediflow", GrafoFalsoClasificadorFallaTotal())
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-HIST-008")

    assert response.status_code == 500
    assert response.json()["estado"] == "error_tecnico"

    assert len(fake_storage.historial_subido) == 1
    _, _, evento = fake_storage.historial_subido[0]
    assert evento["recorrido"]["proveedor_modelo"]["clasificador"] == {
        "proveedor_usado": None, "modelo_usado": None, "fallback_utilizado": True,
        "intentos_principal": 3, "intentos_fallback": 3,
    }
    assert evento["recorrido"]["proveedor_modelo"]["extractor"] == (
        "no_disponible (el agente no se ejecutó)"
    )



# --------------------------------------------------------------------------
# MF-22: huella SHA-256 del contenido original (CAMPO_HUELLA = "huella_sha256",
# propuesto por Mauricio para MF-15 -- ver docs/historial-triaje.md).
# --------------------------------------------------------------------------
def test_post_documentos_huella_sha256_mismo_contenido_misma_huella(monkeypatch):
    """La huella depende solo del contenido -- enviar el mismo archivo con
    otro documento_id y otro nombre de archivo debe dar la misma huella."""
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)
    contenido = (SAMPLES_DIR / "01_receta_medica.txt").read_bytes()
    esperada = hashlib.sha256(contenido).hexdigest()

    client.post(
        "/documentos",
        data={"documento_id": "DOC-HUELLA-A", "canal_origen": "test"},
        files={"archivo": ("01_receta_medica.txt", contenido, "text/plain")},
    )
    client.post(
        "/documentos",
        data={"documento_id": "DOC-HUELLA-B", "canal_origen": "test"},
        files={"archivo": ("copia_con_otro_nombre.txt", contenido, "text/plain")},
    )

    huellas = {doc_id: resultado["huella_sha256"] for doc_id, _, resultado in fake_storage.resultados_subidos}
    assert huellas["DOC-HUELLA-A"] == esperada
    assert huellas["DOC-HUELLA-B"] == esperada


def test_post_documentos_huella_sha256_contenido_distinto_huella_distinta(monkeypatch):
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    _enviar_documento(client, documento_id="DOC-HUELLA-C", filename="01_receta_medica.txt")
    _enviar_documento(client, documento_id="DOC-HUELLA-D", filename="02_informe_estudio.txt")

    huellas = {doc_id: resultado["huella_sha256"] for doc_id, _, resultado in fake_storage.resultados_subidos}
    assert huellas["DOC-HUELLA-C"] != huellas["DOC-HUELLA-D"]
    assert huellas["DOC-HUELLA-C"] == hashlib.sha256(
        (SAMPLES_DIR / "01_receta_medica.txt").read_bytes()
    ).hexdigest()
    assert huellas["DOC-HUELLA-D"] == hashlib.sha256(
        (SAMPLES_DIR / "02_informe_estudio.txt").read_bytes()
    ).hexdigest()


def test_post_documentos_huella_sha256_presente_en_exito(monkeypatch):
    """Caso 1/3: éxito -- la huella queda en procesados/ y en historial/."""
    _configurar_agentes_mock(monkeypatch)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)
    esperada = hashlib.sha256((SAMPLES_DIR / "01_receta_medica.txt").read_bytes()).hexdigest()

    response = _enviar_documento(client, documento_id="DOC-HUELLA-EXITO")

    assert response.status_code == 200
    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "estandar"
    assert resultado["huella_sha256"] == esperada
    _, _, evento_historial = fake_storage.historial_subido[0]
    assert evento_historial["huella_sha256"] == esperada


def test_post_documentos_huella_sha256_presente_en_excepcion_del_grafo(monkeypatch):
    """Caso 2/3: excepción real del grafo -- la huella ya se calculó en el
    paso 1 (antes de correr el grafo), así que sigue presente aunque el
    procesamiento falle del todo."""

    def clasificar_que_falla(_documento, **_kwargs):
        raise RuntimeError("El proveedor Gemini no respondió (fallo técnico simulado)")

    _configurar_agentes_mock(monkeypatch, clasificar=clasificar_que_falla)
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)
    esperada = hashlib.sha256((SAMPLES_DIR / "01_receta_medica.txt").read_bytes()).hexdigest()

    response = _enviar_documento(client, documento_id="DOC-HUELLA-EXCEPCION")

    assert response.status_code == 500
    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "error_tecnico"
    assert resultado["huella_sha256"] == esperada
    _, _, evento_historial = fake_storage.historial_subido[0]
    assert evento_historial["huella_sha256"] == esperada


def test_post_documentos_huella_sha256_presente_en_fallos_tecnicos_de_mf19(monkeypatch):
    """Caso 3/3: fallos_tecnicos (MF-19) sin excepción real -- también va a
    error_tecnico, y también debe llevar la huella."""
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "destino_principal": "estandar",
            "fallos_tecnicos": [
                {"nodo": "extraccion", "error": "timeout llamando al proveedor Gemini"},
            ],
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)
    esperada = hashlib.sha256((SAMPLES_DIR / "01_receta_medica.txt").read_bytes()).hexdigest()

    response = _enviar_documento(client, documento_id="DOC-HUELLA-FALLOSTECNICOS")

    assert response.status_code == 500
    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "error_tecnico"
    assert resultado["huella_sha256"] == esperada
    _, _, evento_historial = fake_storage.historial_subido[0]
    assert evento_historial["huella_sha256"] == esperada
