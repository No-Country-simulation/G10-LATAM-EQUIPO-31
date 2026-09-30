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
from app.services.oci_storage_service import ESTADOS_A_PREFIJO, PersistenciaOCIError

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
        # Mismo mapeo estado -> carpeta que el servicio real (KeyError si la
        # ruta intentara persistir un estado que no existe).
        object_name = f"{ESTADOS_A_PREFIJO[estado]}{documento_id}.json"
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
    # **_kwargs: MF-19 agrego el parametro generador_fallback a
    # clasificar_documento(); los mocks deben aceptar kwargs extra para
    # seguir siendo compatibles sin acoplarse a la firma exacta.
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
    # La respuesta HTTP mantiene su forma previa (compatibilidad hacia atrás).
    assert body["validacion"]["validacion_ok"] is True

    assert len(fake_storage.resultados_subidos) == 1
    documento_id, estado, resultado = fake_storage.resultados_subidos[0]
    assert documento_id == "DOC-TEST-001"
    assert estado == "estandar"

    # El envelope persistido guarda el estado COMPLETO del grafo (plano,
    # tal como lo devuelve grafo_mediflow.invoke), no un subconjunto de
    # campos elegidos a mano.
    estado_persistido = resultado["resultado"]
    assert estado_persistido["extraccion"]["nivel_urgencia"] == "no_urgente"
    assert estado_persistido["validacion_ok"] is True
    assert estado_persistido["errores_validacion"] == []
    assert resultado["oci_object_name_original"] == fake_storage.documentos_subidos[0]
    # Sin MF-11 integrado el estado no trae `urgente`: no se inventa la clave.
    assert "urgente" not in resultado

    # El documento original se serializa como metadata liviana: sin bytes
    # ni texto completo (eso ya vive en recibidos/).
    documento_persistido = estado_persistido["documento"]
    assert documento_persistido["documento_id"] == "DOC-TEST-001"
    assert documento_persistido["tipo_archivo"] == "JSON"
    assert "contenido_bytes" not in documento_persistido
    assert "documento_texto" not in documento_persistido


