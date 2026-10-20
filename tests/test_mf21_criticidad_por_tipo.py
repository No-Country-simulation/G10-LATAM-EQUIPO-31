"""
tests/test_mf21_criticidad_por_tipo.py

Pruebas de MF-21: matriz de criticidad por tipo documental en app/graph/confianza.py.
"""
from app.graph.confianza import nodo_evaluacion_confianza
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import ExtraccionClinica, Paciente, Profesional, Diagnostico


def _clasificacion(tipo_doc, score=0.95):
    return Classification(
        tipo_documento=tipo_doc,
        especialidad="Medicina General",
        nivel_prioridad="Rutina",
        score_confianza_clasificacion=score,
        justificacion="Prueba",
    )


def test_caso_central_certificado_medico_sin_medicamentos_ni_procedimientos():
    """EL CASO DE LA PROPUESTA DE KATE: un certificado médico completo,
    sin medicamentos/estudios/procedimientos (porque no le corresponden),
    NO debe caer a Media/revision_humana solo por esas ausencias."""
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Ana Pérez", edad=40),
        profesional=Profesional(nombre_completo="Dr. Gómez", registro_profesional="12345"),
        diagnosticos=[Diagnostico(descripcion="Apto para actividad física")],
        medicamentos=[],
        estudios_solicitados=[],
        procedimientos_solicitados=[],
        campos_no_encontrados=[],
    )
    state = {
        "clasificacion": _clasificacion(DocumentType.CERTIFICADO_MEDICO, score=0.95),
        "extraccion": extraccion,
    }

    resultado = nodo_evaluacion_confianza(state)

    assert resultado["categoria_confianza"] == "Alta"
    assert resultado["score_confianza_final"] >= 0.90
    assert resultado["motivos_confianza"] == ["Sin inconsistencias detectadas"]


def test_receta_sin_medicamentos_si_penaliza():
    """Una RECETA sin medicamentos sí es un problema real (medicamentos
    es crítico para ese tipo) -> sí debe penalizar."""
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Ana Pérez", edad=40),
        profesional=Profesional(nombre_completo="Dr. Gómez", registro_profesional="12345"),
        diagnosticos=[Diagnostico(descripcion="Hipertensión")],
        medicamentos=[],  # crítico para receta
        campos_no_encontrados=[],
    )
    state = {
        "clasificacion": _clasificacion(DocumentType.RECETA_MEDICA, score=0.95),
        "extraccion": extraccion,
    }

    resultado = nodo_evaluacion_confianza(state)

    assert "medicamentos" in resultado["motivos_confianza"]
    assert resultado["categoria_confianza"] != "Alta"


def test_orden_sin_procedimientos_penaliza_pero_sin_medicamentos_no():
    """Una ORDEN sin procedimientos_solicitados sí penaliza (crítico);
    sin medicamentos NO penaliza (no aplica a ese tipo)."""
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Ana Pérez", edad=40),
        profesional=Profesional(nombre_completo="Dr. Gómez", registro_profesional="12345"),
        diagnosticos=[Diagnostico(descripcion="Sospecha de fractura")],
        medicamentos=[],  # no aplica a Orden -> no debe penalizar
        procedimientos_solicitados=[],  # crítico para Orden -> sí debe penalizar
        campos_no_encontrados=[],
    )
    state = {
        "clasificacion": _clasificacion(DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO, score=0.95),
        "extraccion": extraccion,
    }

    resultado = nodo_evaluacion_confianza(state)

    assert "procedimientos_solicitados" in resultado["motivos_confianza"]
    assert "medicamentos" not in resultado["motivos_confianza"]


def test_tipo_desconocido_trata_todo_como_critico_por_seguridad():
    """Si tipo_documento no está en la matriz (NO_CLASIFICADO u otro),
    todas las entidades de lista se tratan como críticas."""
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Ana Pérez", edad=40),
        profesional=Profesional(nombre_completo="Dr. Gómez", registro_profesional="12345"),
        diagnosticos=[Diagnostico(descripcion="x")],
        medicamentos=[],
        procedimientos_solicitados=[],
        campos_no_encontrados=[],
    )
    state = {
        "clasificacion": _clasificacion(DocumentType.NO_CLASIFICADO, score=0.95),
        "extraccion": extraccion,
    }

    resultado = nodo_evaluacion_confianza(state)

    assert "medicamentos" in resultado["motivos_confianza"]
    assert "procedimientos_solicitados" in resultado["motivos_confianza"]


