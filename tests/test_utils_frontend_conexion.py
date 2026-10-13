"""MF-30: el aviso de API apagada no usa términos técnicos."""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frontend"))

import utils_frontend as u  # noqa: E402
from utils_frontend import ErrorClienteAPI  # noqa: E402


class _SesionSinConexion:
    def request(self, *args, **kwargs):
        raise requests.exceptions.ConnectionError("sin conexión")


def test_api_apagada_muestra_un_mensaje_sin_terminos_tecnicos(monkeypatch):
    monkeypatch.setattr(u, "obtener_sesion", lambda: _SesionSinConexion())
    with pytest.raises(ErrorClienteAPI) as error:
        u._solicitar("GET", "/documentos/pendientes")
    mensaje = str(error.value)
    assert "No hay conexión con la API" in mensaje
    assert u.API_BASE_URL in mensaje
    assert "uvicorn" not in mensaje

