"""
tests/test_oci_storage_service.py

Pruebas del servicio de conexión con OCI Object Storage (MF-04).
Usa un cliente OCI falso en memoria para no depender de credenciales
reales ni de red.

Ejecutar desde la raíz del repositorio:
    pytest tests/test_oci_storage_service.py -v
"""
import pytest

from app.services import oci_storage_service as service_module
from app.services.oci_storage_service import OCIStorageService

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
