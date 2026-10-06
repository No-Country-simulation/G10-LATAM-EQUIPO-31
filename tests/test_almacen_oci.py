"""MF-12: adaptador AlmacenOCI contra un cliente de OCI simulado (sin red ni credenciales)."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import oci
import pytest

from app.services.almacen_oci import AlmacenOCI

FECHA = datetime(2026, 10, 1, tzinfo=timezone.utc)


class ClienteFalso:
    def __init__(self):
        self.objetos = {}
        self.llamadas_list = []

    def list_objects(self, namespace, bucket, prefix, start, fields, limit):
        self.llamadas_list.append(start)
        nombres = sorted(n for n in self.objetos if n.startswith(prefix))
        desde = int(start or 0)
        pagina = nombres[desde: desde + 2]                       # páginas de 2 para forzar la paginación
        siguiente = str(desde + 2) if desde + 2 < len(nombres) else None
        objetos = [SimpleNamespace(name=n, time_modified=FECHA, time_created=FECHA) for n in pagina]
        return SimpleNamespace(data=SimpleNamespace(objects=objetos, next_start_with=siguiente))

    def get_object(self, namespace, bucket, nombre):
        return SimpleNamespace(data=SimpleNamespace(content=self.objetos[nombre]))

    def put_object(self, namespace_name, bucket_name, object_name, put_object_body, content_type, if_none_match):
        assert (namespace_name, bucket_name, content_type, if_none_match) == ("ns", "bucket", "application/json", "*")
        if object_name in self.objetos:
            raise oci.exceptions.ServiceError(412, "IfNoneMatchFailed", {}, "ya existe")
        self.objetos[object_name] = put_object_body


@pytest.fixture
def almacen():
    cliente = ClienteFalso()
    servicio = SimpleNamespace(_client=cliente, _namespace="ns", _bucket_name="bucket")
    return AlmacenOCI(servicio), cliente


def test_listar_recorre_todas_las_paginas(almacen):
    a, cliente = almacen
    for i in range(5):
        cliente.objetos[f"historial/D/{i}.json"] = b"{}"
    cliente.objetos["otro/x.json"] = b"{}"
    nombres = [n for n, _ in a.listar("historial/")]
    assert nombres == [f"historial/D/{i}.json" for i in range(5)] and len(cliente.llamadas_list) == 3
    assert all(f == FECHA for _, f in a.listar("historial/"))


def test_escribir_json_nuevo_guarda_utf8_y_no_sobrescribe(almacen):
    a, cliente = almacen
    a.escribir_json_nuevo("historial/D/1_decision.json", {"notas": "dosis ilegible: señor Ñandú"})
    assert a.leer_json("historial/D/1_decision.json") == {"notas": "dosis ilegible: señor Ñandú"}
    original = cliente.objetos["historial/D/1_decision.json"]
    with pytest.raises(FileExistsError):                       # 412 de OCI -> FileExistsError
        a.escribir_json_nuevo("historial/D/1_decision.json", {"notas": "otra"})
    assert cliente.objetos["historial/D/1_decision.json"] == original


def test_otros_errores_de_oci_no_se_ocultan(almacen):
    a, cliente = almacen

    def fallar(**kw):
        raise oci.exceptions.ServiceError(500, "InternalError", {}, "falla del bucket")

    cliente.put_object = fallar
    with pytest.raises(oci.exceptions.ServiceError):
        a.escribir_json_nuevo("historial/D/1_decision.json", {})
