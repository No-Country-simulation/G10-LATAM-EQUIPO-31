"""
app.services.errores_llm

Excepción común para que cualquier proveedor/cliente de LLM (Gemini hoy;
el que el equipo adopte como secundario en el futuro) le señale al agente
que lo llama que hubo un FALLO TÉCNICO — no un problema de contenido.

Esta distinción es la que decide si un fallo dispara el mecanismo de
fallback (MF-19):

- Fallo TÉCNICO (429/cuota, timeout, 5xx, respuesta vacía por bloqueo de
  seguridad) -> se reintenta y, si persiste, se activa el fallback.
- Problema de CONTENIDO (JSON inválido que no cumple el schema, baja
  confianza, ambigüedad, inconsistencias clínicas) -> NUNCA debe
  traducirse a esta excepción. Eso se evalúa en confianza/consistencia
  (MF-09/MF-10), no acá; un LLM alternativo no arregla un documento
  ambiguo, solo consume cuota extra sin necesidad.

Antes vivía dentro de app/agents/extractor.py (MF-06); se movió acá en
MF-19 para que también pueda usarla app/agents/classifier.py sin que un
agente tenga que importar del otro. Se sigue pudiendo importar como
`from app.agents.extractor import ErrorTecnicoProveedor` (re-exportada
ahí) para no romper código/tests existentes.
"""

from __future__ import annotations


class ErrorTecnicoProveedor(Exception):
    """
    Un proveedor/cliente de LLM concreto debe lanzar esta excepción para
    señalar un fallo TÉCNICO (429/cuota, timeout, 5xx/indisponibilidad,
    respuesta vacía por bloqueo de seguridad) — nunca para un problema de
    contenido del propio documento.
    """
