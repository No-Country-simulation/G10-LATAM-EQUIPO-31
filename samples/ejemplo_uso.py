"""
Ejemplo ejecutable de MF-06 (Agente Extractor), usando el schema real
`ExtraccionClinica` (app/schemas/extraccion_schema.py).

Corre sin API key ni internet: usa un proveedor LLM "falso" que simula
la respuesta de un modelo real, solo para ver el flujo completo:

    texto del documento + clasificación -> extractor -> ExtraccionClinica validado

Ejecutar con:
    python -m samples.ejemplo_uso
(parado en la raíz del repo)
"""

from __future__ import annotations

import json

from app.agents.extractor import ResultadoClasificacionMock, extraer_datos_clinicos

DOCUMENTO_EJEMPLO = """
## Orden Médica
Paciente: Ana Restrepo
Documento: CC 1098765432
Edad: 34 años
Sexo: F

Médico: Dr. Carlos Mendoza
Registro médico: RM-45210
Especialidad: Medicina Interna

Diagnóstico principal: Hipertensión arterial (I10)
Medicamentos: Losartán 50mg vía oral cada 24 horas por 30 días

Estudios solicitados: Hemograma completo (laboratorio), perfil lipídico (laboratorio)

Paciente refiere dolor torácico intenso y disnea súbita en la última hora.
"""


class ProveedorFalso:
    """Simula un LLM devolviendo directamente el JSON esperado por el prompt."""

    def generar(self, prompt_sistema: str, prompt_usuario: str) -> str:
        return json.dumps(
            {
                "tipo_documento": "ORDEN_MEDICA",
                "especialidad": "Medicina Interna",
                "paciente": {
                    "nombre_completo": "Ana Restrepo",
                    "tipo_documento": "CC",
                    "numero_documento": "1098765432",
                    "edad": 34,
                    "sexo": "F",
                },
                "profesional": {
                    "nombre_completo": "Carlos Mendoza",
                    "registro_profesional": "RM-45210",
                    "especialidad": "Medicina Interna",
                    "institucion": None,
                },
                "diagnosticos": [
                    {"descripcion": "Hipertensión arterial", "codigo_cie10": "I10", "tipo": "principal"}
                ],
                "medicamentos": [
                    {
                        "nombre": "Losartán",
                        "dosis": "50mg",
                        "via_administracion": "oral",
                        "frecuencia": "cada 24 horas",
                        "duracion": "30 días",
                    }
                ],
                "estudios_solicitados": [
                    {"tipo": "laboratorio", "descripcion": "Hemograma completo", "prioridad": None},
                    {"tipo": "laboratorio", "descripcion": "perfil lipídico", "prioridad": None},
                ],
                "nivel_urgencia": "urgente",
                "senales_gravedad": ["dolor torácico intenso", "disnea súbita en la última hora"],
                "fecha_documento": None,
                "observaciones": None,
                "campos_no_encontrados": ["fecha_documento"],
            }
        )


def main() -> None:
    clasificacion_mock = ResultadoClasificacionMock(
        tipo_documento="ORDEN_MEDICA", especialidad="Medicina Interna"
    )

    resultado = extraer_datos_clinicos(
        texto_documento=DOCUMENTO_EJEMPLO,
        clasificacion=clasificacion_mock,
        proveedor=ProveedorFalso(),
    )

    print("=== ExtraccionClinica (validado por Pydantic) ===")
    print(resultado.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
