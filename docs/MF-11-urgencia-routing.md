# MF-11: Enrutamiento Condicional por Urgencia y Confianza

## 1. Propósito
El nodo de enrutamiento evalúa directamente la señal de urgencia/prioridad médica y la categoría de confianza calculada en MF-10 a partir del estado (`MediFlowState`). Con esta información, retorna la cadena correspondiente para dirigir el flujo del grafo hacia la rama de ejecución adecuada.

---

## 2. Reglas de Enrutamiento

El nodo procesa las señales en el siguiente orden de prioridad:

1. **Revisión Humana (`revision_humana`):** Se activa si la categoría de confianza es `Baja` o si existen errores de validación e inconsistencias clínicas en el estado.
2. **Urgencia (`urgencia`):** Se activa si la confianza es `Alta` o `Media` y la prioridad evaluada es `urgente` o `emergencia`.
3. **Estándar (`estandar`):** Se activa cuando la confianza es `Alta` o `Media` y no se detecta señal de urgencia.

---

## 3. Matriz de Decisiones

| Categoría Confianza | Señal de Urgencia / Prioridad | Inconsistencias / Errores | Ruta Destino |
| :--- | :--- | :--- | :--- |
| **Baja** | Indiferente | Indiferente | `"revision_humana"` |
| **Cualquiera** | Indiferente | Sí | `"revision_humana"` |
| **Alta / Media** | `urgente` o `emergencia` | No | `"urgencia"` |
| **Alta / Media** | Normal / `no_urgente` | No | `"estandar"` |

---

## 4. Integración en el Grafo (LangGraph)

El nodo se integra como un borde condicional (*conditional edge*) posterior a `evaluacion_confianza`, utilizando directamente las cadenas de texto retornadas para seleccionar la siguiente transmisión:

```python
builder.add_conditional_edges(
    "evaluacion_confianza",
    nodo_enrutamiento_urgencia,
    {
        "estandar": "nodo_procesamiento_estandar",
        "urgencia": "nodo_alerta_urgencia",
        "revision_humana": "nodo_revision_humana",
    }
)