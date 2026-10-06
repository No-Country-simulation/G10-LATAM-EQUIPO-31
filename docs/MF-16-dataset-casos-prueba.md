# MF-16: Fortalecimiento del Dataset y Casos de Prueba

## 1. Estructura y Organización del Dataset
Los archivos de prueba utilizados para la validación del MVP se organizan dentro de la carpeta de recursos de documentación en la siguiente ruta:

*   **`docs/assets/MF-16/`**: Carpeta creada específicamente para esta tarea, destinada a almacenar los nuevos documentos de prueba en formatos **PDF** e **imágenes** (PNG/JPG). Actualmente contiene un archivo `.gitkeep` para preservar la estructura en Git mientras se generan los archivos finales.
*   *Nota: Los documentos sintéticos originales en formato `.md` se mantienen intactos en la raíz de `docs/` para garantizar las pruebas de regresión.*

## 2. Inventario de Casos de Prueba Planificados

| ID Caso | Escenario | Formato Destino | Tipo de Dato | Descripción / Objetivo |
| :--- | :--- | :--- | :--- | :--- |
| **REG-01** | Regresión (Existentes) | `.md` | Sintético | Asegurar compatibilidad con el flujo previo de las tareas anteriores. |
| **STD-01** | Estándar | `PDF` | Realista / Anonimizado | Flujo de ingreso normal de un paciente sin prioridades críticas. |
| **URG-01** | Urgente Explícito | `Imagen (PNG/JPG)`| Anonimizado | Documento médico que incluye una etiqueta textual directa de "Prioridad: Urgente". |
| **INF-01** | Urgencia Inferida | `PDF` | Realista | **Inferencia Clínica:** Paciente con signos vitales en estado crítico (ej. Saturación < 85%) sin etiqueta explícita de prioridad. |
| **AMB-01** | Ambiguo / HITL | `PDF` | Sintético | Datos clínicos contradictorios para evaluar umbrales de baja confianza o activación de revisión humana. |

## 3. Casos de Inferencia de Urgencia Clínica
Para el caso **INF-01**, el dataset evaluará la capacidad del modelo para extraer e inferir la prioridad de atención analizando variables médicas directas del texto (diagnósticos presuntivos graves, sintomatología aguda, funciones vitales alteradas) evitando depender de parámetros explícitos de clasificación preexistentes en el documento.

## 4. Pruebas y Validaciones de Ingesta
*   Verificación de que los nuevos formatos (PDF/Imágenes) no generen excepciones en el pipeline actual.
*   Confirmación de que no se filtren datos clínicos personales identificables (PII) en los ejemplos seleccionados.
