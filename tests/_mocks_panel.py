"""Datos simulados para probar el panel HITL sin API, sin OCI y sin LLM (se importa UNA vez)."""
import os
import sys
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "frontend"))
import utils_frontend as u  # noqa: E402

AHORA = datetime.now(timezone.utc)


def hace(**kw):
    return (AHORA - timedelta(**kw)).isoformat()


def pendiente(doc_id, tipo, nivel, urgente, score, categoria, motivos, justificacion):
    return {
        "documento_id": doc_id, "estado": "revision_humana", "timestamp": hace(hours=2),
        "nivel_urgencia": nivel, "urgente": urgente,
        "resultado": {
            "validacion_ok": True, "score_confianza_final": score, "categoria_confianza": categoria,
            "motivos_confianza": motivos, "justificacion_enrutamiento": justificacion, "requiere_auditoria_humana": True,
            "clasificacion": {"tipo_documento": tipo, "especialidad": "Cardiologia", "score_confianza_clasificacion": 0.35},
            "extraccion": {
                "paciente": {"nombre_completo": "Ana Pérez", "edad": None},
                "medicamentos": [{"nombre": "Enalapril", "dosis": "10 mg"}],
                "nivel_urgencia": nivel, "campos_no_encontrados": ["paciente_edad"],
            },
        },
    }


PEND = [
    pendiente("DOC-0417", "Certificado Medico", "no_urgente", False, 0.64, "Media",
              ["Confianza media (0.64)"], "Confianza Media: requiere revisión humana"),
    pendiente("URGBAJA-001", "Receta Medica", "emergencia", True, 0.42, "Baja",
              ["Autoevaluación del clasificador baja (0.35)", "Faltan campos: paciente_edad"],
              "Confianza Baja: va a revisión aunque es urgente"),
]
RES = [
    {"documento_id": "DOC-0398", "decision": "APROBADO", "auditor": "kimberlyn.r", "timestamp": hace(hours=1), "tipo_documento": "Receta Medica"},
    {"documento_id": "DOC-0391", "decision": "RECHAZADO", "auditor": "ana", "timestamp": hace(hours=3), "tipo_documento": "No Clasificado",
     "motivo": "TIPO_INCORRECTO", "notas": "No es un documento clínico."},
]

LLAMADAS = []        # lo que el panel intentó guardar (las pruebas lo inspeccionan)
ESTADO = {"conflicto": False}


def reset():
    LLAMADAS.clear()
    ESTADO["conflicto"] = False


def _registrar(item, decision, notas, auditor, motivo=None):
    if ESTADO["conflicto"]:
        raise u.ErrorDecisionConflicto("409: El documento ya no está pendiente.")
    LLAMADAS.append(("decision", item["documento_id"], decision, notas, auditor, motivo))


u.obtener_bandeja = lambda limite=50: {
    "pendientes": [u._item_desde_evento(e) for e in PEND], "total_pendientes": len(PEND),
    "resueltos": [u._fila_decision(e) for e in RES], "avisos": [],
}
u.obtener_linea_tiempo = lambda d: [{"evento": "Procesamiento", "fecha": u.formatear_fecha(hace(hours=2)), "detalle": "estado: revision_humana"}]
u.registrar_decision_auditoria = _registrar
