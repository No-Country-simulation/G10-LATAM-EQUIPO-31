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
from datetime import datetime, timedelta, timezone

import oci
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
        self._content_types = {}
        self._fechas = {}

    def fijar_fechas(self, namespace_name, bucket_name, object_name, time_created=None, time_modified=None):
        """Ayuda de test: asigna timeCreated/timeModified a un objeto ya subido."""
        clave = (namespace_name, bucket_name, object_name)
        self._fechas[clave] = (time_created, time_modified)

    def put_object(
        self,
        namespace_name,
        bucket_name,
        object_name,
        put_object_body,
        if_none_match=None,
        content_type=None,
    ):
        clave = (namespace_name, bucket_name, object_name)
        if if_none_match == "*" and clave in self._objetos:
            raise oci.exceptions.ServiceError(
                status=412,
                code="IfNoneMatchFailed",
                headers={},
                message=f"El objeto {object_name!r} ya existe.",
            )
        self._objetos[clave] = put_object_body
        self._content_types[clave] = content_type
        self._fechas.setdefault(clave, (None, None))

    def get_object(self, namespace_name, bucket_name, object_name):
        clave = (namespace_name, bucket_name, object_name)
        contenido = self._objetos[clave]
        return RespuestaFalsa(contenido)

    def list_objects(self, namespace_name, bucket_name, prefix=None, fields=None, start=None):
        prefijo = prefix or ""
        nombres = sorted(
            nombre
            for (ns, bucket, nombre) in self._objetos
            if ns == namespace_name and bucket == bucket_name and nombre.startswith(prefijo)
        )
        if start:
            nombres = [nombre for nombre in nombres if nombre >= start]
        objetos = []
        for nombre in nombres:
            clave = (namespace_name, bucket_name, nombre)
            time_created, time_modified = self._fechas.get(clave, (None, None))
            objetos.append(
                ObjectSummaryFalso(nombre, time_created=time_created, time_modified=time_modified)
            )
        return RespuestaListObjetosFalsa(objetos, next_start_with=None)


class RespuestaFalsa:
    def __init__(self, content: bytes):
        self.data = DatosFalsos(content)


class DatosFalsos:
    def __init__(self, content: bytes):
        self.content = content


class RespuestaListObjetosFalsa:
    def __init__(self, objetos, next_start_with):
        self.data = ListObjectsFalso(objetos, next_start_with)


class ListObjectsFalso:
    def __init__(self, objetos, next_start_with):
        self.objects = objetos
        self.next_start_with = next_start_with


class ObjectSummaryFalso:
    def __init__(self, name, time_created=None, time_modified=None):
        self.name = name
        self.time_created = time_created
        self.time_modified = time_modified


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


def test_upload_document_sanitiza_document_id(service):
    """El document_id tampoco debe permitir traversal de rutas en OCI."""

    object_name = service.upload_document(
        "../../etc/passwd",
        b"contenido",
        "informe.pdf",
    )

    assert object_name == "recibidos/passwd_informe.pdf"


# --- MF-13: persistencia de resultados del flujo ---------------------------

