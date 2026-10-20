"""
tests/test_groq_client.py

MF-19: valida el cliente de Groq (proveedor de fallback) de forma
aislada -- sin llamar a la API real de Groq (se reemplaza
`_build_client`/`groq.Groq` por un cliente falso controlable):

  1. Traduccion de fallos TECNICOS (429/cuota, 5xx, timeout, respuesta
     vacia) a `ErrorTecnicoProveedor`, igual que se exige para Gemini.
  2. `ProveedorGroq` cumple el protocolo `ProveedorLLM` del Extractor
     (mismo contrato que `ProveedorGemini`) -- incluye una prueba de
     integracion real con `extraer_datos_clinicos`.
  3. `generar_estructurado_con_groq` (modo estricto) para el Clasificador:
     JSON Schema correcto, respuesta valida, respuesta que no cumple el
     schema (problema de contenido, no tecnico).
  4. Rasterizacion de PDF a imagen (Groq no acepta PDF nativo -- ver
     docs/mf-19-fallback-tecnico.md), con un PDF real generado con
     PyMuPDF, y el limite de tamano de imagen documentado por Groq.
"""

from __future__ import annotations

from types import SimpleNamespace

import groq
import pytest

from app.agents.extractor import ProveedorLLM, extraer_datos_clinicos
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.documento import DocumentoEntrada
from app.services import groq_client
from app.services.errores_llm import ErrorTecnicoProveedor


def _pdf_de_prueba() -> bytes:
    import fitz  # PyMuPDF

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Receta de prueba MF-19")
    contenido = doc.tobytes()
    doc.close()
    return contenido


def _respuesta_con_texto(texto: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=texto))])


class _ClienteFalso:
    def __init__(self, comportamiento):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=comportamiento))


def _usar_cliente_falso(monkeypatch, comportamiento) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(groq_client, "_build_client", lambda api_key=None: _ClienteFalso(comportamiento))


# --------------------------------------------------------------------------
# 1. Traduccion de fallos tecnicos
# --------------------------------------------------------------------------
class TestFallosTecnicos:
    def test_error_429_se_traduce_a_error_tecnico(self, monkeypatch):
        def _falla(*a, **kw):
            request = SimpleNamespace(url="https://api.groq.com/x")
            response = SimpleNamespace(status_code=429, request=request, headers={})
            raise groq.RateLimitError("rate limit", response=response, body=None)

        _usar_cliente_falso(monkeypatch, _falla)

        with pytest.raises(ErrorTecnicoProveedor):
            groq_client.ProveedorGroq().generar("sistema", "usuario")

    def test_error_5xx_se_traduce_a_error_tecnico(self, monkeypatch):
        def _falla(*a, **kw):
            request = SimpleNamespace(url="https://api.groq.com/x")
            response = SimpleNamespace(status_code=503, request=request, headers={})
            raise groq.InternalServerError("service unavailable", response=response, body=None)

        _usar_cliente_falso(monkeypatch, _falla)

        with pytest.raises(ErrorTecnicoProveedor):
            groq_client.ProveedorGroq().generar("sistema", "usuario")

    def test_timeout_se_traduce_a_error_tecnico(self, monkeypatch):
        def _falla(*a, **kw):
            raise groq.APITimeoutError(request=SimpleNamespace(url="https://api.groq.com/x"))

        _usar_cliente_falso(monkeypatch, _falla)

        with pytest.raises(ErrorTecnicoProveedor):
            groq_client.ProveedorGroq().generar("sistema", "usuario")

    def test_respuesta_vacia_es_error_tecnico(self, monkeypatch):
        _usar_cliente_falso(monkeypatch, lambda *a, **kw: _respuesta_con_texto(""))

        with pytest.raises(ErrorTecnicoProveedor):
            groq_client.ProveedorGroq().generar("sistema", "usuario")

    def test_sin_groq_api_key_no_se_confunde_con_fallo_tecnico(self, monkeypatch):
        """Falta de configuracion (sin API key) es RuntimeError, no ErrorTecnicoProveedor."""
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(RuntimeError):
            groq_client.ProveedorGroq()


