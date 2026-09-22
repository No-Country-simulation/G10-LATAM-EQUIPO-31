"""
app.providers.gemini_provider

Implementación concreta de `ProveedorLLM` (ver app/agents/extractor.py)
usando el SDK oficial `google-genai` (el que está en requirements.txt).

No modifica el schema ni la lógica de extracción: el extractor solo
necesita un objeto con `.generar(prompt_sistema, prompt_usuario) -> str`,
así que este archivo es intercambiable con ProveedorFalso o con
cualquier otro proveedor (fallback incluido).
"""

from __future__ import annotations

import os

from google import genai


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
        respuesta = self.client.models.generate_content(
            model=self.modelo,
            contents=prompt_usuario,
            config={"system_instruction": prompt_sistema},
        )
        return respuesta.text