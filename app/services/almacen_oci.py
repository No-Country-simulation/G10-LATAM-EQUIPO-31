"""
app/services/almacen_oci.py  (MF-12)

Adaptador que expone a `OCIStorageService` con la interfaz mínima de `auditoria_eventos.Almacen`
(listar, leer_json, escribir_json_nuevo). Usa los atributos internos del servicio (`_client`, `_namespace`,
`_bucket_name`) para no tocar su código. PENDIENTE (apoyo de persistencia/OCI): convertirlo en métodos públicos
del propio servicio (`listar_objetos`, `get_json`, `put_json_si_no_existe`) y, si se desea, aplicar la misma
verificación de relectura que usa `upload_historial`.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import oci

from app.services.oci_storage_service import OCIStorageService


class AlmacenOCI:
    def __init__(self, servicio: OCIStorageService):
        self._cliente = servicio._client
        self._namespace = servicio._namespace
        self._bucket = servicio._bucket_name

    def listar(self, prefijo: str) -> list[tuple[str, datetime | None]]:
        salida: list[tuple[str, datetime | None]] = []
        inicio = None
        while True:
            r = self._cliente.list_objects(
                self._namespace, self._bucket, prefix=prefijo, start=inicio,
                fields="name,timeCreated,timeModified", limit=1000,
            )
            salida += [(o.name, getattr(o, "time_modified", None) or o.time_created) for o in r.data.objects]
            inicio = r.data.next_start_with
            if not inicio:
                return salida

    def leer_json(self, nombre: str) -> dict[str, Any]:
        r = self._cliente.get_object(self._namespace, self._bucket, nombre)
        return json.loads(r.data.content.decode("utf-8"))

    def escribir_json_nuevo(self, nombre: str, contenido: dict[str, Any]) -> None:
        try:
            self._cliente.put_object(
                namespace_name=self._namespace,
                bucket_name=self._bucket,
                object_name=nombre,
                put_object_body=json.dumps(contenido, ensure_ascii=False, default=str).encode("utf-8"),
                content_type="application/json",
                if_none_match="*",  # no sobrescribe: 412 si ya existe
            )
        except oci.exceptions.ServiceError as exc:
            if exc.status == 412:
                raise FileExistsError(nombre) from exc
            raise
