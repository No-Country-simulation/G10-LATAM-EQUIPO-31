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
        # Mismo mapeo estado -> carpeta que el servicio real (KeyError si la
        # ruta intentara persistir un estado que no existe).
        object_name = f"{ESTADOS_A_PREFIJO[estado]}{documento_id}.json"
        self.resultados_subidos.append((documento_id, estado, resultado))
        return object_name

    def upload_historial(self, documento_id, momento, evento):
        if self._fallar_upload_historial:
            raise PersistenciaOCIError("fallo simulado de OCI (historial)")
        # No reproduce el formato exacto del object_name real (eso ya lo
        # prueba tests/test_oci_storage_service.py contra el servicio de
        # verdad); acá solo hace falta que sea único por momento, para
        # poder comprobar que un reproceso no pisa el anterior.
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

    # MF-15: además de procesados/, el mismo procesamiento queda registrado
    # como un evento de historial (clasificador + extractor + validación
    # corrieron los tres, sin fallas técnicas).
    assert body["historial_ok"] is True
    assert body["oci_object_name_historial"] is not None
    assert len(fake_storage.historial_subido) == 1
    _, _, evento = fake_storage.historial_subido[0]
    assert evento["recorrido"]["agentes_ejecutados"] == [
        "clasificador", "extractor", "validacion_pydantic",
    ]
    assert evento["recorrido"]["fallos_tecnicos"] is None
    # MF-10 integrado: el historial conserva el resultado de confianza.
    assert evento["resumen"]["score_confianza_final"] == 0.97
    assert evento["resumen"]["categoria_confianza"] == "Alta"

    assert estado_persistido["validacion_ok"] is True
    assert estado_persistido["errores_validacion"] == []
    assert resultado["oci_object_name_original"] == fake_storage.documentos_subidos[0]

    # MF-11 integrado: el estado conserva la señal reconciliada de urgencia.
    assert resultado["urgente"] is False

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

    # MF-15: el evento de historial reusa el mismo estado_completo
    # serializado, así que hereda gratis la misma exclusión de contenido
    # pesado.
    assert body["historial_ok"] is True
    _, _, evento = fake_storage.historial_subido[0]
    documento_en_historial = evento["resultado"]["documento"]
    assert "contenido_bytes" not in documento_en_historial
    assert "documento_texto" not in documento_en_historial


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
    assert fake_storage.historial_subido == []


# --- MF-15: historial de triaje ---------------------------------------------


def test_post_documentos_reprocesado_dos_veces_historial_no_se_pisa(monkeypatch):
    """A diferencia de procesados/ (que pisa), cada corrida debe quedar
    como un evento nuevo en el historial.

    `datetime.now()` real puede devolver el MISMO microsegundo en dos
    llamadas consecutivas si la máquina es rápida (pasó en la práctica),
    lo que haría flaky esta prueba -- se controla el reloj de routes.py
    para garantizar dos instantes distintos sin depender de la velocidad
    de ejecución."""

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

    # procesados/: sigue pisando, una sola entrada "viva" por documento_id
    # en la lista del fake (semántica de sobrescritura, igual que el real).
    assert len(fake_storage.resultados_subidos) == 2
    assert fake_storage.resultados_subidos[0][0] == fake_storage.resultados_subidos[1][0]

    # historial/: dos eventos distintos, ninguno se pisa.
    assert len(fake_storage.historial_subido) == 2
    object_name_1 = respuesta_1.json()["oci_object_name_historial"]
    object_name_2 = respuesta_2.json()["oci_object_name_historial"]
    assert object_name_1 is not None and object_name_2 is not None
    assert object_name_1 != object_name_2


def test_post_documentos_excepcion_en_el_grafo_historial_registra_sin_agentes_ejecutados(
    monkeypatch,
):
    """Si el grafo crashea, no se puede saber con certeza en qué nodo
    estaba -- el historial debe reflejar eso (lista vacía), no inventar
    un recorrido."""

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
    """Un fallo al guardar el HISTORIAL no debe afectar la respuesta ni la
    persistencia en procesados/, que es independiente."""

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
    """Simula el estado que MF-19 produce cuando el clasificador agota
    Gemini y el fallback: el extractor NUNCA llega a correr (corta antes
    de llamar a ningún LLM, ver app/graph/graph.py::nodo_extractor en la
    rama de MF-19), así que el estado no tiene clave "extraccion"."""

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
            # MF-19: el Clasificador SÍ corrió (y generó su propia
            # metadata, aunque fallara del todo); el Extractor nunca llegó
            # a correr, así que metadata_extraccion no existe en el estado.
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
    """Complemento del test anterior: si el clasificador SÍ tuvo éxito y es
    el EXTRACTOR el que agota todo, sí llegó a correr (devuelve una
    extracción degradada) -- no debe excluirse de agentes_ejecutados solo
    porque fallos_tecnicos esté poblado."""

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
    """Cuando el estado trae categoria_confianza/score_confianza_final
    (MF-10), el resumen del historial los copia tal cual -- mismo criterio
    que destino_principal (MF-11): ni se inventan ni se recalculan acá."""

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
    # score_confianza_clasificacion (la autoevaluación cruda) se mantiene
    # en paralelo, no se pisa con score_confianza_final.
    assert evento["resumen"]["score_confianza_clasificacion"] == 0.95
    assert evento["resumen"]["destino_principal"] == "revision_humana"


def test_post_documentos_con_metadata_de_mf19_historial_copia_proveedor_modelo(monkeypatch):
    """Cuando el estado trae metadata_clasificacion/metadata_extraccion
    (MF-19), el recorrido las copia tal cual, por agente -- mismo criterio
    que destino_principal (MF-11) y la confianza (MF-10): ni se inventan
    ni se recalculan acá."""

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
    """Cuando el Clasificador falla del todo, el Extractor nunca llega a
    correr (ver app/graph/graph.py::nodo_extractor en la rama de MF-19) --
    el recorrido debe mostrar la metadata del Clasificador (sí corrió,
    aunque fallara) pero seguir en "no_disponible" para el Extractor
    (nunca generó metadata, no es que MF-19 no esté integrado)."""

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
