"""
tests/test_mf25_derivacion_hitl.py
MF-25 | Derivación a HITL del caso estándar: pruebas de regresión.

Contexto. En la demo del Sprint 3 un documento esperado como estándar
(`caso-estandar.pdf`, el alta médica de una persona con una fractura) terminó
en revisión humana. El clasificador lo tipó como "Orden de Solicitud de
Procedimiento"; para ese tipo la matriz de criticidad (MF-21) exige
`procedimientos_solicitados`, el documento no los trae, la categoría baja a
Media aunque el score sea alto y el routing (MF-11) deriva a HITL.

Estas pruebas fijan, SIN usar ningún modelo, el comportamiento de los nodos
`nodo_evaluacion_confianza` (MF-10/MF-21) y `nodo_routing_condicional`
(MF-11) para esos casos:
  - los que requieren revisión humana siguen yendo a HITL;
  - los casos estándar adecuados siguen el flujo automático.

No modifican código de producto. Si la matriz de MF-21 cambia (por ejemplo,
dejar de exigir medicamentos en epicrisis), la prueba correspondiente debe
actualizarse a propósito.

Ejecutar: pytest tests/test_mf25_derivacion_hitl.py -v
"""
import pytest

from app.graph.confianza import nodo_evaluacion_confianza
from app.graph.routing import nodo_routing_condicional
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import ExtraccionClinica, NivelUrgencia, Paciente, Profesional


def _estado(
    tipo,
    *,
    medicamentos=0,
    estudios=0,
    procedimientos=0,
    urgencia=NivelUrgencia.NO_URGENTE,
    score_clasificador=0.96,
):
    """Estado equivalente al que llega a confianza y routing: un paciente y un
    profesional identificados, un diagnóstico y las listas indicadas."""
    clasificacion = Classification(
        tipo_documento=tipo,
        especialidad="Medicina General",
        nivel_prioridad="Rutina",
        score_confianza_clasificacion=score_clasificador,
        justificacion="Prueba de regresión MF-25",
    )
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Paciente Ficticio", edad=40),
        nivel_urgencia=urgencia,
    )
    extraccion.profesional = Profesional(nombre_completo="Dr. Ficticio")
    extraccion.diagnosticos = ["Diagnóstico de prueba"]
    extraccion.medicamentos = ["Medicamento de prueba"] * medicamentos
    extraccion.estudios_solicitados = ["Estudio de prueba"] * estudios
    extraccion.procedimientos_solicitados = ["Procedimiento de prueba"] * procedimientos
    extraccion.campos_no_encontrados = []
    return {
        "clasificacion": clasificacion,
        "extraccion": extraccion,
        "errores_validacion": [],
        "inconsistencias": [],
    }


def _recorrer(estado):
    """Aplica los dos nodos en el orden del grafo: confianza y routing."""
    estado = dict(estado)
    estado.update(nodo_evaluacion_confianza(estado))
    estado.update(nodo_routing_condicional(estado))
    return estado


# --- Casos que requieren revisión humana: deben seguir yendo a HITL ---

def test_orden_sin_procedimientos_va_a_hitl_aunque_el_score_sea_alto():
    """Es el caso de `caso-estandar.pdf`: el score (0.93) es alto, pero faltan
    los procedimientos de una orden, la categoría baja a Media y va a HITL."""
    final = _recorrer(_estado(DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO))

    assert final["score_confianza_final"] >= 0.80
    assert final["categoria_confianza"] == "Media"
    assert "procedimientos_solicitados" in final["motivos_confianza"]
    assert final["destino_principal"] == "revision_humana"
    assert final["requiere_auditoria_humana"] is True
    assert final.get("departamento_destino") is None


def test_epicrisis_sin_medicamentos_va_a_hitl_regla_actual():
    """Regla actual de MF-21: en una epicrisis los medicamentos son críticos.
    Documenta la regla vigente; si se decide relajarla, actualizar esta prueba."""
    final = _recorrer(_estado(DocumentType.EPICRISIS_INFORME_ALTA))

    assert final["categoria_confianza"] == "Media"
    assert "medicamentos" in final["motivos_confianza"]
    assert final["destino_principal"] == "revision_humana"


def test_receta_sin_medicamentos_va_a_hitl():
    final = _recorrer(_estado(DocumentType.RECETA_MEDICA))

    assert final["categoria_confianza"] == "Media"
    assert "medicamentos" in final["motivos_confianza"]
    assert final["destino_principal"] == "revision_humana"


def test_orden_urgente_sin_procedimientos_va_a_hitl_conservando_la_urgencia():
    """La confianza manda sobre la ruta: un caso urgente incompleto no va a la
    cola de emergencia sin revisión, pero la señal de urgencia se conserva."""
    final = _recorrer(
        _estado(DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO, urgencia=NivelUrgencia.EMERGENCIA)
    )

    assert final["destino_principal"] == "revision_humana"
    assert final["urgente"] is True
    assert final["requiere_auditoria_humana"] is True


# --- Casos estándar adecuados: deben seguir el flujo automático ---

@pytest.mark.parametrize(
    "tipo, kwargs, departamento",
    [
        (DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO, {"procedimientos": 1}, "auditoria_autorizaciones"),
        (DocumentType.RECETA_MEDICA, {"medicamentos": 1}, "farmacia_hospitalaria"),
        (DocumentType.CERTIFICADO_MEDICO, {}, "historia_clinica_electronica"),
        (DocumentType.EPICRISIS_INFORME_ALTA, {"medicamentos": 1}, "historia_clinica_electronica"),
        (DocumentType.INFORME_ESTUDIO_DIAGNOSTICO, {"estudios": 1}, "historia_clinica_electronica"),
    ],
)
def test_documento_completo_sigue_el_flujo_estandar(tipo, kwargs, departamento):
    final = _recorrer(_estado(tipo, **kwargs))

    assert final["categoria_confianza"] == "Alta"
    assert final["destino_principal"] == "estandar"
    assert final["requiere_auditoria_humana"] is False
    assert final["urgente"] is False
    assert final["departamento_destino"] == departamento


def test_certificado_sin_medicamentos_no_se_penaliza():
    """Un certificado no necesita medicamentos (MF-21): no debe ir a HITL."""
    final = _recorrer(_estado(DocumentType.CERTIFICADO_MEDICO, medicamentos=0))

    assert final["categoria_confianza"] == "Alta"
    assert final["destino_principal"] == "estandar"

def test_orden_con_estudios_y_sin_procedimientos_sigue_el_flujo_estandar():
    """Una orden de laboratorio/imágenes trae `estudios_solicitados`, no procedimientos."""
    final = _recorrer(_estado(DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO, estudios=1))

    assert final["categoria_confianza"] == "Alta"
    assert final["destino_principal"] == "estandar"
    assert final["departamento_destino"] == "auditoria_autorizaciones"


def test_orden_sin_estudios_ni_procedimientos_sigue_yendo_a_hitl():
    final = _recorrer(_estado(DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO))

    assert final["categoria_confianza"] == "Media"
    assert final["destino_principal"] == "revision_humana"