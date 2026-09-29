import json
import os
import re
import oci
from dotenv import load_dotenv

load_dotenv()

RECIBIDOS_PREFIX = "recibidos/"

# Único lugar que mapea el estado de un resultado a su carpeta en el bucket.
# Sumar un estado nuevo (p. ej. "urgente") es agregar una entrada acá; nada
# más del servicio depende de los nombres de carpeta.
ESTADOS_A_PREFIJO = {
    "procesado_exitoso": "procesados/",
    "auditoria_humana": "auditoria_humana/",
    "error_tecnico": "errores_tecnicos/",
}


class PersistenciaOCIError(Exception):
    """Error al guardar o verificar un resultado en OCI Object Storage."""


def _sanitizar_nombre_archivo(filename: str) -> str:
    """Limpia el nombre del archivo antes de usarlo como object_name en OCI."""
    nombre = filename.replace("\\", "/").split("/")[-1]
    nombre = re.sub(r"[^A-Za-z0-9._-]", "_", nombre)
    return nombre or "archivo"


def _object_name_resultado(documento_id: str, estado: str) -> str:
    if estado not in ESTADOS_A_PREFIJO:
        raise ValueError(
            f"Estado de resultado no soportado: {estado!r}. "
            f"Valores válidos: {sorted(ESTADOS_A_PREFIJO)}"
        )
    documento_id_seguro = _sanitizar_nombre_archivo(documento_id)
    return f"{ESTADOS_A_PREFIJO[estado]}{documento_id_seguro}.json"


class OCIStorageService:
    """Servicio de conexión con OCI Object Storage para el bucket de documentos clínicos."""

    def __init__(self):
        self._config = {
            "user": os.environ["OCI_USER_OCID"],
            "tenancy": os.environ["OCI_TENANCY_OCID"],
            "fingerprint": os.environ["OCI_FINGERPRINT"],
            "key_file": os.environ["OCI_PRIVATE_KEY_PATH"],
            "region": os.environ["OCI_REGION"],
        }
        oci.config.validate_config(self._config)

        self._client = oci.object_storage.ObjectStorageClient(self._config)
        self._namespace = os.environ["OCI_NAMESPACE"]
        self._bucket_name = os.environ["OCI_BUCKET_NAME"]

    def upload_document(self, document_id: str, content: bytes, filename: str) -> str:
        """Sube un documento a la carpeta recibidos/ del bucket y devuelve el nombre del objeto."""
        document_id_seguro = _sanitizar_nombre_archivo(document_id)
        filename_seguro = _sanitizar_nombre_archivo(filename)
        object_name = f"{RECIBIDOS_PREFIX}{document_id_seguro}_{filename_seguro}"

        self._client.put_object(
            namespace_name=self._namespace,
            bucket_name=self._bucket_name,
            object_name=object_name,
            put_object_body=content,
        )
        return object_name

    def get_document(self, object_name: str) -> bytes:
        """Recupera el contenido de un documento ya almacenado en el bucket."""
        response = self._client.get_object(
            namespace_name=self._namespace,
            bucket_name=self._bucket_name,
            object_name=object_name,
        )
        return response.data.content

    def upload_resultado(self, documento_id: str, estado: str, resultado: dict) -> str:
        """
        Guarda el resultado del flujo (el estado completo que llegó del
        grafo) como JSON, en la carpeta que corresponde a `estado`
        (ver ESTADOS_A_PREFIJO). Nunca escribe en recibidos/, así que no
        puede sobrescribir el documento original.

        Verifica la escritura recuperando el objeto inmediatamente después
        de subirlo; si la subida falla o el contenido recuperado no
        coincide, levanta PersistenciaOCIError.
        """
        object_name = _object_name_resultado(documento_id, estado)
        contenido = json.dumps(resultado, ensure_ascii=False, default=str).encode("utf-8")

        try:
            self._client.put_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket_name,
                object_name=object_name,
                put_object_body=contenido,
            )
            recuperado = self._client.get_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket_name,
                object_name=object_name,
            ).data.content
        except Exception as exc:
            raise PersistenciaOCIError(
                f"No se pudo guardar/verificar el resultado de "
                f"documento_id={documento_id!r} (estado={estado!r}) en OCI: {exc}"
            ) from exc

        if recuperado != contenido:
            raise PersistenciaOCIError(
                f"Verificación de escritura falló para {object_name}: "
                "el contenido recuperado no coincide con el enviado."
            )

        return object_name

    def get_resultado(self, documento_id: str, estado: str) -> dict:
        """Recupera y deserializa el resultado guardado para documento_id/estado."""
        object_name = _object_name_resultado(documento_id, estado)
        contenido = self.get_document(object_name)
        return json.loads(contenido.decode("utf-8"))
