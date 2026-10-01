from enum import Enum
from typing import List, Dict, Any
from app.schemas.respuesta import RespuestaProcesamiento

class RutaDestino(str, Enum):
    STANDARD = "standard"     # Escenario 1: Procesado correctamente
    EMERGENCY = "emergency"   # Escenario 2: Urgencia / Alerta
    HITL = "hitl"             # Escenario 3: Ambiguo / Inconsistente

def validar_consistencia_clinica(respuesta: RespuestaProcesamiento) -> Dict[str, Any]:
    """
    MF-09: Módulo de Validación de Consistencia e Inconsistencias Clínicas.
    """
    motivos_estructurados: Dict[str, List[str]] = {
        "faltantes": [],
        "invalidos": [],
        "contradictorios": []
    }
    
    clasif = respuesta.clasificacion
    extrac = respuesta.extraccion
    
    # 1. DETECCIÓN DE DATOS FALTANTES
    if clasif.tipo_documento != "No Clasificado":
        if not extrac.paciente or not extrac.paciente.nombre_completo:
            motivos_estructurados["faltantes"].append(
                "Falta el nombre completo del paciente en un documento ya clasificado."
            )
    
    if extrac.profesional and extrac.profesional.registro_profesional:
        if len(extrac.profesional.registro_profesional.strip()) < 3:
            motivos_estructurados["invalidos"].append(
                f"Registro profesional inválido: '{extrac.profesional.registro_profesional}' es demasiado corto."
            )

    if clasif.tipo_documento == "Receta Medica" and len(extrac.estudios_solicitados) > 0:
        motivos_estructurados["contradictorios"].append(
            "El documento es una 'Receta Medica' pero incluye estudios complejos."
        )

    prioridad_clasif = clasif.nivel_prioridad.lower() if clasif.nivel_prioridad else ""
    urgencia_extrac = extrac.nivel_urgencia.lower() if extrac.nivel_urgencia else ""
    
    es_urgente_clasif = prioridad_clasif in ["emergencia", "urgente"]   
    es_no_urgente_extrac = urgencia_extrac == "no_urgente"

    if es_urgente_clasif and es_no_urgente_extrac:
        motivos_estructurados["contradictorios"].append(
            "Conflicto de urgencia: Clasificador indica Urgencia/Emergencia pero Extractor indica No Urgente."
        )

    todos_los_errores = (
        motivos_estructurados["faltantes"] + 
        motivos_estructurados["invalidos"] + 
        motivos_estructurados["contradictorios"]
    )
    
    es_valido = len(todos_los_errores) == 0

    if not es_valido:
        ruta_assigned = RutaDestino.HITL
    elif urgencia_extrac in ["urgente", "emergencia"] or es_urgente_clasif:
        ruta_assigned = RutaDestino.EMERGENCY
    else:
        ruta_assigned = RutaDestino.STANDARD

    return {
        "validacion_ok": es_valido,
        "errores_validacion": todos_los_errores,
        "ruta_destino": ruta_assigned,
        "detalles_por_categoria": motivos_estructurados
    }
