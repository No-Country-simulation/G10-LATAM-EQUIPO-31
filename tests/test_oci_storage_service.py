"""
tests/test_oci_storage_service.py

Pruebas del servicio de conexión con OCI Object Storage (MF-04) y de la
persistencia de resultados del flujo (MF-13).
Usa un cliente OCI falso en memoria para no depender de credenciales
reales ni de red.

Ejecutar desde la raíz del repositorio:
    pytest tests/test_oci_storage_service.py -v
"""
import json

import pytest

from app.services import oci_storage_service as service_module
from app.services.oci_storage_service import OCIStorageService, PersistenciaOCIError

ENV_VARS = {
    "OCI_USER_OCID": "ocid1.user.oc1..fake",
    "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..fake",
    "OCI_FINGERPRINT": "aa:bb:cc:dd:ee:ff",
    "OCI_PRIVATE_KEY_PATH": "/fake/key.pem",
    "OCI_REGION": "sa-saopaulo-1",
    "OCI_NAMESPACE": "fake-namespace",
    "OCI_BUCKET_NAME": "documentos-clinicos",
}


class ObjectStorageClientFalso:
    """Simula el ObjectStorageClient de OCI guardando los objetos en memoria."""

    def __init__(self, config):
        self.config_recibida = config
        self._objetos = {}

    def put_object(self, namespace_name, bucket_name, object_name, put_object_body):
        self._objetos[(namespace_name, bucket_name, object_name)] = put_object_body

    def get_object(self, namespace_name, bucket_name, object_name):
        clave = (namespace_name, bucket_name, object_name)
        contenido = self._objetos[clave]
        return RespuestaFalsa(contenido)


class RespuestaFalsa:
    def __init__(self, content: bytes):
        self.data = DatosFalsos(content)


class DatosFalsos:
    def __init__(self, content: bytes):
        self.content = content


@pytest.fixture
def service(monkeypatch):
    for key, value in ENV_VARS.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(service_module.oci.config, "validate_config", lambda config: None)
    monkeypatch.setattr(
        service_module.oci.object_storage, "ObjectStorageClient", ObjectStorageClientFalso
    )

    return OCIStorageService()


def test_upload_document_devuelve_object_name_con_prefijo_recibidos(service):
    object_name = service.upload_document("DOC-2026-ABC123", b"contenido", "informe.pdf")

    assert object_name == "recibidos/DOC-2026-ABC123_informe.pdf"


def test_upload_y_get_document_recuperan_el_mismo_contenido(service):
    contenido = b"contenido de prueba MF-04"
    object_name = service.upload_document("DOC-2026-XYZ789", contenido, "orden.txt")

    recuperado = service.get_document(object_name)

    assert recuperado == contenido


def test_get_document_con_object_name_inexistente_lanza_error(service):
    with pytest.raises(KeyError):
        service.get_document("recibidos/no-existe_archivo.txt")


def test_falta_variable_de_entorno_lanza_key_error_al_crear_el_servicio(monkeypatch):
    for key, value in ENV_VARS.items():
        if key != "OCI_USER_OCID":
            monkeypatch.setenv(key, value)
    monkeypatch.delenv("OCI_USER_OCID", raising=False)

    monkeypatch.setattr(service_module.oci.config, "validate_config", lambda config: None)
    monkeypatch.setattr(
        service_module.oci.object_storage, "ObjectStorageClient", ObjectStorageClientFalso
    )

    with pytest.raises(KeyError):
        OCIStorageService()

def test_upload_document_sanitiza_nombre_archivo(service):
    """El nombre usado en OCI no debe conservar rutas ni caracteres problemáticos."""

    object_name = service.upload_document(
        "DOC-2026-SEC001",
        b"contenido",
        "../carpeta/mi archivo clínico.pdf",
    )

    assert object_name == "recibidos/DOC-2026-SEC001_mi_archivo_cl_nico.pdf"


# --- MF-13: persistencia de resultados del flujo ---------------------------

@pytest.mark.parametrize(
    "estado,prefijo",
    [
        ("procesado_exitoso", "procesados/"),
        ("auditoria_humana", "auditoria_humana/"),
        ("error_tecnico", "errores_tecnicos/"),
    ],
)
def test_upload_y_get_resultado_por_estado(service, estado, prefijo):
    resultado = {"documento_id": "DOC-2026-RES001", "estado": estado, "resultado": {"ok": True}}

    object_name = service.upload_resultado("DOC-2026-RES001", estado, resultado)

    assert object_name == f"{prefijo}DOC-2026-RES001.json"

    recuperado = service.get_resultado("DOC-2026-RES001", estado)
    assert recuperado == resultado


def test_upload_resultado_sanitiza_documento_id(service):
    """El documento_id no debe permitir traversal de rutas dentro del bucket."""

    object_name = service.upload_resultado(
        "../../etc/passwd", "procesado_exitoso", {"x": 1}
    )

    assert object_name == "procesados/passwd.json"


def test_upload_resultado_estado_invalido_lanza_value_error(service):
    with pytest.raises(ValueError):
        service.upload_resultado("DOC-2026-RES002", "estado_inventado", {})


def test_get_resultado_estado_invalido_lanza_value_error(service):
    with pytest.raises(ValueError):
        service.get_resultado("DOC-2026-RES002", "estado_inventado")


def test_upload_resultado_no_toca_recibidos(service):
    """Guardar un resultado no debe crear ni modificar nada bajo recibidos/."""

    service.upload_document("DOC-2026-RES003", b"original", "informe.pdf")
    service.upload_resultado("DOC-2026-RES003", "procesado_exitoso", {"x": 1})

    objetos_recibidos = [
        clave for clave in service._client._objetos if clave[2].startswith("recibidos/")
    ]
    assert objetos_recibidos == [
        ("fake-namespace", "documentos-clinicos", "recibidos/DOC-2026-RES003_informe.pdf")
    ]
    assert service._client._objetos[objetos_recibidos[0]] == b"original"


def test_upload_resultado_propaga_fallo_de_oci_como_persistencia_error(service, monkeypatch):
    def put_object_falla(*args, **kwargs):
        raise RuntimeError("bucket no disponible")

    monkeypatch.setattr(service._client, "put_object", put_object_falla)

    with pytest.raises(PersistenciaOCIError):
        service.upload_resultado("DOC-2026-RES004", "procesado_exitoso", {"x": 1})


def test_upload_resultado_detecta_verificacion_fallida(service, monkeypatch):
    """Si lo que se recupera no coincide con lo enviado, debe fallar la verificación."""

    original_get_object = service._client.get_object

    def get_object_corrupto(*args, **kwargs):
        respuesta = original_get_object(*args, **kwargs)
        respuesta.data.content = b"contenido corrupto"
        return respuesta

    monkeypatch.setattr(service._client, "get_object", get_object_corrupto)

    with pytest.raises(PersistenciaOCIError):
        service.upload_resultado("DOC-2026-RES005", "procesado_exitoso", {"x": 1})
