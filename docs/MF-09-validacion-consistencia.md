Documentación Técnica: MF-09 - Validación de Consistencia e Inconsistencias
1. Descripción de la Actividad
Esta actividad consistió en la separación e implementación funcional del nodo de validación de consistencia clínica dentro del grafo principal de MediFlow. Originalmente, la validación se ejecutaba de forma acoplada dentro de nodo_validacion_pydantic. Para garantizar un flujo modular y permitir que los módulos posteriores (como la evaluación de confianza MF-10) consuman los datos de forma independiente, se aisló esta lógica en su propio nodo.
El flujo consolidado del grafo quedó establecido de la siguiente manera:
\(\text{validacion\_pydantic}\rightarrow \text{consistencia}\rightarrow \text{evaluacion\_confianza}\rightarrow \text{routing}\)
2. Implementación en el Grafo (app/graph/graph.py)
Se definió el nodo independiente nodo_validacion_consistencia encargado de interceptar el estado del documento clínico, procesar las inconsistencias y mapearlas al estado global del sistema:
• Función del Nodo: nodo_validacion_consistencia(state: MediFlowState) -> dict
• Lógica Principal: El nodo invoca la función externa validar_consistencia_clinica(state) para evaluar el contenido estructurado del documento y retorna un diccionario con la clave "inconsistencias".
python
def nodo_validacion_consistencia(state: MediFlowState) -> dict:
    """
    Nodo independiente para el módulo MF-09.
    Ejecuta la validación clínica y añade las inconsistencias al estado general.
    """
    resultado = validar_consistencia_clinica(state)
    return {
        "inconsistencias": resultado["inconsistencias"]
    }
3. Estructura y Manejo de Inconsistencias
El componente evalúa la información del documento clínico e identifica datos faltantes, inválidos o lógicas contradictorias que afecten el flujo de negocio. Cuando encuentra anomalías, genera un resultado estructurado que se inyecta en el estado para que MF-10 pueda aplicar penalizaciones diferenciadas.
La salida estructurada sigue el formato de la clave extraída en el retorno del nodo:
json
{
  "inconsistencias": [
    {
      "campo": "motivo_consulta",
      "tipo_error": "contradictorio_o_faltante",
      "descripcion": "El diagnóstico no coincide con los síntomas reportados."
    }
  ]
}
4. Pruebas e Integración (E2E)
• Casos Estándar y Válidos: Documentos clínicos procesados correctamente que transicionan de nodo_validacion_pydantic a consistencia sin registrar penalizaciones en el estado.
• Casos Inconsistentes / Datos Faltantes: Simulación de payloads con inconsistencias clínicas para verificar que el estado capture el arreglo de errores, permitiendo que la lógica de confianza (confianza.py) aplique los descuentos correspondientes (-0.05 para secundarios y -0.10 para críticos).
• Validación en el Grafo: Se verificó la correcta declaración de builder.add_node("consistencia", nodo_validacion_consistencia) Se verificó la integración del nodo mediante la suite de pruebas correspondiente.
