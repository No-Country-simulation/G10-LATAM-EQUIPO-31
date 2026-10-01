"""
app.services.groq_client

Cliente para el modelo/proveedor SECUNDARIO propuesto por el equipo para
MF-19: Groq (qwen/qwen3.8-27b), via el SDK oficial `groq`.

Gemini sigue siendo el modelo PRINCIPAL en ambos agentes, sin cambios.
Este modulo solo se usa si el fallo tecnico del principal agota sus
reintentos (ver app/agents/classifier.py y app/agents/extractor.py).

Implementa dos piezas, una por agente:

  * `ProveedorGroq`: cumple el protocolo `ProveedorLLM` de
    app/agents/extractor.py (mismo contrato que `ProveedorGemini`), para
    usarse como `proveedor_fallback` del Extractor.
  * `generar_estructurado_con_groq(...)`: genera una salida validada
    contra un schema Pydantic usando el modo estricto de Groq
    (`response_format={"type": "json_schema", "strict": True}`), para
    usarse como `generador_fallback` del Clasificador. Solo es
    directamente aplicable a schemas SIN campos opcionales (como
    `Classification`): el modo estricto de Groq exige que todo el schema
    tenga `additionalProperties: false` y todas las propiedades en
    `required`, algo que Pydantic ya genera solo para modelos sin
    `Optional` (ver `_json_schema_estricto`).

LIMITACION CONOCIDA (documentada en detalle en
docs/mf-19-fallback-tecnico.md): Groq/qwen3.8-27b es un modelo de VISION
(imagenes), no procesa PDF nativo como si hace Gemini
(`Part.from_bytes(mime_type="application/pdf")`). Si el documento es un
PDF, este modulo rasteriza la PRIMERA pagina a PNG con PyMuPDF antes de
enviarla. Para esta primera version del fallback (MF-19) es una
limitacion aceptada y documentada: un PDF de varias paginas pierde el
contenido de las paginas 2+ si el fallback llega a activarse justo en
ese documento. Los documentos de imagen (JPG/PNG) no tienen esta
limitacion.
"""

from __future__ import annotations

import base64
import os
from typing import TypeVar

import groq
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from app.services.errores_llm import ErrorTecnicoProveedor

load_dotenv()

MODELO_GROQ_POR_DEFECTO = "qwen/qwen3.8-27b"

# Qwen3.8 arranca por defecto en modo "thinking": el razonamiento consume
# tokens del limite del plan gratuito (8.000/min) y puede contaminar el
# texto que el Extractor parsea como JSON. Para extraccion/clasificacion
# no hace falta razonar, asi que se usa el modo instruct (segun las
# mejores practicas de la ficha del modelo en la documentacion de Groq).
_REASONING_EFFORT = "none"

# Limite documentado por Groq para requests que incluyen una imagen.
_LIMITE_BYTES_IMAGEN = 20 * 1024 * 1024

T = TypeVar("T", bound=BaseModel)


def _build_client(api_key: str | None = None) -> groq.Groq:
    clave = api_key or os.getenv("GROQ_API_KEY")
    if not clave:
        raise RuntimeError(
            "Falta la API key de Groq. Pasala por parametro o define GROQ_API_KEY en el .env "
            "(se genera gratis en https://console.groq.com/keys)."
        )
    return groq.Groq(api_key=clave)


def _pdf_a_png_primera_pagina(contenido_pdf: bytes) -> bytes:
    """Ver la nota de LIMITACION CONOCIDA en el docstring del modulo."""
    import fitz  # PyMuPDF -- import perezoso: solo hace falta si se usa el fallback con un PDF

    with fitz.open(stream=contenido_pdf, filetype="pdf") as documento:
        if documento.page_count == 0:
            raise ValueError("El PDF no tiene paginas; no se puede rasterizar para Groq.")
        pixmap = documento.load_page(0).get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        return pixmap.tobytes("png")


def _preparar_imagen(contenido_bytes: bytes, mime_type: str | None) -> tuple[bytes, str]:
    """Devuelve (bytes_de_imagen, mime_type_de_imagen), rasterizando el PDF si hace falta."""
    if mime_type == "application/pdf":
        return _pdf_a_png_primera_pagina(contenido_bytes), "image/png"
    return contenido_bytes, mime_type or "image/jpeg"


