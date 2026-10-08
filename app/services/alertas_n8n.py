"""
app/services/alertas_n8n.py

Alertas de casos urgentes vía n8n -- MF-14.

Cuando un documento queda marcado como urgente, MediFlow envía un evento por
webhook a un workflow de n8n, que lo reparte por Slack y correo electrónico
(ver docs/MF-14-alertas-n8n.md y n8n/mf14-alerta-caso-urgente.json).

DESACOPLAMIENTO (requisito de MF-14): este módulo NUNCA propaga excepciones.
Si n8n está caído, tarda más del timeout, devuelve un error HTTP, o la
variable de entorno no está configurada, el resultado es un log y `False`;
el procesamiento y la persistencia del documento no se ven afectados. La
ruta lo ejecuta además como tarea en segundo plano, después de persistir
resultado e historial y de armar la respuesta.

PRIVACIDAD: el evento NO incluye datos identificatorios del paciente
(nombre, documento de identidad, edad) ni el contenido del documento. Solo
lo necesario para que quien recibe la alerta ubique el caso: documento_id,
destino, tipo de documento, especialidad, nivel de urgencia, categoría de
confianza y las señales de gravedad que ya extrajo el Extractor.
"""
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("mediflow.app.services.alertas_n8n")

ENV_WEBHOOK_URL = "N8N_ALERT_WEBHOOK_URL"
ENV_WEBHOOK_TOKEN = "N8N_ALERT_WEBHOOK_TOKEN"

# Header que el webhook de n8n valida (Header Auth) cuando hay token.
HEADER_TOKEN = "X-MediFlow-Token"

# Tiempo máximo de espera al webhook. Corto a propósito: la alerta es
# secundaria y no debe retener recursos del servidor si n8n no responde.
TIMEOUT_SEGUNDOS = 5.0

MAX_SENALES_GRAVEDAD = 3


def debe_alertar(envelope: dict) -> bool:
    """
    Condición de la alerta: la señal reconciliada `urgente` (MF-11) es True,
    sin importar el destino final (`urgente` o `revision_humana`).

    Un documento urgente con confianza Media/Baja termina en
    revision_humana pero conserva urgente=True: con una condición por
    destino (estado == "urgente") esos casos no generarían alerta.
    Cambiar el criterio es modificar solo esta función.
    """
    return envelope.get("urgente") is True


def _valor(obj: Any) -> Any:
    """Normaliza Enums (str, Enum) al valor plano para serializar a JSON."""
    return getattr(obj, "value", obj)


def construir_evento_alerta(envelope: dict, estado_completo: dict | None) -> dict:
    """
    Arma el payload que se envía a n8n a partir del envelope persistido y
    del estado completo del grafo. Solo campos no identificatorios.
    """
    estado_completo = estado_completo or {}
    clasificacion = estado_completo.get("clasificacion") or {}
    extraccion = estado_completo.get("extraccion") or {}

    senales = list(extraccion.get("senales_gravedad") or [])[:MAX_SENALES_GRAVEDAD]

    return {
        "documento_id": envelope.get("documento_id"),
        "estado": envelope.get("estado"),
        "urgente": True,
        "timestamp": envelope.get("timestamp"),
        "nivel_urgencia": _valor(envelope.get("nivel_urgencia")),
        "tipo_documento": _valor(clasificacion.get("tipo_documento")),
        "especialidad": clasificacion.get("especialidad"),
        "categoria_confianza": estado_completo.get("categoria_confianza"),
        "score_confianza_final": estado_completo.get("score_confianza_final"),
        "requiere_auditoria_humana": estado_completo.get("requiere_auditoria_humana"),
        "senales_gravedad": senales,
        "justificacion_enrutamiento": estado_completo.get("justificacion_enrutamiento"),
    }


def notificar_caso_urgente(evento: dict) -> bool:
    """
    Envía el evento al webhook de n8n. Devuelve True si n8n respondió 2xx.
    Nunca lanza excepciones.
    """
    documento_id = evento.get("documento_id")
    url = os.getenv(ENV_WEBHOOK_URL, "").strip()
    if not url:
        logger.info(
            "Alerta omitida para documento_id=%s: %s no está configurada.",
            documento_id, ENV_WEBHOOK_URL,
        )
        return False

    headers = {}
    token = os.getenv(ENV_WEBHOOK_TOKEN, "").strip()
    if token:
        headers[HEADER_TOKEN] = token

    try:
        respuesta = httpx.post(
            url, json=evento, headers=headers, timeout=TIMEOUT_SEGUNDOS
        )
        respuesta.raise_for_status()
    except Exception as exc:
        # No se loguea str(exc): los errores de httpx incluyen la URL del
        # webhook, que puede contener un identificador secreto.
        estado_http = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "No se pudo enviar la alerta urgente de documento_id=%s a n8n "
            "(%s%s). El procesamiento no se ve afectado.",
            documento_id,
            type(exc).__name__,
            f", HTTP {estado_http}" if estado_http else "",
        )
        return False

    logger.info("Alerta urgente enviada a n8n: documento_id=%s", documento_id)
    return True


def emitir_alerta_si_corresponde(envelope: dict, estado_completo: dict | None) -> bool:
    """
    Punto de entrada que usa la ruta (como tarea en segundo plano): decide,
    arma el evento y notifica. Cualquier error -- incluso un bug al armar el
    evento -- se absorbe: devuelve False y queda en el log.
    """
    try:
        if not debe_alertar(envelope):
            return False
        return notificar_caso_urgente(construir_evento_alerta(envelope, estado_completo))
    except Exception:
        logger.exception(
            "Fallo inesperado al emitir la alerta de documento_id=%s; "
            "el procesamiento no se ve afectado.",
            envelope.get("documento_id") if isinstance(envelope, dict) else None,
        )
        return False
