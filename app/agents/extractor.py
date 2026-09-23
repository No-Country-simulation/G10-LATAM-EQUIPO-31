"""
app.agents.extractor

MF-06 | Agente Extractor.

Recibe un documento (ya como texto) + el resultado de clasificación, llama
al LLM para extraer los datos clínicos estructurados, y valida la salida
contra `ExtraccionClinica` (app/schemas/extraccion_schema.py — borrador
propio mientras MF-02 entrega el schema definitivo acordado con el resto
de agentes del grafo).

Política de reintento: hasta MAX_INTENTOS si el LLM devuelve JSON inválido,
no cumple el schema, o el proveedor falla técnicamente (429/cuota, timeout,
5xx). Si se agotan los intentos, no se lanza excepción: se devuelve una
extracción "vacía" con campos_no_encontrados lleno, para que la etapa de
"Evaluación de confianza y consistencia" decida enviarlo a revisión humana.

Fallback técnico (según diagrama de arquitectura del equipo): si el
proveedor principal agota sus reintentos, se cambia a `proveedor_fallback`
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
    un error de contenido.
    """


class ResultadoClasificacionMock:
    """
    Sustituto mínimo de lo que entregará el Agente Clasificador (MF-05).
    Solo se usa para poder probar el extractor de forma aislada.
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


def _calcular_campos_no_encontrados(resultado: ExtraccionClinica) -> list[str]:
    """
    Revisa el resultado YA VALIDADO y determina, por código (no confiando
    en lo que el LLM haya reportado por su cuenta), cuáles de los campos
    mínimos esperados quedaron vacíos.
    """
    faltantes: list[str] = []
    if not resultado.paciente.nombre_completo:
        faltantes.append("paciente.nombre_completo")
    if not resultado.paciente.numero_documento:
        faltantes.append("paciente.numero_documento")
    if not resultado.profesional.nombre_completo:
        faltantes.append("profesional.nombre_completo")
    if not resultado.diagnosticos:
        faltantes.append("diagnosticos")
    return faltantes


def _normalizar_resultado(resultado: ExtraccionClinica, clasificacion: Any) -> ExtraccionClinica:
    """
    Se aplica a todo resultado exitoso antes de devolverlo:
    - tipo_documento / especialidad SIEMPRE vienen de la clasificación
      (Agente 1), nunca de lo que el LLM haya devuelto en esos campos.
    - campos_no_encontrados se recalcula por código en vez de confiar
      ciegamente en la lista que reportó el LLM.
    """
    resultado.tipo_documento = clasificacion.tipo_documento
    resultado.especialidad = clasificacion.especialidad

    calculados = _calcular_campos_no_encontrados(resultado)
    combinados = list(dict.fromkeys([*resultado.campos_no_encontrados, *calculados]))
    resultado.campos_no_encontrados = combinados
    return resultado


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
    clasificacion: Any,
) -> ExtraccionClinica | None:
    """
    Intenta hasta MAX_INTENTOS veces con UN proveedor. Devuelve el resultado
    validado si tiene éxito, o None si hay que pasar al fallback o se
    agotaron los intentos.
    """
    for intento in range(1, MAX_INTENTOS + 1):
        try:
            respuesta = proveedor.generar(prompt_sistema, prompt_usuario)
        except ErrorTecnicoProveedor as exc:
            # Se reintenta con el MISMO proveedor (un timeout/429 puntual
            # puede ser transitorio); solo se pasa al fallback cuando se
            # agotan los MAX_INTENTOS.
            mensaje = f"[{etiqueta}] intento {intento}/{MAX_INTENTOS}: fallo técnico ({exc})"
            logger.warning(mensaje)
            errores.append(mensaje)
            continue
        except Exception as exc:
            # Red de seguridad: cualquier error que el proveedor NO haya
            # traducido a ErrorTecnicoProveedor cae aquí. Nunca debe
            # escaparse una excepción fuera de este módulo.
            mensaje = (
                f"[{etiqueta}] intento {intento}/{MAX_INTENTOS}: "
                f"error inesperado del proveedor ({type(exc).__name__}: {exc})"
            )
            logger.warning(mensaje)
            errores.append(mensaje)
            continue

        try:
            datos_json = _extraer_json(respuesta)
            resultado = ExtraccionClinica.model_validate(datos_json)
            resultado = _normalizar_resultado(resultado, clasificacion)
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

    texto_documento: contenido ya en texto plano/Markdown del documento.
    clasificacion: salida del Agente Clasificador (MF-05) — o
        ResultadoClasificacionMock para pruebas aisladas.
    proveedor: cliente concreto del LLM principal.
    proveedor_fallback: cliente del LLM alternativo (opcional).
    """
    prompt_sistema, prompt_usuario = _construir_prompt(texto_documento, clasificacion)
    errores: list[str] = []

    resultado = _intentar_con_proveedor(
        proveedor, prompt_sistema, prompt_usuario, "principal", errores, clasificacion
    )
    if resultado is not None:
        return resultado

    if proveedor_fallback is not None:
        logger.warning("Proveedor principal no respondió correctamente; probando fallback.")
        resultado = _intentar_con_proveedor(
            proveedor_fallback, prompt_sistema, prompt_usuario, "fallback", errores, clasificacion
        )
        if resultado is not None:
            return resultado

    logger.error("Se agotaron todos los proveedores disponibles; devolviendo extracción vacía.")
    return _extraccion_vacia(clasificacion, "; ".join(errores))