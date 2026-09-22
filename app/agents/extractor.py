"""
app.agents.extractor

MF-06 | Agente Extractor.

Recibe un documento (ya como texto) + el resultado de clasificación, llama
al LLM para extraer los datos clínicos estructurados, y valida la salida
contra `ExtraccionClinica` (app/schemas/extraccion_schema.py — borrador
propio mientras MF-02 entrega el schema definitivo acordado con el resto
de agentes del grafo).

Política de reintento: hasta MAX_INTENTOS si el LLM devuelve JSON inválido
o que no cumple el schema. Si se agotan los intentos, no se lanza excepción:
se devuelve una extracción "vacía" con campos_no_encontrados lleno, para
que la etapa de "Evaluación de confianza y consistencia" decida enviarlo
a revisión humana.

Fallback técnico (según diagrama de arquitectura del equipo): si el
proveedor principal falla por un error técnico (429/cuota, timeout, 5xx —
no por un JSON mal formado), se cambia automáticamente a `proveedor_fallback`
si se proporcionó uno. Cuál es el LLM alternativo queda pendiente de
confirmar con el equipo (tarea abierta de Kimberlyn); mientras tanto,
`proveedor_fallback` es opcional y el extractor sigue funcionando sin él.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import ValidationError

from app.schemas.extraccion_schema import (
    ExtraccionClinica,
    Paciente,
    Profesional,
)

logger = logging.getLogger("mediflow.app.agents.extractor")

MAX_INTENTOS = 3

_CAMPOS_MINIMOS_ESPERADOS = [
    "paciente.nombre_completo",
    "paciente.numero_documento",
    "profesional.nombre_completo",
    "diagnosticos",
]


class ProveedorLLM(Protocol):
    """
    Interfaz mínima que debe cumplir el cliente del LLM que uses
    (OpenAI, Anthropic, Gemini, etc.). Así el resto del código no
    depende de qué proveedor termine usando el equipo.
    """

    def generar(self, prompt_sistema: str, prompt_usuario: str) -> str: ...


class ErrorTecnicoProveedor(Exception):
    """
    Excepción que un ProveedorLLM concreto puede lanzar para señalar un
    fallo técnico (429/cuota, timeout, 5xx/indisponibilidad) en lugar de
    un error de contenido. El extractor la usa para decidir si vale la
    pena reintentar con el mismo proveedor o saltar directo al fallback.

    Si tu proveedor (ej. ProveedorGemini) no distingue esto, no pasa nada:
    el extractor sigue funcionando, simplemente no podrá diferenciar un
    fallo técnico de uno de contenido y agotará los reintentos igual.
    """


class ResultadoClasificacionMock:
    """
    Sustituto mínimo de lo que entregará el Agente Clasificador (MF-05).
    Solo se usa para poder probar el extractor de forma aislada; el campo
    real que llegue del grafo probablemente tenga esta misma forma o muy
    parecida (confirmar con quien tenga esa tarjeta).
    """

    def __init__(self, tipo_documento: str, especialidad: str | None = None):
        self.tipo_documento = tipo_documento
        self.especialidad = especialidad


def _extraer_json(texto: str) -> dict[str, Any]:
    """Tolera que el LLM devuelva el JSON envuelto en fences de Markdown."""
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.strip("`")
        if texto.lower().startswith("json"):
            texto = texto[4:]
        texto = texto.strip()
    return json.loads(texto)


def _construir_prompt(texto_documento: str, clasificacion: Any) -> tuple[str, str]:
    prompt_sistema = (
        "Eres un asistente clínico que extrae información estructurada de "
        "documentos hospitalarios. Devuelve SIEMPRE un único objeto JSON, sin "
        "texto adicional ni explicaciones, que cumpla EXACTAMENTE esta forma:\n"
        "{\n"
        '  "tipo_documento": str,\n'
        '  "especialidad": str|null,\n'
        '  "paciente": {"nombre_completo": str|null, "tipo_documento": str|null, '
        '"numero_documento": str|null, "edad": int|null, "sexo": str|null},\n'
        '  "profesional": {"nombre_completo": str|null, "registro_profesional": str|null, '
        '"especialidad": str|null, "institucion": str|null},\n'
        '  "diagnosticos": [{"descripcion": str, "codigo_cie10": str|null, '
        '"tipo": "principal"|"secundario"|"presuntivo"|null}],\n'
        '  "medicamentos": [{"nombre": str, "dosis": str|null, "via_administracion": str|null, '
        '"frecuencia": str|null, "duracion": str|null}],\n'
        '  "estudios_solicitados": [{"tipo": str, "descripcion": str, "prioridad": str|null}],\n'
        '  "nivel_urgencia": "no_urgente"|"prioritario"|"urgente"|"emergencia"|null,\n'
        '  "senales_gravedad": [str],\n'
        '  "fecha_documento": str|null,\n'
        '  "observaciones": str|null,\n'
        '  "campos_no_encontrados": [str]\n'
        "}\n"
        "'senales_gravedad' debe contener frases textuales del documento que "
        "respalden el nivel de urgencia elegido (evidencia, no opinión). Si un "
        "dato no aparece en el documento, usa null (o lista vacía) y agrega el "
        "nombre del campo a 'campos_no_encontrados'. No inventes datos ni "
        "códigos CIE-10 que no puedan inferirse con alta confianza."
    )
    prompt_usuario = (
        f"Tipo de documento clasificado (Agente 1): {clasificacion.tipo_documento}\n"
        f"Especialidad clasificada (Agente 1): {clasificacion.especialidad or 'no informada'}\n\n"
        f"Documento:\n{texto_documento}"
    )
    return prompt_sistema, prompt_usuario


def _extraccion_vacia(clasificacion: Any, motivo: str) -> ExtraccionClinica:
    """Salida degradada cuando se agotan los reintentos: nunca se lanza excepción."""
    return ExtraccionClinica(
        tipo_documento=clasificacion.tipo_documento,
        especialidad=clasificacion.especialidad,
        paciente=Paciente(),
        profesional=Profesional(),
        diagnosticos=[],
        medicamentos=[],
        estudios_solicitados=[],
        nivel_urgencia=None,
        senales_gravedad=[],
        campos_no_encontrados=list(_CAMPOS_MINIMOS_ESPERADOS),
        observaciones=f"No fue posible obtener una extracción válida del LLM: {motivo}",
    )


def _intentar_con_proveedor(
    proveedor: ProveedorLLM,
    prompt_sistema: str,
    prompt_usuario: str,
    etiqueta: str,
    errores: list[str],
) -> ExtraccionClinica | None:
    """
    Intenta hasta MAX_INTENTOS veces con UN proveedor. Devuelve el resultado
    validado si tiene éxito, o None si hay que pasar al fallback (fallo
    técnico) o se agotaron los intentos por errores de formato.
    """
    for intento in range(1, MAX_INTENTOS + 1):
        try:
            respuesta = proveedor.generar(prompt_sistema, prompt_usuario)
        except ErrorTecnicoProveedor as exc:
            mensaje = f"[{etiqueta}] intento {intento}/{MAX_INTENTOS}: fallo técnico ({exc})"
            logger.warning(mensaje)
            errores.append(mensaje)
            return None  # no insistir con el mismo proveedor si ya sabemos que es técnico

        try:
            datos_json = _extraer_json(respuesta)
            resultado = ExtraccionClinica.model_validate(datos_json)
            logger.info(
                "Extracción completada con [%s] en intento %s/%s (%s campos no encontrados).",
                etiqueta,
                intento,
                MAX_INTENTOS,
                len(resultado.campos_no_encontrados),
            )
            return resultado
        except (json.JSONDecodeError, ValidationError) as exc:
            mensaje = f"[{etiqueta}] intento {intento}/{MAX_INTENTOS}: salida inválida ({exc})"
            logger.warning(mensaje)
            errores.append(mensaje)

    return None


def extraer_datos_clinicos(
    texto_documento: str,
    clasificacion: Any,
    proveedor: ProveedorLLM,
    proveedor_fallback: ProveedorLLM | None = None,
) -> ExtraccionClinica:
    """
    Punto de entrada principal del Agente Extractor.

    texto_documento: contenido ya en texto plano/Markdown del documento
        (se asume que la conversión de PDF/imagen, si aplica, ya ocurrió
        antes de esta función — pendiente de confirmar con el equipo, ya
        que el diagrama de arquitectura habla de un LLM "multimodal", lo
        que podría significar enviar el documento directo, sin este paso).
    clasificacion: salida del Agente Clasificador (MF-05) — o
        ResultadoClasificacionMock para pruebas aisladas. Debe tener al
        menos `.tipo_documento` y `.especialidad`.
    proveedor: cliente concreto del LLM principal que implemente `.generar(...)`.
    proveedor_fallback: cliente del LLM alternativo (opcional). Se usa solo
        si `proveedor` falla por un ErrorTecnicoProveedor. Cuál LLM usar
        aquí es una decisión pendiente del equipo.
    """
    prompt_sistema, prompt_usuario = _construir_prompt(texto_documento, clasificacion)
    errores: list[str] = []

    resultado = _intentar_con_proveedor(proveedor, prompt_sistema, prompt_usuario, "principal", errores)
    if resultado is not None:
        return resultado

    if proveedor_fallback is not None:
        logger.warning("Proveedor principal no respondió correctamente; probando fallback.")
        resultado = _intentar_con_proveedor(
            proveedor_fallback, prompt_sistema, prompt_usuario, "fallback", errores
        )
        if resultado is not None:
            return resultado

    logger.error("Se agotaron todos los proveedores disponibles; devolviendo extracción vacía.")
    return _extraccion_vacia(clasificacion, "; ".join(errores))