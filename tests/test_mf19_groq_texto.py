"""
tests/test_mf19_groq_texto.py

MF-19 / MF-20: un documento de TEXTO (text/plain) que llega con
`contenido_bytes` (como en el flujo de FastAPI) debe enviarse a Groq como
texto y NUNCA como `image_url` (Groq responde 400 "invalid image data").
Tambien se verifica que PDF e imagenes sigan funcionando como antes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.schemas.clasificacion import Classification, DocumentType
from app.services import groq_client

TEXTO = "Receta medica. Paciente: Ana Torres. Rx: Amoxicilina 500 mg cada 8 horas."
PROMPT = "Clasifica el documento."


def _tipos(contenido: list[dict]) -> list[str]:
    return [parte["type"] for parte in contenido]


def _texto_total(contenido: list[dict]) -> str:
    return "\n".join(parte["text"] for parte in contenido if parte["type"] == "text")


# ---------------------------------------------------------------- texto


def test_text_plain_se_envia_como_texto_no_como_imagen():
    contenido = groq_client._construir_contenido_usuario(PROMPT, TEXTO.encode(), "text/plain")

    assert "image_url" not in _tipos(contenido)
    assert TEXTO in _texto_total(contenido)


def test_text_plain_con_charset_tambien_es_texto():
    contenido = groq_client._construir_contenido_usuario(
        PROMPT, TEXTO.encode(), "text/plain; charset=utf-8"
    )

    assert "image_url" not in _tipos(contenido)
    assert TEXTO in _texto_total(contenido)


def test_json_se_envia_como_texto():
    contenido = groq_client._construir_contenido_usuario(
        PROMPT, b'{"paciente": "Ana Torres"}', "application/json"
    )

    assert "image_url" not in _tipos(contenido)
    assert "Ana Torres" in _texto_total(contenido)


def test_no_duplica_el_texto_si_el_prompt_ya_lo_incluye():
    prompt = f"{PROMPT}\n\nDocumento:\n{TEXTO}"

    contenido = groq_client._construir_contenido_usuario(prompt, TEXTO.encode(), "text/plain")

    assert _texto_total(contenido).count(TEXTO) == 1


def test_texto_con_tildes_y_bom_se_decodifica_bien():
    original = "Paciente: José Muñoz"
    contenido = groq_client._construir_contenido_usuario(
        PROMPT, original.encode("utf-8-sig"), "text/plain"
    )

    assert original in _texto_total(contenido)


def test_texto_con_codificacion_invalida_no_rompe():
    """Bytes que no son UTF-8 (p. ej. latin-1) no deben lanzar excepcion."""
    contenido = groq_client._construir_contenido_usuario(
        PROMPT, "Paciente: José".encode("latin-1"), "text/plain"
    )

    assert "image_url" not in _tipos(contenido)
    assert "Paciente: Jos" in _texto_total(contenido)


def test_sin_bytes_solo_envia_el_prompt():
    contenido = groq_client._construir_contenido_usuario(PROMPT, None, "text/plain")

    assert contenido == [{"type": "text", "text": PROMPT}]


# ------------------------------------------------- lo que ya funcionaba


def test_imagen_sigue_enviandose_como_image_url():
    contenido = groq_client._construir_contenido_usuario(PROMPT, b"\x89PNG-falso", "image/png")

    assert _tipos(contenido) == ["text", "image_url"]
    assert contenido[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_sin_mime_type_se_mantiene_el_comportamiento_previo_de_imagen():
    contenido = groq_client._construir_contenido_usuario(PROMPT, b"bytes", None)

    assert contenido[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_pdf_sigue_rasterizandose_a_png():
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Receta de prueba MF-19")
    pdf = doc.tobytes()
    doc.close()

    contenido = groq_client._construir_contenido_usuario(PROMPT, pdf, "application/pdf")

    assert _tipos(contenido) == ["text", "image_url"]
    assert contenido[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_tipo_no_soportado_lanza_value_error_sin_llamar_a_la_api():
    with pytest.raises(ValueError, match="application/zip"):
        groq_client._construir_contenido_usuario(PROMPT, b"PK", "application/zip")


# ------------------------------- de punta a punta con un cliente falso


def _cliente_falso(capturado: dict, respuesta: str):
    def _create(**kwargs):
        capturado.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=respuesta))])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))


def _mensaje_usuario(capturado: dict) -> list[dict]:
    return next(m["content"] for m in capturado["messages"] if m["role"] == "user")


def test_proveedor_groq_con_txt_no_envia_imagen(monkeypatch):
    capturado: dict = {}
    monkeypatch.setattr(
        groq_client, "_build_client", lambda api_key=None: _cliente_falso(capturado, "{}")
    )

    groq_client.ProveedorGroq(api_key="k").generar(
        "sistema", "usuario", contenido_bytes=TEXTO.encode(), mime_type="text/plain"
    )

    contenido = _mensaje_usuario(capturado)
    assert "image_url" not in _tipos(contenido)
    assert TEXTO in _texto_total(contenido)


def test_clasificador_groq_con_txt_no_envia_imagen(monkeypatch):
    capturado: dict = {}
    respuesta = Classification(
        tipo_documento=DocumentType.RECETA_MEDICA,
        especialidad="Medicina General",
        nivel_prioridad="Rutina",
        score_confianza_clasificacion=0.9,
        justificacion="Receta con medicamentos.",
    ).model_dump_json()
    monkeypatch.setattr(
        groq_client, "_build_client", lambda api_key=None: _cliente_falso(capturado, respuesta)
    )

    resultado = groq_client.generar_estructurado_con_groq(
        prompt=PROMPT,
        contenido_bytes=TEXTO.encode(),
        mime_type="text/plain",
        schema=Classification,
        api_key="k",
    )

    assert isinstance(resultado, BaseModel)
    contenido = _mensaje_usuario(capturado)
    assert "image_url" not in _tipos(contenido)
    assert TEXTO in _texto_total(contenido)
