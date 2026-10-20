from app.schemas.extraccion import (
    ExtraccionClinica,
    Paciente,
    Profesional,
    Diagnostico,
    Medicamento,
    NivelUrgencia,
)


def test_extraccion_clinica_valida():
    extraccion = ExtraccionClinica(
        paciente=Paciente(
            nombre_completo="Laura Martínez Gómez",
            edad=45,
        ),
        profesional=Profesional(
            nombre_completo="Dr. Andrés Ramírez",
            registro_profesional="MP-45821",
            especialidad="Cardiologia",
        ),
        diagnosticos=[
            Diagnostico(
                descripcion="Hipertensión arterial esencial",
                codigo_cie10="I10",
                tipo="principal",
            )
        ],
        medicamentos=[
            Medicamento(
                nombre="Losartán",
                dosis="50 mg",
                frecuencia="cada 12 horas",
                duracion="30 días",
            )
        ],
        nivel_urgencia=NivelUrgencia.NO_URGENTE,
    )

    assert extraccion.paciente.nombre_completo == "Laura Martínez Gómez"
    assert extraccion.diagnosticos[0].codigo_cie10 == "I10"
    assert extraccion.medicamentos[0].nombre == "Losartán"
    assert extraccion.nivel_urgencia == NivelUrgencia.NO_URGENTE