# --------------------------------------------------------------------------
# 2. ProveedorGroq cumple el protocolo ProveedorLLM del Extractor
# --------------------------------------------------------------------------
class TestProveedorGroqParaElExtractor:
    def test_generar_devuelve_texto_tal_cual(self, monkeypatch):
        _usar_cliente_falso(monkeypatch, lambda *a, **kw: _respuesta_con_texto('{"ok": true}'))

        resultado = groq_client.ProveedorGroq().generar("sistema", "usuario")

        assert resultado == '{"ok": true}'

    def test_envia_imagen_como_data_url_cuando_hay_contenido_bytes(self, monkeypatch):
        capturado = {}

        def _mock(*a, **kw):
            capturado.update(kw)
            return _respuesta_con_texto("ok")

        _usar_cliente_falso(monkeypatch, _mock)

        groq_client.ProveedorGroq().generar(
            "sistema", "usuario", contenido_bytes=b"\xff\xd8\xff\xe0", mime_type="image/jpeg"
        )

        mensaje_usuario = capturado["messages"][1]
        partes = mensaje_usuario["content"]
        assert any(p["type"] == "image_url" for p in partes)
        assert partes[-1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_extractor_completo_usa_groq_como_fallback(self, monkeypatch):
        """
        Integracion real con app.agents.extractor: el principal falla
        tecnicamente, ProveedorGroq (real, con el cliente HTTP mockeado)
        se usa como proveedor_fallback y el resultado respeta el
        contrato ExtraccionClinica -- transparente para el resto del flujo.
        """
        _usar_cliente_falso(
            monkeypatch,
            lambda *a, **kw: _respuesta_con_texto(
                '{"paciente": {"nombre_completo": "Ana Torres"}, '
                '"profesional": {"nombre_completo": "Dr. Luis Ramirez"}, '
                '"diagnosticos": [{"descripcion": "Faringitis aguda"}]}'
            ),
        )

        class _ProveedorPrincipalRoto:
            def generar(self, *a, **kw):
                raise ErrorTecnicoProveedor("Gemini caido (simulado)")

        documento = DocumentoEntrada(
            documento_id="DOC-TEST-GROQ-FALLBACK",
            tipo_archivo="JSON",
            canal_origen="test",
            nombre_archivo="ejemplo_receta_medica.txt",
            mime_type="text/plain",
            documento_texto="Paciente: Ana Torres. Medico: Dr. Luis Ramirez. Dx: Faringitis aguda.",
        )
        clasificacion = SimpleNamespace(
            tipo_documento=DocumentType.RECETA_MEDICA, especialidad="Medicina General"
        )

        resultado = extraer_datos_clinicos(
            documento=documento,
            clasificacion=clasificacion,
            proveedor=_ProveedorPrincipalRoto(),
            proveedor_fallback=groq_client.ProveedorGroq(),
        )

        assert resultado.paciente.nombre_completo == "Ana Torres"
        assert resultado.profesional.nombre_completo == "Dr. Luis Ramirez"

    def test_proveedor_groq_cumple_la_firma_del_protocolo(self):
        """
        ProveedorLLM no esta marcado @runtime_checkable (extractor.py, MF-06),
        asi que isinstance() no aplica aqui; se verifica la firma en su lugar
        -- el test de integracion de arriba ya prueba el comportamiento real.
        """
        import inspect

        firma_esperada = inspect.signature(ProveedorLLM.generar)
        firma_real = inspect.signature(groq_client.ProveedorGroq.generar)
        assert list(firma_esperada.parameters) == list(firma_real.parameters)


# --------------------------------------------------------------------------
# 3. Modo estricto para el Clasificador
# --------------------------------------------------------------------------
class TestGenerarEstructuradoConGroq:
    def test_schema_estricto_incluye_additional_properties_false(self):
        esquema = groq_client._json_schema_estricto(Classification)
        assert esquema["additionalProperties"] is False
        assert set(esquema["required"]) >= {
            "tipo_documento",
            "especialidad",
            "nivel_prioridad",
            "score_confianza_clasificacion",
            "justificacion",
        }

    def test_respuesta_valida_se_valida_contra_el_schema(self, monkeypatch):
        json_valido = (
            '{"tipo_documento": "Receta Medica", "especialidad": "Medicina General", '
            '"nivel_prioridad": "Rutina", "score_confianza_clasificacion": 0.9, '
            '"justificacion": "ok"}'
        )
        _usar_cliente_falso(monkeypatch, lambda *a, **kw: _respuesta_con_texto(json_valido))

        resultado = groq_client.generar_estructurado_con_groq(
            prompt="clasifica esto", contenido_bytes=None, mime_type=None, schema=Classification
        )

        assert isinstance(resultado, Classification)
        assert resultado.tipo_documento == DocumentType.RECETA_MEDICA

    def test_envia_el_response_format_json_schema_strict(self, monkeypatch):
        capturado = {}
        json_valido = (
            '{"tipo_documento": "Receta Medica", "especialidad": "x", '
            '"nivel_prioridad": "Rutina", "score_confianza_clasificacion": 0.5, "justificacion": "x"}'
        )

        def _mock(*a, **kw):
            capturado.update(kw)
            return _respuesta_con_texto(json_valido)

        _usar_cliente_falso(monkeypatch, _mock)

        groq_client.generar_estructurado_con_groq(
            prompt="clasifica esto", contenido_bytes=None, mime_type=None, schema=Classification
        )

        assert capturado["response_format"]["type"] == "json_schema"
        assert capturado["response_format"]["json_schema"]["strict"] is True

    def test_respuesta_que_no_cumple_el_schema_es_value_error_no_fallo_tecnico(self, monkeypatch):
        """Pese al modo estricto, si Groq devuelve algo invalido es un problema de
        CONTENIDO (ValueError), no un fallo tecnico -- no debe confundirse con
        ErrorTecnicoProveedor."""
        _usar_cliente_falso(monkeypatch, lambda *a, **kw: _respuesta_con_texto('{"campo": "no existe"}'))

        with pytest.raises(ValueError):
            groq_client.generar_estructurado_con_groq(
                prompt="clasifica esto", contenido_bytes=None, mime_type=None, schema=Classification
            )

    def test_fallo_tecnico_de_groq_se_propaga_como_tal(self, monkeypatch):
        def _falla(*a, **kw):
            request = SimpleNamespace(url="https://api.groq.com/x")
            response = SimpleNamespace(status_code=429, request=request, headers={})
            raise groq.RateLimitError("rate limit", response=response, body=None)

        _usar_cliente_falso(monkeypatch, _falla)

        with pytest.raises(ErrorTecnicoProveedor):
            groq_client.generar_estructurado_con_groq(
                prompt="clasifica esto", contenido_bytes=None, mime_type=None, schema=Classification
            )


# --------------------------------------------------------------------------
# 4. PDF -> imagen (limitacion conocida, ver docstring del modulo) y limites
# --------------------------------------------------------------------------
class TestRasterizacionDePdfYLimites:
    def test_pdf_se_rasteriza_a_png_valido(self):
        png = groq_client._pdf_a_png_primera_pagina(_pdf_de_prueba())
        assert png.startswith(b"\x89PNG\r\n\x1a\n")

    def test_pdf_sin_paginas_lanza_value_error_no_fallo_tecnico(self, monkeypatch):
        """
        PyMuPDF no permite serializar un PDF de 0 paginas (no es un archivo
        representable) y `page_count` es de solo lectura, asi que se
        simula con un objeto minimo en vez de un fitz.Document real.
        """
        import fitz

        class _DocumentoVacioFalso:
            page_count = 0

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(fitz, "open", lambda **kw: _DocumentoVacioFalso())

        with pytest.raises(ValueError):
            groq_client._pdf_a_png_primera_pagina(b"contenido-irrelevante-aqui")

    def test_imagen_que_no_es_pdf_se_envia_sin_rasterizar(self):
        datos, mime = groq_client._preparar_imagen(b"\xff\xd8\xff\xe0-jpg-simulado", "image/jpeg")
        assert datos == b"\xff\xd8\xff\xe0-jpg-simulado"
        assert mime == "image/jpeg"

    def test_imagen_que_supera_el_limite_de_groq_es_error_tecnico(self, monkeypatch):
        monkeypatch.setattr(groq_client, "_LIMITE_BYTES_IMAGEN", 10)  # fuerza el limite en la prueba

        with pytest.raises(ErrorTecnicoProveedor, match="20MB|10"):
            groq_client._construir_contenido_usuario(
                "prompt", b"x" * 100, "image/jpeg"
            )

    def test_documento_pdf_real_se_puede_enviar_de_extremo_a_extremo(self, monkeypatch):
        """El PDF se rasteriza y se manda como image_url -- no como PDF nativo."""
        capturado = {}

        def _mock(*a, **kw):
            capturado.update(kw)
            return _respuesta_con_texto("ok")

        _usar_cliente_falso(monkeypatch, _mock)

        groq_client.ProveedorGroq().generar(
            "sistema", "usuario", contenido_bytes=_pdf_de_prueba(), mime_type="application/pdf"
        )

        url_imagen = capturado["messages"][1]["content"][-1]["image_url"]["url"]
        assert url_imagen.startswith("data:image/png;base64,")
