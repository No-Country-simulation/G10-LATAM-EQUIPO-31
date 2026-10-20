from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import ExtraccionClinica, Paciente
from app.schemas.respuesta import ResultadoValidacion, RespuestaProcesamiento


def test_respuesta_procesamiento_valida():
    clasificacion = Classification(
        tipo_documento=DocumentType.RECETA_MEDICA,
        especialidad="Cardiologia",
        nivel_prioridad="Rutina",
        score_confianza_clasificacion=0.95,
        justificacion="Documento identificado como receta médica.",
    )

    extraccion = ExtraccionClinica(
        paciente=Paciente(
            nombre_completo="Laura Martínez Gómez",
            edad=45,
        )
    )

    validacion = ResultadoValidacion(
        validacion_ok=True,
        errores_validacion=[],
    )

    respuesta = RespuestaProcesamiento(
        status="procesado",
        documento_id="DOC-001",
        clasificacion=clasificacion,
        extraccion=extraccion,
        validacion=validacion,
    )

    assert respuesta.status == "procesado"
    assert respuesta.documento_id == "DOC-001"
    assert respuesta.validacion.validacion_ok is True
    assert respuesta.clasificacion.tipo_documento == DocumentType.RECETA_MEDICA