@pytest.mark.parametrize(
    "estado,prefijo",
    [
        ("estandar", "procesados/estandar/"),
        ("urgente", "procesados/urgente/"),
        ("revision_humana", "procesados/revision_humana/"),
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
        "../../etc/passwd", "estandar", {"x": 1}
    )

    assert object_name == "procesados/estandar/passwd.json"


def test_upload_resultado_estado_invalido_lanza_value_error(service):
    with pytest.raises(ValueError):
        service.upload_resultado("DOC-2026-RES002", "estado_inventado", {})


def test_get_resultado_estado_invalido_lanza_value_error(service):
    with pytest.raises(ValueError):
        service.get_resultado("DOC-2026-RES002", "estado_inventado")


def test_upload_resultado_no_toca_recibidos(service):
    """Guardar un resultado no debe crear ni modificar nada bajo recibidos/."""

    service.upload_document("DOC-2026-RES003", b"original", "informe.pdf")
    service.upload_resultado("DOC-2026-RES003", "estandar", {"x": 1})

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
        service.upload_resultado("DOC-2026-RES004", "estandar", {"x": 1})


def test_upload_resultado_detecta_verificacion_fallida(service, monkeypatch):
    """Si lo que se recupera no coincide con lo enviado, debe fallar la verificación."""

    original_get_object = service._client.get_object

    def get_object_corrupto(*args, **kwargs):
        respuesta = original_get_object(*args, **kwargs)
        respuesta.data.content = b"contenido corrupto"
        return respuesta

    monkeypatch.setattr(service._client, "get_object", get_object_corrupto)

    with pytest.raises(PersistenciaOCIError):
        service.upload_resultado("DOC-2026-RES005", "estandar", {"x": 1})


# --- MF-15: historial de triaje ---------------------------------------------

MOMENTO_PRUEBA = datetime(2026, 9, 30, 15, 30, 12, 456789, tzinfo=timezone.utc)


def test_upload_historial_devuelve_object_name_con_prefijo_historial(service):
    object_name = service.upload_historial(
        "DOC-2026-HIST001", MOMENTO_PRUEBA, {"documento_id": "DOC-2026-HIST001"}
    )

    assert object_name == "historial/DOC-2026-HIST001/20260930T153012456789.json"


def test_upload_y_get_historial_recuperan_el_mismo_contenido(service):
    evento = {"documento_id": "DOC-2026-HIST002", "estado": "estandar", "resumen": {"x": 1}}

    object_name = service.upload_historial("DOC-2026-HIST002", MOMENTO_PRUEBA, evento)
    recuperado = service.get_historial(object_name)

    assert recuperado == evento


def test_upload_historial_dos_momentos_distintos_no_se_pisan(service):
    """El mismo documento_id, reprocesado, debe generar DOS objetos
    distintos (a diferencia de upload_resultado, que pisa)."""

    momento_1 = MOMENTO_PRUEBA
    momento_2 = MOMENTO_PRUEBA + timedelta(seconds=1)

    object_name_1 = service.upload_historial(
        "DOC-2026-HIST003", momento_1, {"intento": 1}
    )
    object_name_2 = service.upload_historial(
        "DOC-2026-HIST003", momento_2, {"intento": 2}
    )

    assert object_name_1 != object_name_2
    assert service.get_historial(object_name_1) == {"intento": 1}
    assert service.get_historial(object_name_2) == {"intento": 2}


def test_upload_historial_sanitiza_documento_id(service):
    """El documento_id no debe permitir traversal de rutas dentro del bucket."""

    object_name = service.upload_historial(
        "../../etc/passwd", MOMENTO_PRUEBA, {"x": 1}
    )

    assert object_name == "historial/passwd/20260930T153012456789.json"


def test_upload_historial_no_toca_procesados_ni_recibidos(service):
    """Guardar un evento de historial no debe crear ni modificar nada bajo
    recibidos/ ni procesados/*."""

    service.upload_document("DOC-2026-HIST004", b"original", "informe.pdf")
    service.upload_resultado("DOC-2026-HIST004", "estandar", {"x": 1})
    service.upload_historial("DOC-2026-HIST004", MOMENTO_PRUEBA, {"y": 2})

    claves_historial = [
        clave for clave in service._client._objetos if clave[2].startswith("historial/")
    ]
    assert claves_historial == [
        (
            "fake-namespace",
            "documentos-clinicos",
            "historial/DOC-2026-HIST004/20260930T153012456789.json",
        )
    ]


def test_upload_historial_propaga_fallo_de_oci_como_persistencia_error(service, monkeypatch):
    def put_object_falla(*args, **kwargs):
        raise RuntimeError("bucket no disponible")

    monkeypatch.setattr(service._client, "put_object", put_object_falla)

    with pytest.raises(PersistenciaOCIError):
        service.upload_historial("DOC-2026-HIST005", MOMENTO_PRUEBA, {"x": 1})


def test_upload_historial_detecta_verificacion_fallida(service, monkeypatch):
    original_get_object = service._client.get_object

    def get_object_corrupto(*args, **kwargs):
        respuesta = original_get_object(*args, **kwargs)
        respuesta.data.content = b"contenido corrupto"
        return respuesta

    monkeypatch.setattr(service._client, "get_object", get_object_corrupto)

    with pytest.raises(PersistenciaOCIError):
        service.upload_historial("DOC-2026-HIST006", MOMENTO_PRUEBA, {"x": 1})


# --- MF-12: listar / leer_json / escribir_json_nuevo -----------------------


def test_listar_devuelve_nombre_y_fecha_bajo_el_prefijo(service):
    service.upload_document("DOC-2026-LIST001", b"a", "informe.pdf")
    service.upload_resultado("DOC-2026-LIST001", "estandar", {"x": 1})
    service.upload_resultado("DOC-2026-LIST002", "urgente", {"x": 2})

    creado_1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    modificado_1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    creado_2 = datetime(2026, 1, 3, tzinfo=timezone.utc)
    service._client.fijar_fechas(
        "fake-namespace",
        "documentos-clinicos",
        "procesados/estandar/DOC-2026-LIST001.json",
        time_created=creado_1,
        time_modified=modificado_1,
    )
    service._client.fijar_fechas(
        "fake-namespace",
        "documentos-clinicos",
        "procesados/urgente/DOC-2026-LIST002.json",
        time_created=creado_2,
        time_modified=None,
    )

    objetos = service.listar("procesados/")

    assert sorted(objetos) == [
        ("procesados/estandar/DOC-2026-LIST001.json", modificado_1),
        ("procesados/urgente/DOC-2026-LIST002.json", creado_2),
    ]


def test_listar_usa_time_created_si_no_hay_time_modified(service):
    """Si el objeto no tiene timeModified (p.ej. nunca se sobrescribió),
    listar() debe devolver timeCreated en su lugar."""

    service.upload_resultado("DOC-2026-LIST003", "estandar", {"x": 1})
    creado = datetime(2026, 2, 1, tzinfo=timezone.utc)
    service._client.fijar_fechas(
        "fake-namespace",
        "documentos-clinicos",
        "procesados/estandar/DOC-2026-LIST003.json",
        time_created=creado,
        time_modified=None,
    )

    objetos = service.listar("procesados/estandar/")

    assert objetos == [("procesados/estandar/DOC-2026-LIST003.json", creado)]


def test_listar_carpeta_vacia_devuelve_lista_vacia(service):
    assert service.listar("no/existe/") == []


def test_listar_pasa_fields_a_list_objects(service, monkeypatch):
    """listar() debe pedir explícitamente timeCreated/timeModified, ya que
    OCI por defecto solo devuelve el nombre del objeto."""

    llamadas = []
    original_list_objects = service._client.list_objects

    def list_objects_espia(*args, **kwargs):
        llamadas.append(kwargs.get("fields"))
        return original_list_objects(*args, **kwargs)

    monkeypatch.setattr(service._client, "list_objects", list_objects_espia)

    service.listar("no/existe/")

    assert llamadas == ["name,timeCreated,timeModified"]


def test_listar_sigue_la_paginacion_de_oci(service, monkeypatch):
    """ListObjects de OCI devuelve como máximo 1000 objetos por página;
    listar() debe seguir `next_start_with` hasta que sea None."""

    fecha_a = datetime(2026, 3, 1, tzinfo=timezone.utc)
    fecha_b = datetime(2026, 3, 2, tzinfo=timezone.utc)
    paginas = [
        RespuestaListObjetosFalsa(
            [ObjectSummaryFalso("historial/DOC/a.json", time_modified=fecha_a)],
            next_start_with="historial/DOC/b.json",
        ),
        RespuestaListObjetosFalsa(
            [ObjectSummaryFalso("historial/DOC/b.json", time_modified=fecha_b)],
            next_start_with=None,
        ),
    ]
    llamadas = []

    def list_objects_paginado(namespace_name, bucket_name, prefix=None, fields=None, start=None):
        llamadas.append(start)
        return paginas[len(llamadas) - 1]

    monkeypatch.setattr(service._client, "list_objects", list_objects_paginado)

    objetos = service.listar("historial/DOC/")

    assert objetos == [
        ("historial/DOC/a.json", fecha_a),
        ("historial/DOC/b.json", fecha_b),
    ]
    assert llamadas == [None, "historial/DOC/b.json"]


def test_leer_json_caso_feliz(service):
    datos = {"documento_id": "DOC-2026-LEER001", "x": 1}
    service.escribir_json_nuevo("historial/DOC-2026-LEER001/evento.json", datos)

    assert service.leer_json("historial/DOC-2026-LEER001/evento.json") == datos


def test_leer_json_archivo_inexistente_lanza_error_claro(service):
    with pytest.raises(PersistenciaOCIError):
        service.leer_json("historial/no-existe/evento.json")


def test_escribir_json_nuevo_caso_feliz(service):
    clave = service.escribir_json_nuevo(
        "historial/DOC-2026-ESCR001/evento.json", {"x": 1}
    )

    assert clave == "historial/DOC-2026-ESCR001/evento.json"
    assert service.leer_json(clave) == {"x": 1}


def test_escribir_json_nuevo_usa_content_type_json(service):
    clave = service.escribir_json_nuevo(
        "historial/DOC-2026-ESCR004/evento.json", {"x": 1}
    )

    assert service._client._content_types[
        ("fake-namespace", "documentos-clinicos", clave)
    ] == "application/json"


def test_escribir_json_nuevo_si_ya_existe_lanza_file_exists_error(service):
    clave = "historial/DOC-2026-ESCR002/evento.json"
    service.escribir_json_nuevo(clave, {"x": 1})

    with pytest.raises(FileExistsError):
        service.escribir_json_nuevo(clave, {"x": 2})

    assert service.leer_json(clave) == {"x": 1}


def test_escribir_json_nuevo_otro_error_de_oci_lanza_persistencia_error(service, monkeypatch):
    def put_object_falla(*args, **kwargs):
        raise oci.exceptions.ServiceError(
            status=500, code="InternalError", headers={}, message="bucket no disponible"
        )

    monkeypatch.setattr(service._client, "put_object", put_object_falla)

    with pytest.raises(PersistenciaOCIError):
        service.escribir_json_nuevo("historial/DOC-2026-ESCR003/evento.json", {"x": 1})
