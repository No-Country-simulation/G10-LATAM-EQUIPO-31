# MF-16: Fortalecimiento del Dataset y Criterios de Inferencia Clínica

## 1. Propósito
El objetivo del fortalecimiento del dataset en la tarea MF-16 es expandir la capacidad de validación del pipeline de MediFlow mediante la incorporación de documentos realistas, anonimizados y de variada estructura morfológica (PDFs e imágenes). Su propósito es someter al MVP a condiciones operativas reales, evaluando su resiliencia ante formatos complejos, datos ambiguos que activen rutas HITL (Human-in-the-loop) y la capacidad de deducir prioridades críticas a partir del contexto semántico médico, mitigando la dependencia de etiquetas explícitas de triaje.

## 2. Segmentación y Distribución del Dataset
El dataset del proyecto se divide en dos grandes conjuntos operativos con objetivos diferenciados dentro del ciclo de integración continua (CI):

*   **Set de Regresión (Existente - 100% Sintético):** Compuesto por archivos originales en formato Markdown (`.md`). Su objetivo es garantizar que las optimizaciones del pipeline no corrompan las capacidades de extracción básicas ya validadas en el Sprint 1.
*   **Set de Robustez MVP (Nuevo - Realista/Anonimizado):** Compuesto por un inventario de archivos distribuidos en formatos **PDF** e **Imágenes (PNG/JPG)** que representan la casuística real de un entorno hospitalario.

## 3. Matriz de Escenarios de Prueba e Inferencia
La estrategia de validación clasifica los documentos en cuatro categorías funcionales basados en la estructura del dato y la complejidad del procesamiento:

| Tipo de Escenario | Formato de Ingesta | Criterio de Evaluación / Comportamiento Esperado | Objetivo Operativo |
| :--- | :--- | :--- | :--- |
| **Estándar** | PDF | Flujo feliz. Datos completos, legibles y estructurados de pacientes estables sin criticidad. | Validar ingesta base Ocr/Pdf. |
| **Urgente Explícito** | Imagen (PNG/JPG) | El documento contiene textualmente la cadena `"Prioridad: Urgente"` o `"Emergencia"`. | Evaluar extracción directa de texto sobre canales OCR. |
| **Urgencia Inferida** | Texto / Markdown | **Inferencia Clínica Activa:** El documento carece de etiquetas de prioridad, pero describe constantes vitales alteradas o sintomatología de riesgo. | Evaluar la capacidad analítica/médica del LLM. |
| **Ambiguo / Inconsistente** | PDF | Datos contradictorios o corruptos que fuerzan una caída en los scores de confianza. | Validar el disparo de alertas y desvíos hacia rutas HITL. |

## 4. Lógica de Diseño para el Caso de Urgencia Inferida
Para cumplir con el criterio de aceptación clínico, el caso **`caso-urgente-inferido.md` (ID: INF-01)** fue diseñado sin descriptores de prioridad explícitos. El pipeline deberá clasificar el documento con prioridad crítica disparando las reglas basadas en los siguientes umbrales semánticos:

*   **Sintomatología Aguda Isquémica:** Presencia de vectores semánticos equivalentes a *"dolor torácico opresivo 8/10 irradiado a miembro superior izquierdo"*, *"diaforesis"* y *"disnea de inicio súbito"*.
*   **Signos Vitales en Estado de Choque:** 
    *   *Presión Arterial*: Hipotensión severa (≤ 90/60 mmHg).
    *   *Frecuencia Cardíaca*: Taquicardia compensatoria (> 100 lpm).
    *   *Saturación de Oxígeno (SpO2)*: Hipoxemia severa (< 85% en aire ambiente).

## 5. Contrato de Estructura de Datos (Esquema de Ingesta assets/mf-16/)
Para asegurar que los archivos incorporados puedan ser consumidos por el componente de pruebas en la tarea **MF-17**, la carpeta del dataset se organiza bajo el siguiente contrato de localización:

```text
docs/assets/mf-16/
├── caso-ambiguo.pdf           # Caso de baja confianza (HITL)
├── caso-estandar.pdf          # Caso de flujo normal estable
├── caso-urgente-inferido.md   # Caso de lógica médica/signos críticos
└── caso-urgente.png           # Caso de extracción OCR explícita
```
