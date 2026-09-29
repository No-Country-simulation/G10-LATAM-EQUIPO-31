from app.schemas.respuesta import RespuestaProcesamiento, ResultadoValidacion
from app.schemas.clasificacion import DocumentType

def validar_consistencia_clinica(respuesta: RespuestaProcesamiento) -> ResultadoValidacion:
    """
    Ejecuta las reglas de validación de consistencia (MF-09) sobre los datos extraídos
    y clasificados de un documento clínico.
    """
    errores = []
    
    # Referencias cortas de los datos de tus compañeros
    clasif = respuesta.clasificacion
    extrac = respuesta.extraction
    
    # --- REGLA 1: Tipo de Documento vs Contenido ---
    if clasif.tipo_documento == DocumentType.RECETA_MEDICA:
        if len(extrac.estudios_solicitados) > 0:
            errores.append(
                f"Inconsistencia: El documento está clasificado como 'Receta Médica', "
                f"pero contiene {len(extrac.estudios_solicitados)} estudio(s) solicitado(s)."
            )

    # --- REGLA 2: Consistencia de Criterio de Urgencia ---
    prioridad_clasificador = clasif.nivel_prioridad.lower() if clasif.nivel_prioridad else ""
    urgencia_extractor = extrac.nivel_urgencia.value.lower() if extrac.nivel_urgencia else ""
    
    if "emergencia" in prioridad_clasificador or "urgente" in prioridad_clasificador:
        if "no_urgente" in urgencia_extractor:
            errores.append(
                "Contradicción: El Agente Clasificador marca el caso como Urgente/Emergencia, "
                "pero el Agente Extractor determinó que las señales de gravedad son 'No Urgente'."
            )

    # --- REGLA 3: Datos Faltantes Críticos ---
    if clasif.tipo_documento != "No Clasificado":
        if not extrac.paciente or not extrac.paciente.nombre_completo:
            errores.append("Datos faltantes: No se logró extraer el nombre completo del paciente.")
            
    # --- REGLA 4: Identificación del Profesional ---
    if extrac.profesional:
        prof = extrac.profesional
        if prof.registro_profesional and not prof.especialidad:
            errores.append(
                "Inconsistencia: Se extrajo el registro médico del profesional, "
                "pero no se pudo determinar su especialidad."
            )

    # --- CONSTRUCCIÓN DEL RESULTADO ---
    es_valido = len(errores) == 0
    
    return ResultadoValidacion(
        validacion_ok=es_valido,
        errores_validacion=errores
    )