def test_profesional_ausente_siempre_penaliza_sin_importar_tipo():
    """profesional es siempre crítico, no varía por tipo de documento."""
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Ana Pérez", edad=40),
        profesional=None,
        diagnosticos=[Diagnostico(descripcion="x")],
        campos_no_encontrados=[],
    )
    state = {
        "clasificacion": _clasificacion(DocumentType.CERTIFICADO_MEDICO, score=0.95),
        "extraccion": extraccion,
    }

    resultado = nodo_evaluacion_confianza(state)

    assert "profesional" in resultado["motivos_confianza"]


def test_no_duplica_penalizacion_si_llm_reporta_entidad_en_campos_no_encontrados():
    """Si el string 'medicamentos' aparece TAMBIÉN en campos_no_encontrados
    (reportado por el LLM), no debe penalizar dos veces (una por atributo
    real, otra por texto)."""
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Ana Pérez", edad=40),
        profesional=Profesional(nombre_completo="Dr. Gómez", registro_profesional="12345"),
        diagnosticos=[Diagnostico(descripcion="Hipertensión")],
        medicamentos=[],
        campos_no_encontrados=["medicamentos"],  # el LLM lo reportó también como texto
    )
    state = {
        "clasificacion": _clasificacion(DocumentType.RECETA_MEDICA, score=0.95),
        "extraccion": extraccion,
    }

    resultado = nodo_evaluacion_confianza(state)

    # Solo UNA mención de "medicamentos" en los motivos, no dos
    assert resultado["motivos_confianza"].count("medicamentos") == 1


def test_informe_sin_estudios_solicitados_si_penaliza():
    """Un INFORME DE ESTUDIO sin estudios_solicitados sí penaliza
    (crítico para ese tipo); sin medicamentos NO penaliza (no aplica)."""
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Ana Pérez", edad=40),
        profesional=Profesional(nombre_completo="Dr. Gómez", registro_profesional="12345"),
        diagnosticos=[Diagnostico(descripcion="Hallazgo radiológico")],
        medicamentos=[],  # no aplica a Informe
        estudios_solicitados=[],  # crítico para Informe
        campos_no_encontrados=[],
    )
    state = {
        "clasificacion": _clasificacion(DocumentType.INFORME_ESTUDIO_DIAGNOSTICO, score=0.95),
        "extraccion": extraccion,
    }

    resultado = nodo_evaluacion_confianza(state)

    assert "estudios_solicitados" in resultado["motivos_confianza"]
    assert "medicamentos" not in resultado["motivos_confianza"]


def test_certificado_sigue_sin_penalizar_estudios_ni_medicamentos():
    """Repite el caso central de Kate, ahora que estudios_solicitados sí
    puede ser crítico en general -> confirma que para Certificado sigue
    sin aplicar (no se rompió el caso que motivó toda la propuesta)."""
    extraccion = ExtraccionClinica(
        paciente=Paciente(nombre_completo="Ana Pérez", edad=40),
        profesional=Profesional(nombre_completo="Dr. Gómez", registro_profesional="12345"),
        diagnosticos=[Diagnostico(descripcion="Apto para actividad física")],
        medicamentos=[],
        estudios_solicitados=[],
        procedimientos_solicitados=[],
        campos_no_encontrados=[],
    )
    state = {
        "clasificacion": _clasificacion(DocumentType.CERTIFICADO_MEDICO, score=0.95),
        "extraccion": extraccion,
    }

    resultado = nodo_evaluacion_confianza(state)

    assert resultado["categoria_confianza"] == "Alta"
    assert resultado["motivos_confianza"] == ["Sin inconsistencias detectadas"]