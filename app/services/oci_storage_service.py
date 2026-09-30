import json
import os
import re
from datetime import datetime

import oci
from dotenv import load_dotenv

load_dotenv()

RECIBIDOS_PREFIX = "recibidos/"
HISTORIAL_PREFIX = "historial/"

ESTADO_ERROR_TECNICO = "error_tecnico"

# Único lugar que mapea el estado de un resultado a su carpeta en el bucket.
# Las claves de procesados/ coinciden con los valores de `destino_principal`
# que define el contrato de MF-11 ("estandar", "urgente", "revision_humana").
# Sumar un destino nuevo es agregar una entrada acá; nada más del servicio
# depende de los nombres de carpeta.
ESTADOS_A_PREFIJO = {
    "estandar": "procesados/estandar/",
    "urgente": "procesados/urgente/",
    "revision_humana": "procesados/revision_humana/",
    ESTADO_ERROR_TECNICO: "errores_tecnicos/",
}

# Valores de `destino_principal` (MF-11) que se aceptan tal cual como estado:
# todos los estados salvo el de error técnico, que solo lo decide la API.
DESTINOS_PRINCIPALES = frozenset(ESTADOS_A_PREFIJO) - {ESTADO_ERROR_TECNICO}


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


def _id_temporal(momento: datetime) -> str:
    """
    Convierte un datetime en un identificador de archivo seguro y
    ordenable cronológicamente por nombre (año-mes-día-hora-minuto-
    segundo-microsegundos, sin separadores: p. ej. 20260930T153012456789).
    Se usa como nombre de archivo del historial (MF-15) en vez del ISO
    8601 con separadores (":", "+"), que `_sanitizar_nombre_archivo`
    convertiría en guiones bajos poco legibles.
    """
    return momento.strftime("%Y%m%dT%H%M%S%f")


def _object_name_historial(documento_id: str, id_temporal: str) -> str:
    documento_id_seguro = _sanitizar_nombre_archivo(documento_id)
    return f"{HISTORIAL_PREFIX}{documento_id_seguro}/{id_temporal}.json"


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

    def upload_historial(self, documento_id: str, momento: datetime, evento: dict) -> str:
        """
        Guarda un EVENTO de historial de triaje (MF-15) bajo
        `historial/{documento_id}/{momento}.json`. A diferencia de
        `upload_resultado` (que pisa el resultado anterior del mismo
        documento_id), cada llamada con un `momento` distinto crea un
        objeto nuevo: el historial de reprocesos se conserva completo.

        Mismo patrón de verificación que `upload_resultado`: sube y
        vuelve a leer inmediatamente: si la subida falla o el contenido
        recuperado no coincide, levanta PersistenciaOCIError.
        """
        object_name = _object_name_historial(documento_id, _id_temporal(momento))
        contenido = json.dumps(evento, ensure_ascii=False, default=str).encode("utf-8")

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
                f"No se pudo guardar/verificar el evento de historial de "
                f"documento_id={documento_id!r} en OCI: {exc}"
            ) from exc

        if recuperado != contenido:
            raise PersistenciaOCIError(
                f"Verificación de escritura falló para {object_name}: "
                "el contenido recuperado no coincide con el enviado."
            )

        return object_name

    def get_historial(self, object_name: str) -> dict:
        """
        Recupera y deserializa un evento de historial ya guardado, a
        partir del `object_name` devuelto por `upload_historial` (no se
        reconstruye desde documento_id/momento: evita un desfasaje de
        microsegundos entre el momento de guardar y el de reconstruir
        el nombre del archivo).
        """
        contenido = self.get_document(object_name)
        return json.loads(contenido.decode("utf-8"))
