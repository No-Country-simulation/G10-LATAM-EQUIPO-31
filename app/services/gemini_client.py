"""Cliente delgado sobre google-genai para los agentes de MediFlow.

Cada agente usa su propia API key segun .env.example
(GEMINI_CLASSIFIER_API_KEY / GEMINI_EXTRACTOR_API_KEY), para poder medir
y limitar el consumo de cuota de forma independiente por agente.

MF-19: traduce los fallos TECNICOS reales de la API (429/cuota, 5xx,
timeout) a `ErrorTecnicoProveedor`, igual que ya hace
`gemini_provider.py` para el Extractor, para que `classifier.py` pueda
distinguirlos de un problema de contenido (respuesta que no cumple el
schema) y activar correctamente reintentos/fallback.
"""
from __future__ import annotations

import os
from typing import Type, TypeVar

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.services.errores_llm import ErrorTecnicoProveedor

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

    try:
        respuesta = client.models.generate_content(
            model=model,
            contents=partes,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    except genai_errors.APIError as exc:
        # Fallo TECNICO real de la API (429/cuota, 5xx, etc.) -> dispara
        # reintentos/fallback en classifier.py.
        raise ErrorTecnicoProveedor(
            f"Gemini respondio con error HTTP {getattr(exc, 'code', '?')}: {exc}"
        ) from exc
    except (TimeoutError, ConnectionError) as exc:
        raise ErrorTecnicoProveedor(f"Timeout/conexion con Gemini: {exc}") from exc

    parsed = respuesta.parsed
    if parsed is None:
        # Problema de CONTENIDO (Gemini no devolvio algo que cumpla el
        # schema), no un fallo tecnico: classifier.py lo trata igual que
        # un JSON invalido (reintenta con el MISMO modelo antes de
        # escalar), nunca como motivo por si solo para cambiar de modelo.
        motivo_bloqueo = getattr(respuesta, "prompt_feedback", None)
        if not (respuesta.text or "").strip() and motivo_bloqueo:
            # Respuesta vacia por bloqueo de seguridad SI es un fallo
            # tecnico del proveedor con esa entrada, no del contenido.
            raise ErrorTecnicoProveedor(
                f"Gemini devolvio una respuesta vacia (prompt_feedback={motivo_bloqueo})"
            )
        raise ValueError(
            f"Gemini no devolvio un JSON valido contra {schema.__name__}: {respuesta.text!r}"
        )
    return parsed
