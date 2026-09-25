"""
tests/test_extractor.py

Cubre reintentos por JSON inválido y fallback técnico del extractor (MF-06).

Adaptado en MF-08 para utilizar DocumentoEntrada de MF-02 y soportar
el flujo multimodal integrado.
"""

from __future__ import annotations

import json

from app.agents.extractor import (
    MAX_INTENTOS,
    ErrorTecnicoProveedor,
    ResultadoClasificacionMock,
    extraer_datos_clinicos,
)
from app.schemas.documento import DocumentoEntrada


def _clasificacion() -> ResultadoClasificacionMock:
    return ResultadoClasificacionMock(
        tipo_documento="ORDEN_MEDICA",
        especialidad="Medicina Interna",
    )


def _documento() -> DocumentoEntrada:
    """Documento de texto utilizado por las pruebas unitarias del extractor."""
    return DocumentoEntrada(
        documento_id="DOC-TEST-EXT-001",
        tipo_archivo="JSON",
        canal_origen="test",
        nombre_archivo="orden_medica.txt",
        mime_type="text/plain",
        documento_texto="Documento clínico de prueba.",
    )


def _json_valido(observaciones: str = "ok") -> str:
    return json.dumps(
        {
            "paciente": {
                "nombre_completo": "Ana Restrepo",
                "tipo_documento": "CC",
                "numero_documento": "123",
                "edad": 30,
                "sexo": "F",
            },
            "profesional": {
                "nombre_completo": "Dr. X",
                "registro_profesional": None,
                "especialidad": None,
                "institucion": None,
            },
            "diagnosticos": [
                {
                    "descripcion": "algo",
                    "codigo_cie10": None,
                    "tipo": None,
                }
            ],
            "medicamentos": [],
            "estudios_solicitados": [],
            "procedimientos_solicitados": [],
            "nivel_urgencia": None,
            "senales_gravedad": [],
            "fecha_documento": None,
            "observaciones": observaciones,
            "campos_no_encontrados": [],
        }
    )


class ProveedorSiempreInvalido:
    def __init__(self):
        self.llamadas = 0

    def generar(
        self,
        prompt_sistema: str,
        prompt_usuario: str,
        contenido_bytes: bytes | None = None,
        mime_type: str | None = None,
    ) -> str:
        self.llamadas += 1
        return "esto no es json"


class ProveedorFalloTecnico:
    def __init__(self):
        self.llamadas = 0

    def generar(
        self,
        prompt_sistema: str,
        prompt_usuario: str,
        contenido_bytes: bytes | None = None,
        mime_type: str | None = None,
    ) -> str:
        self.llamadas += 1
        raise ErrorTecnicoProveedor("503 simulado")


class ProveedorOK:
    def __init__(self):
        self.llamadas = 0

    def generar(
        self,
        prompt_sistema: str,
        prompt_usuario: str,
        contenido_bytes: bytes | None = None,
        mime_type: str | None = None,
    ) -> str:
        self.llamadas += 1
        return _json_valido()


def test_reintenta_hasta_max_intentos_con_json_invalido():
    proveedor = ProveedorSiempreInvalido()

    resultado = extraer_datos_clinicos(
        _documento(),
        _clasificacion(),
        proveedor,
    )

    assert proveedor.llamadas == MAX_INTENTOS
    assert resultado.paciente.nombre_completo is None
    assert "paciente.nombre_completo" in resultado.campos_no_encontrados


def test_fallo_tecnico_agota_reintentos_del_principal_antes_del_fallback():
    principal = ProveedorFalloTecnico()
    fallback = ProveedorOK()

    resultado = extraer_datos_clinicos(
        _documento(),
        _clasificacion(),
        proveedor=principal,
        proveedor_fallback=fallback,
    )

    assert principal.llamadas == MAX_INTENTOS
    assert fallback.llamadas == 1
    assert resultado.observaciones == "ok"


def test_sin_fallback_configurado_tambien_reintenta_antes_de_degradar():
    principal = ProveedorFalloTecnico()

    resultado = extraer_datos_clinicos(
        _documento(),
        _clasificacion(),
        proveedor=principal,
    )

    assert principal.llamadas == MAX_INTENTOS
    assert resultado.paciente.nombre_completo is None
    assert "fallo técnico" in resultado.observaciones


def test_proveedor_que_falla_de_forma_no_anticipada_no_rompe_el_flujo():
    class ProveedorConBugInesperado:
        def generar(
            self,
            prompt_sistema: str,
            prompt_usuario: str,
            contenido_bytes: bytes | None = None,
            mime_type: str | None = None,
        ) -> str:
            raise AttributeError("'NoneType' object has no attribute 'text'")

    resultado = extraer_datos_clinicos(
        _documento(),
        _clasificacion(),
        ProveedorConBugInesperado(),
    )

    assert resultado.paciente.nombre_completo is None
    assert "error inesperado" in resultado.observaciones


def test_extrae_resultado_valido_con_contrato_mf02():
    resultado = extraer_datos_clinicos(
        _documento(),
        _clasificacion(),
        ProveedorOK(),
    )

    assert resultado.paciente.nombre_completo == "Ana Restrepo"
    assert resultado.profesional.nombre_completo == "Dr. X"
    assert resultado.observaciones == "ok"