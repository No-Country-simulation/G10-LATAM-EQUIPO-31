from app.schemas.clasificacion import Classification, DocumentType
import pytest
from pydantic import ValidationError


def test_clasificacion_valida():
    clasificacion = Classification(
        tipo_documento=DocumentType.RECETA_MEDICA,
        especialidad="Cardiologia",
        nivel_prioridad="Rutina",
        score_confianza_clasificacion=0.95,
        justificacion="Documento identificado como receta médica.",
    )

    assert clasificacion.tipo_documento == DocumentType.RECETA_MEDICA
    assert clasificacion.especialidad == "Cardiologia"
    assert clasificacion.score_confianza_clasificacion == 0.95

def test_clasificacion_rechaza_confianza_fuera_de_rango():
    with pytest.raises(ValidationError):
        Classification(
            tipo_documento=DocumentType.RECETA_MEDICA,
            especialidad="Cardiologia",
            nivel_prioridad="Rutina",
            score_confianza_clasificacion=1.5,
            justificacion="Prueba",
        )