"""
app.providers.gemini_provider

Implementación concreta de `ProveedorLLM` (ver app/agents/extractor.py)
usando el SDK oficial `google-genai` (el que está en requirements.txt).

Traduce los fallos técnicos reales de la API (429/cuota, 5xx, timeout,
respuesta vacía por bloqueo de seguridad) a `ErrorTecnicoProveedor`, para
que `extractor.py` pueda distinguirlos de un JSON mal formado y activar
correctamente el fallback / la degradación controlada.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors

from app.agents.extractor import ErrorTecnicoProveedor

# Carga el .env explícitamente (no asume que otro módulo ya lo haya hecho).
# Variable de entorno usada en todo el proyecto: GEMINI_API_KEY
load_dotenv()


class ProveedorGemini:
    def __init__(self, api_key: str | None = None, modelo: str = "gemini-2.0-flash"):
        clave = api_key or os.getenv("GEMINI_API_KEY")
        if not clave:
            raise ValueError(
                "Falta la API key de Gemini. Pásala por parámetro o define "
                "GEMINI_API_KEY en el .env"
            )
        self.client = genai.Client(api_key=clave)
        self.modelo = modelo

    def generar(self, prompt_sistema: str, prompt_usuario: str) -> str:
        try:
            respuesta = self.client.models.generate_content(
                model=self.modelo,
                contents=prompt_usuario,
                config={"system_instruction": prompt_sistema},
            )
        except genai_errors.APIError as exc:
            # Cubre ClientError (4xx, incl. 429 cuota) y ServerError
            # (5xx/indisponibilidad). exc.code trae el status HTTP.
            raise ErrorTecnicoProveedor(
                f"Gemini respondió con error HTTP {exc.code}: {exc}"
            ) from exc
        except (TimeoutError, ConnectionError) as exc:
            raise ErrorTecnicoProveedor(f"Timeout/conexión con Gemini: {exc}") from exc

        texto = respuesta.text
        if not texto or not texto.strip():
            # Respuesta vacía: normalmente indica bloqueo por los filtros
            # de seguridad de Gemini. Se trata como fallo técnico.
            motivo_bloqueo = getattr(respuesta, "prompt_feedback", None)
            raise ErrorTecnicoProveedor(
                f"Gemini devolvió una respuesta vacía (prompt_feedback={motivo_bloqueo})"
            )

        return texto