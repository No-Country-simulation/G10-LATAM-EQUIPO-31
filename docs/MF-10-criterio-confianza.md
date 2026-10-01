# MF-10: Evaluación de Confianza y Ponderación Diferenciada

## 1. Propósito
El nodo `evaluacion_confianza` calcula la métrica global de confiabilidad (`score_confianza_final`) y la clasifica en una categoría de decisión (`Alta`, `Media`, `Baja`). Su objetivo es prevenir que omisiones menores de datos desvíen innecesariamente un documento a revisión humana, manteniendo un control estricto ante errores estructurales o contradicciones clínicas.

---

## 2. Ponderación General
El score final combina la autoevaluación del modelo LLM y un cálculo estricto basado en reglas deterministas:

$$Score_{Final} = (Score_{Modelo} \times 0.50) + (Score_{Reglas} \times 0.50)$$

* **Peso Modelo ($0.50$):** `clasificacion.score_confianza_clasificacion`.
* **Peso Reglas ($0.50$):** Calculado a partir de la penalización acumulada sobre un valor base de $1.0$.

---

## 3. Criterio de Penalización Diferenciada

La penalización del score de reglas distingue la criticidad del dato faltante únicamente sobre la lista `campos_no_encontrados`. Los errores de validación e inconsistencias clínicas no se atenúan.

| Tipo de Inconsistencia / Omisión | Penalización | Descripción |
| :--- | :--- | :--- |
| **Campos Faltantes Secundarios** | `-0.05` | Datos de soporte como `sexo`, `fecha`, `tipo_documento`, `numero_documento`. |
| **Campos Faltantes Críticos** | `-0.10` | Datos esenciales como `paciente`, `profesional`, `diagnostico`, `medicamentos`. |
| **Errores de Validación (Sprint 1)** | `-0.10` | Fallos de formato Pydantic o estructuras corruptas. |
| **Inconsistencias Clínicas (MF-09)** | `-0.10` | Contradicciones lógicas entre el clasificador y la extracción. |

> **Nota de Diseño:** El score de reglas tiene un valor mínimo de $0.0$ (penalización máxima acotada a $1.0$).

---

## 4. Clasificación por Categorías y Degradación

Un umbral numérico define la categoría inicial. Sin embargo, la presencia de errores estructurales o inconsistencias clínicas aplica una **degradación de seguridad**:

* **Alta (≥ 0.80):** Requiere un score final de $0.80$ o superior y **cero** inconsistencias clínicas o errores de validación.
* **Media (0.50 - 0.79):** Asignada cuando el score está en el rango o cuando el score es $\ge 0.80$ pero existen inconsistencias clínicas detectadas.
* **Baja (< 0.50):** Asignada cuando el score es inferior a $0.50$.

---

## 5. Contrato de Entrada y Salida (LangGraph)

### Entrada (`MediFlowState`)
* `clasificacion`: Objeto Pydantic con `score_confianza_clasificacion`.
* `extraccion`: Objeto Pydantic con la propiedad `campos_no_encontrados`.
* `errores_validacion`: Lista de errores formales generados en validación.
* `inconsistencias`: Lista de anomalías detectadas en el nodo MF-09.

### Salida
```json
{
  "score_confianza_final": 0.85,
  "categoria_confianza": "Alta",
  "motivos_confianza": ["Sin inconsistencias detectadas"]
}