"""
tests/test_gemini_client.py

MF-19: `generar_salida_estructurada` debe traducir los fallos TECNICOS
reales de la API de Gemini (429/cuota, 5xx, timeout, respuesta vacia por
bloqueo de seguridad) a `ErrorTecnicoProveedor`, y dejar cualquier otro
problema (respuesta que no cumple el schema) como el `ValueError` que ya
lanzaba antes de MF-19 -- esa distincion es la que usan classifier.py y
extractor.py para decidir si corresponde reintentar/hacer fallback.

No se llama a la API real de Gemini: se reemplaza `_build_client` por un
cliente falso controlable.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.services import gemini_client
from app.services.errores_llm import ErrorTecnicoProveedor


class _EsquemaDePrueba(BaseModel):
    ok: bool


class _ClienteFalso:
    """Sustituye a `genai.Client`: `models.generate_content` es controlable."""

    def __init__(self, comportamiento):
        self.models = SimpleNamespace(generate_content=comportamiento)


def _usar_cliente_falso(monkeypatch, comportamiento) -> None:
    monkeypatch.setenv("GEMINI_CLASSIFIER_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(
        gemini_client, "_build_client", lambda api_key_env: _ClienteFalso(comportamiento)
    )


def _llamar(**overrides):
    kwargs = {
        "api_key_env": "GEMINI_CLASSIFIER_API_KEY",
        "prompt": "prompt de prueba",
        "contenido_bytes": None,
        "mime_type": None,
        "schema": _EsquemaDePrueba,
        "model": "modelo-de-prueba",
    }
    kwargs.update(overrides)
    return gemini_client.generar_salida_estructurada(**kwargs)


class TestFallosTecnicos:
    def test_api_error_se_traduce_a_error_tecnico(self, monkeypatch):
        def _falla(*args, **kwargs):
            raise genai_errors.APIError(503, {"error": {"message": "service unavailable"}})

        _usar_cliente_falso(monkeypatch, _falla)

        with pytest.raises(ErrorTecnicoProveedor):
            _llamar()

    def test_error_429_cuota_se_traduce_a_error_tecnico(self, monkeypatch):
        def _falla(*args, **kwargs):
            raise genai_errors.APIError(429, {"error": {"message": "quota exceeded"}})

        _usar_cliente_falso(monkeypatch, _falla)

        with pytest.raises(ErrorTecnicoProveedor, match="429"):
            _llamar()

    def test_timeout_se_traduce_a_error_tecnico(self, monkeypatch):
        def _falla(*args, **kwargs):
            raise TimeoutError("timed out")

        _usar_cliente_falso(monkeypatch, _falla)

        with pytest.raises(ErrorTecnicoProveedor):
            _llamar()

    def test_respuesta_vacia_por_bloqueo_de_seguridad_es_error_tecnico(self, monkeypatch):
        respuesta = SimpleNamespace(parsed=None, text="", prompt_feedback="BLOCKED: safety")

        def _ok(*args, **kwargs):
            return respuesta

        _usar_cliente_falso(monkeypatch, _ok)

        with pytest.raises(ErrorTecnicoProveedor):
            _llamar()


class TestProblemasDeContenidoNoSonFalloTecnico:
    """
    Estos casos NO deben convertirse en `ErrorTecnicoProveedor`: son
    problemas de CONTENIDO (Gemini respondio, pero no cumplio el schema),
    y por lo tanto no deben disparar el fallback por si solos.
    """

    def test_sin_parsed_y_sin_prompt_feedback_es_value_error_no_tecnico(self, monkeypatch):
        respuesta = SimpleNamespace(parsed=None, text="esto no es json", prompt_feedback=None)

        def _ok(*args, **kwargs):
            return respuesta

        _usar_cliente_falso(monkeypatch, _ok)

        with pytest.raises(ValueError):
            _llamar()

    def test_respuesta_valida_se_devuelve_tal_cual(self, monkeypatch):
        esperado = _EsquemaDePrueba(ok=True)
        respuesta = SimpleNamespace(parsed=esperado, text='{"ok": true}', prompt_feedback=None)

        def _ok(*args, **kwargs):
            return respuesta

        _usar_cliente_falso(monkeypatch, _ok)

        assert _llamar() is esperado

    def test_sin_credenciales_no_se_confunde_con_fallo_tecnico(self, monkeypatch):
        """Un error de CONFIGURACION (falta la API key) no es un fallo
        tecnico del proveedor: sigue siendo RuntimeError, no debe
        disparar reintentos/fallback (esos no arreglarian nada)."""
        monkeypatch.delenv("GEMINI_CLASSIFIER_API_KEY", raising=False)

        with pytest.raises(RuntimeError):
            _llamar()
