"""
tests/test_graph.py

Pruebas del esqueleto del grafo de MediFlow (MF-07, Sprint 1).
Responsable: Jennifer Silva.

Ejecutar desde la raíz del repositorio:
    pytest tests/test_graph.py -v

Usa el mismo documento de ejemplo del brief oficial, para poder comparar
el resultado contra el JSON de ejemplo que trae el brief.
"""
from app.graph.graph import grafo_mediflow, nodo_validacion_pydantic


DOCUMENTO_PRUEBA = {
    "documento_id": "DOC-CLIN-2026-8942",
    "tipo_archivo": "PDF",
    "documento_contenido": (
        "HOSPITAL SANTA LUCIA - INFORME DE ESTUDIO RADIOLOGICO. "
        "Paciente: Carlos Eduardo Mendes, 52 anos. "
        "Medico Solicitante: Dra. Renata Silveira MP 145892. "
        "Estudio: Tomografia de Torax con contraste. "
        "Conclusion: Cuadro compatible con Tromboembolismo Pulmonar Agudo."
    ),
    "canal_origen": "Guardia_Emergencias",
}


def test_grafo_corre_de_punta_a_punta():
    """El recorrido completo Inicio -> Clasificador -> Extractor ->
    Validación Pydantic -> Fin debe ejecutarse sin errores y devolver
    todos los campos esperados."""
    resultado = grafo_mediflow.invoke(DOCUMENTO_PRUEBA)

    # Campos de entrada, intactos
    assert resultado["documento_id"] == "DOC-CLIN-2026-8942"

    # Campos que debería haber llenado el Clasificador (placeholder)
    assert resultado["tipo_documento"] == "Informe de Estudio por Imágenes"
    assert resultado["nivel_prioridad"] == "Urgente"

    # Campos que debería haber llenado el Extractor (placeholder)
    assert resultado["paciente_nombre"] == "Carlos Eduardo Mendes"
    assert resultado["cie10_sugerido"] == "I26.9"


def test_validacion_ok_con_datos_completos():
    """Con Clasificador y Extractor completos (caso normal), la
    validación básica debe cerrar sin errores."""
    resultado = grafo_mediflow.invoke(DOCUMENTO_PRUEBA)

    assert resultado["validacion_ok"] is True
    assert resultado["errores_validacion"] == []


def test_validacion_detecta_campos_faltantes_del_extractor():
    """Si al Extractor le faltan campos obligatorios, la validación debe
    marcarlos uno por uno, no solo decir 'inválido' de forma genérica."""
    estado_incompleto = {
        "documento_id": "DOC-TEST-001",
        "tipo_documento": "Informe de Imágenes",
        "especialidad": "Radiología",
        "nivel_prioridad": "Urgente",
        "score_confianza_clasificacion": 0.9,
        # Faltan a propósito: paciente_nombre, paciente_edad,
        # medico_nombre, medico_matricula
    }

    resultado = nodo_validacion_pydantic(estado_incompleto)

    assert resultado["validacion_ok"] is False
    assert len(resultado["errores_validacion"]) == 4
    assert "Falta el campo obligatorio: paciente_nombre" in resultado["errores_validacion"]


def test_validacion_detecta_campos_faltantes_del_clasificador():
    """Mismo chequeo, pero cuando lo que falta son campos del
    Clasificador en vez del Extractor."""
    estado_incompleto = {
        "documento_id": "DOC-TEST-002",
        "paciente_nombre": "Ana Pérez",
        "paciente_edad": 40,
        "medico_nombre": "Dr. Gómez",
        "medico_matricula": "12345",
        # Faltan a propósito: tipo_documento, especialidad,
        # nivel_prioridad, score_confianza_clasificacion
    }

    resultado = nodo_validacion_pydantic(estado_incompleto)

    assert resultado["validacion_ok"] is False
    assert len(resultado["errores_validacion"]) == 4