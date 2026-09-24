"""Cliente delgado sobre google-genai para los agentes de MediFlow.

Cada agente usa su propia API key segun .env.example
(GEMINI_CLASSIFIER_API_KEY / GEMINI_EXTRACTOR_API_KEY), para poder medir
y limitar el consumo de cuota de forma independiente por agente.
"""
from __future__ import annotations

import os
from typing import Type, TypeVar

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.getenv("GEMINI_CLASSIFIER_MODEL", "gemini-3.5-flash-lite")


def _build_client(api_key_env: str) -> genai.Client:
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(
            f"Falta la variable de entorno {api_key_env}. Copia .env.example a .env y completala."
        )
    return genai.Client(api_key=api_key)


def generar_salida_estructurada(
    *,
    api_key_env: str,
    prompt: str,
    contenido_bytes: bytes | None,
    mime_type: str | None,
    schema: Type[T],
    model: str = DEFAULT_MODEL,
) -> T:
    """Llama a Gemini y devuelve la respuesta ya validada contra `schema`."""
    client = _build_client(api_key_env)

    partes: list[types.Part | str] = [prompt]
    if contenido_bytes:
        partes.append(
            types.Part.from_bytes(data=contenido_bytes, mime_type=mime_type or "application/pdf")
        )

    respuesta = client.models.generate_content(
        model=model,
        contents=partes,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )

    parsed = respuesta.parsed
    if parsed is None:
        raise ValueError(
            f"Gemini no devolvio un JSON valido contra {schema.__name__}: {respuesta.text!r}"
        )
    return parsed