def test_post_documentos_validacion_falla_persiste_en_revision_humana(monkeypatch):
    # clasificar_documento devuelve None -> nodo_validacion_pydantic detecta
    # que falta la clasificación y marca validacion_ok=False.
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
        # La excepción técnica manda siempre, aun con destino_principal.
        (True, True, "urgente", "error_tecnico"),
        (False, True, None, "error_tecnico"),
        # destino_principal válido (contrato MF-11) se usa tal cual.
        (True, False, "estandar", "estandar"),
        (True, False, "urgente", "urgente"),
        (True, False, "revision_humana", "revision_humana"),
        (False, False, "urgente", "urgente"),
        # Sin destino_principal (MF-11 no integrado): fallback por validacion_ok.
        (True, False, None, "estandar"),
        (False, False, None, "revision_humana"),
        # Cualquier valor que no sea exactamente uno de los 3 del contrato
        # (mayúsculas, acentos, espacios, "error_tecnico", otro texto) va a
        # revision_humana, aunque la validación haya dado bien.
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
        # fallos_tecnicos (MF-19) manda a error_tecnico aunque no haya
        # habido excepción real y aunque venga un destino_principal válido.
        (False, "urgente", ["timeout llamando al proveedor Gemini"]),
        (False, "estandar", [{"nodo": "extraccion", "error": "timeout"}]),
        (False, None, ["timeout llamando al proveedor Gemini"]),
        # Si además hubo excepción, sigue siendo error_tecnico (misma regla).
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
    requiere_auditoria_humana), que hoy MediFlowState todavía no define."""

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
    "destino_principal,urgente,requiere_auditoria_humana",
    [
        ("estandar", False, False),
        ("urgente", True, False),
        ("revision_humana", False, True),
    ],
)
def test_post_documentos_con_destino_principal_de_mf11(
    monkeypatch, destino_principal, urgente, requiere_auditoria_humana
):
    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "destino_principal": destino_principal,
            "urgente": urgente,
            "requiere_auditoria_humana": requiere_auditoria_humana,
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-MF11")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == destino_principal
    assert body["persistencia_ok"] is True

    assert body["oci_object_name_resultado"] == (
        f"procesados/{destino_principal}/DOC-TEST-MF11.json"
    )

    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == destino_principal
    assert resultado["estado"] == destino_principal
    # `urgente` se copia a nivel superior del envelope...
    assert resultado["urgente"] is urgente
    # ...y los campos de MF-11 se persisten en el estado completo.
    assert resultado["resultado"]["destino_principal"] == destino_principal
    assert resultado["resultado"]["urgente"] is urgente
    assert resultado["resultado"]["requiere_auditoria_humana"] is requiere_auditoria_humana


def test_post_documentos_urgente_true_con_destino_revision_humana(monkeypatch):
    """Contrato de MF-11: un documento puede ser urgente y a la vez requerir
    revisión humana. Va a revision_humana, pero `urgente` se conserva en
    True (no se pisa) y requiere_auditoria_humana se guarda tal cual."""

    monkeypatch.setattr(
        routes,
        "grafo_mediflow",
        GrafoFalso({
            "destino_principal": "revision_humana",
            "urgente": True,
            "requiere_auditoria_humana": True,
        }),
    )
    fake_storage = FakeOCIStorageService()
    client = _crear_client(monkeypatch, fake_storage)

    response = _enviar_documento(client, documento_id="DOC-TEST-MF11-URG")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "revision_humana"
    assert body["oci_object_name_resultado"] == (
        "procesados/revision_humana/DOC-TEST-MF11-URG.json"
    )

    _, estado, resultado = fake_storage.resultados_subidos[0]
    assert estado == "revision_humana"
    assert resultado["urgente"] is True
    assert resultado["resultado"]["urgente"] is True
    assert resultado["resultado"]["destino_principal"] == "revision_humana"
    assert resultado["resultado"]["requiere_auditoria_humana"] is True


def test_post_documentos_destino_principal_desconocido_va_a_revision_humana(
    monkeypatch, caplog
):
    """Un valor fuera del contrato (p. ej. "Urgente" con mayúscula) no debe
    terminar en estandar: se deriva a revision_humana y se loguea."""

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
    # El valor original se persiste tal cual para poder auditarlo.
    assert resultado["resultado"]["destino_principal"] == "Urgente"
    assert resultado["urgente"] is True
    assert any("destino_principal desconocido" in r.getMessage() for r in caplog.records)


def test_post_documentos_fallos_tecnicos_de_mf19_sin_excepcion_va_a_error_tecnico(
    monkeypatch,
):
    """MF-19 puede agregar `fallos_tecnicos` al estado sin que el grafo
    lance una excepción real (el nodo captura el fallo y el flujo sigue).
    Igual debe tratarse como error_tecnico, con la misma respuesta HTTP
    (500, status "error") que ya usábamos para el caso de excepción real."""

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
    # No hubo excepción real, pero el campo `error` del envelope igual
    # lleva el detalle de `fallos_tecnicos` (cada elemento convertido a
    # texto), para que alguien que filtre por `error` no tenga que bucear
    # dentro de `resultado`. El detalle original (sea cual sea su forma:
    # string, dict por nodo, etc.) sigue disponible tal cual en
    # `resultado.fallos_tecnicos`.
    assert resultado["error"] == (
        "{'nodo': 'extraccion', 'error': 'timeout llamando al proveedor Gemini'}"
    )
    assert resultado["resultado"]["fallos_tecnicos"] == [
        {"nodo": "extraccion", "error": "timeout llamando al proveedor Gemini"},
    ]
    # destino_principal queda registrado tal cual, aunque fallos_tecnicos
    # tenga prioridad y no se haya usado para el enrutamiento.
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
    assert body["estado"] == "estandar"
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
