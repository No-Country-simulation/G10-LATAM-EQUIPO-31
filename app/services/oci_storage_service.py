import os
import re
import oci
from dotenv import load_dotenv

load_dotenv()

RECIBIDOS_PREFIX = "recibidos/"

def _sanitizar_nombre_archivo(filename: str) -> str:
    """Limpia el nombre del archivo antes de usarlo como object_name en OCI."""
    nombre = filename.replace("\\", "/").split("/")[-1]
    nombre = re.sub(r"[^A-Za-z0-9._-]", "_", nombre)
    return nombre or "archivo"

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
        filename_seguro = _sanitizar_nombre_archivo(filename)
        object_name = f"{RECIBIDOS_PREFIX}{document_id}_{filename_seguro}"
        
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