def _construir_contenido_usuario(
    prompt: str, contenido_bytes: bytes | None, mime_type: str | None
) -> list[dict]:
    contenido: list[dict] = [{"type": "text", "text": prompt}]
    if contenido_bytes:
        imagen_bytes, imagen_mime = _preparar_imagen(contenido_bytes, mime_type)
        if len(imagen_bytes) > _LIMITE_BYTES_IMAGEN:
            # Limite tecnico real de la API (no un problema de contenido):
            # cuenta como fallo tecnico, igual que un 413 del servidor.
            raise ErrorTecnicoProveedor(
                f"La imagen supera el limite de Groq de {_LIMITE_BYTES_IMAGEN // (1024 * 1024)}MB "
                f"por solicitud ({len(imagen_bytes)} bytes)."
            )
        b64 = base64.b64encode(imagen_bytes).decode("ascii")
        contenido.append(
            {"type": "image_url", "image_url": {"url": f"data:{imagen_mime};base64,{b64}"}}
        )
    return contenido


def _json_schema_estricto(schema: type[BaseModel]) -> dict:
    """
    JSON Schema en modo estricto para Structured Outputs de Groq. Groq
    exige `additionalProperties: false` en el objeto; Pydantic ya deja
    todas las propiedades en `required` para un modelo sin campos
    Optional (como `Classification`), asi que no hace falta tocar nada
    mas. Si en el futuro se usa con un schema CON campos opcionales
    (`ExtraccionClinica`), esta funcion necesitaria adaptarse (marcar los
    tipos como nullable y agregarlos igual a `required`, que es como
    exige el modo estricto tratar los "opcionales") -- no es el caso hoy
    porque el Extractor usa `ProveedorGroq.generar` (texto libre + parseo
    manual de JSON), no este modo estricto.
    """
    esquema = schema.model_json_schema()
    esquema["additionalProperties"] = False
    esquema.pop("title", None)
    return esquema


class ProveedorGroq:
    """
    Implementa el protocolo `ProveedorLLM` (ver app/agents/extractor.py)
    con el SDK de Groq. Se usa como `proveedor_fallback` del Extractor,
    con la misma interfaz que `ProveedorGemini` -- el Extractor no sabe
    ni le importa si esta hablando con Gemini o con Groq.
    """

    def __init__(self, api_key: str | None = None, modelo: str = MODELO_GROQ_POR_DEFECTO):
        self.client = _build_client(api_key)
        self.modelo = modelo

    def generar(
        self,
        prompt_sistema: str,
        prompt_usuario: str,
        contenido_bytes: bytes | None = None,
        mime_type: str | None = None,
    ) -> str:
        try:
            contenido_usuario = _construir_contenido_usuario(prompt_usuario, contenido_bytes, mime_type)
            respuesta = self.client.chat.completions.create(
                model=self.modelo,
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": contenido_usuario},
                ],
                reasoning_effort=_REASONING_EFFORT,
            )
        except ErrorTecnicoProveedor:
            raise
        except groq.APIError as exc:
            raise ErrorTecnicoProveedor(f"Groq respondio con un error tecnico: {exc}") from exc

        texto = respuesta.choices[0].message.content if respuesta.choices else None
        if not texto or not texto.strip():
            raise ErrorTecnicoProveedor("Groq devolvio una respuesta vacia.")
        return texto


def generar_estructurado_con_groq(
    prompt: str,
    contenido_bytes: bytes | None,
    mime_type: str | None,
    schema: type[T],
    modelo: str = MODELO_GROQ_POR_DEFECTO,
    api_key: str | None = None,
) -> T:
    """
    Genera una salida validada contra `schema` usando el modo estricto de
    Groq (ver `_json_schema_estricto`). Pensado para el Clasificador.
    """
    client = _build_client(api_key)
    try:
        contenido_usuario = _construir_contenido_usuario(prompt, contenido_bytes, mime_type)
        respuesta = client.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": contenido_usuario}],
            reasoning_effort=_REASONING_EFFORT,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": _json_schema_estricto(schema),
                    "strict": True,
                },
            },
        )
    except ErrorTecnicoProveedor:
        raise
    except groq.APIError as exc:
        raise ErrorTecnicoProveedor(f"Groq respondio con un error tecnico: {exc}") from exc

    texto = respuesta.choices[0].message.content if respuesta.choices else None
    if not texto or not texto.strip():
        raise ErrorTecnicoProveedor("Groq devolvio una respuesta vacia.")

    try:
        return schema.model_validate_json(texto)
    except ValidationError as exc:
        # Problema de CONTENIDO (no cumplio el schema pese al modo
        # estricto) -- se trata igual que un JSON invalido de Gemini, NO
        # como un fallo tecnico.
        raise ValueError(
            f"Groq no devolvio un JSON valido contra {schema.__name__}: {texto!r}"
        ) from exc
