# MF-26 — Registro de pruebas, validaciones y hallazgos

**Actividad:** MF-26 — Pruebas y validación del flujo  
**Estado:** En progreso  
**Participantes:** Equipo MediFlow. Pruebas y hallazgos registrados por Kimberlyn y Jennifer.

## 1. Objetivo

Documentar los resultados de las pruebas funcionales realizadas sobre MediFlow, identificando comportamientos esperados, inconsistencias, problemas técnicos y posibles causas.

Este registro consolida los hallazgos obtenidos durante las pruebas del equipo y los análisis relacionados con MF-24 y MF-25.

La actividad permanece abierta, ya que todavía existen escenarios pendientes de validación e investigación.

## 2. Alcance de las pruebas

Las validaciones realizadas hasta el momento incluyen:

- Procesamiento y clasificación de documentos clínicos.
- Extracción de información.
- Evaluación de confianza y enrutamiento.
- Persistencia y consulta de resultados en OCI.
- Revisión humana (HITL), aprobación y rechazo.
- Alertas de emergencia mediante n8n, Slack y correo.


Las pruebas aquí registradas corresponden al entorno local, utilizando el backend FastAPI, la interfaz Streamlit y los servicios configurados para MediFlow.

## 3. Matriz de pruebas funcionales

Se consolidan los resultados obtenidos durante las validaciones realizadas por Kimberlyn y Jennifer. Los casos coincidentes se registran una sola vez, relacionándolos con las investigaciones correspondientes.

| Documento / escenario | Resultado esperado | Resultado obtenido | Evaluación |
|---|---|---|---|
| `caso-estandar.pdf` | Procesamiento como caso estándar | Clasificado como orden médica, confianza 0.93 Media y derivación a revisión humana. | Requiere análisis de clasificación — MF-25 |
| `caso-urgente.png` | Detección de urgencia | Clasificado como no urgente, con confianza 0.97 Alta y procesamiento automático. | No cumple el escenario esperado |
| `p10.jpg` | Identificación de contradicciones clínicas | No se identificó la contradicción entre el contexto pediátrico y la referencia a Alzheimer. | No cumple el escenario esperado |
| `caso-urgente-inferido.jpg` | Detección de emergencia y envío de alertas | Emergencia detectada y alertas recibidas. | Satisfactorio |
| Reporte clínico urgente 2D | Detección de emergencia y enrutamiento seguro | Emergencia detectada, confianza 0.68 Media, revisión humana y alertas recibidas. | Satisfactorio con observaciones |
| `DOC-20261013-203307-62D7` | Aprobación de un documento desde HITL | Aprobación persistida y visible en Consulta de resultados. | Satisfactorio |
| `DOC-20261013-110546-49B0` | Rechazo de un documento desde HITL | Rechazo persistido y visible en Consulta de resultados. | Satisfactorio |
| `DOC-TEST-MF11-X` | Prueba automatizada aislada de notificaciones reales | El test generó una alerta real en Slack con confianza y señales vacías. | Reproducido — MF-24 |

### Observaciones

Los resultados de `caso-estandar.pdf`, `caso-urgente.png` y `p10.jpg` coinciden con comportamientos investigados o reportados por Jennifer.

La investigación de MF-25 permitió explicar la derivación de `caso-estandar.pdf` a revisión humana, mientras que los otros dos documentos requieren actividades específicas de seguimiento.

La reproducción de `DOC-TEST-MF11-X` permitió respaldar la hipótesis planteada durante MF-24.

Las pruebas de aprobación, rechazo y alertas en escenarios urgentes permitieron verificar funcionalidades importantes del flujo de MediFlow.


## 4. Hallazgos identificados durante las pruebas

### H01 — Documento estándar derivado a revisión humana

**Documento:** `caso-estandar.pdf`  
**Actividad relacionada:** MF-25  
**Estado:** Causa identificada; pendiente de determinar si requiere ajuste.

Durante las pruebas de integración se observó que un documento utilizado como caso estándar fue derivado a revisión humana, con confianza numérica de 0.93 y categoría Media.

En paralelo, durante la investigación de MF-25, Jennifer identificó que el clasificador interpretaba el documento como una orden médica sin procedimientos solicitados. La ausencia de este campo provocaba una penalización en la evaluación de confianza y su posterior derivación a revisión humana.

El enrutamiento es coherente con las reglas actuales del sistema. Sin embargo, queda pendiente determinar si la clasificación documental inicial es adecuada para el contenido del archivo.

### H02 — Falso negativo en la detección de urgencia

**Documento:** `caso-urgente.png`  
**Estado:** Pendiente de investigación.

Durante las pruebas se observó que el documento fue clasificado como no urgente, a pesar de utilizarse como un escenario de urgencia.

Este comportamiento también fue identificado por Jennifer durante sus validaciones.

Se propone registrar una actividad específica a partir de MF-32 para investigar la causa y determinar si se requiere ajustar la clasificación de urgencia.

**Seguimiento:** Pendiente de confirmar la creación y asignación del bug.

### H03 — Contradicción clínica no detectada

**Documento:** `p10.jpg`  
**Estado:** Pendiente de investigación.

Jennifer identificó durante sus pruebas un documento con información clínica contradictoria que no fue señalada por el sistema.

El caso corresponde a una contradicción entre los datos pediátricos y una referencia clínica a Alzheimer.

Se propone registrar una actividad específica a partir de MF-32 para analizar el comportamiento y evaluar los ajustes necesarios.

**Seguimiento:** Pendiente de confirmar la creación y asignación del bug.

### H04 — Alertas incompletas generadas durante pruebas automatizadas

**Documento de prueba:** `DOC-TEST-MF11-X`  
**Actividad relacionada:** MF-24  
**Estado:** Comportamiento reproducido; protección pendiente.

Durante la investigación de MF-24, Jennifer identificó que una alerta incompleta observada durante la demostración del Sprint 3 podía haberse originado en una prueba automatizada que utilizaba un grafo simulado.

Para verificar esta hipótesis, se ejecutó localmente el test asociado a `DOC-TEST-MF11-X`, manteniendo activo el webhook de n8n.

La ejecución generó una alerta real en Slack con los campos «Confianza» y «Señales de gravedad» vacíos, reproduciendo el comportamiento observado.

La prueba confirma que este escenario puede generar alertas incompletas, aunque no permite asegurar que haya sido el origen exacto de la alerta histórica.

**Seguimiento propuesto:** Incorporar una fixture en `tests/conftest.py` que impida el envío de alertas reales durante las ejecuciones de pytest.

### H05 — Validación de documentos urgentes con revisión humana

**Documento de prueba:** `DOC-20261013-210219-567B`  
**Estado:** Validación satisfactoria con observaciones.

Se procesó un reporte clínico urgente en formato de imagen 2D.

El sistema identificó el nivel de emergencia, asignó confianza Media (0.68) y derivó el documento a revisión humana debido a información crítica faltante.

Las alertas se generaron correctamente, aun cuando el documento quedó pendiente de revisión humana.

Esto permitió validar que la derivación a HITL no impide la emisión de alertas correspondientes a casos urgentes.

### H06 — Persistencia de decisiones de revisión humana

**Documentos de prueba:**
- `DOC-20261013-203307-62D7`: aprobación.
- `DOC-20261013-110546-49B0`: rechazo.

**Estado:** Validado.

Se realizaron pruebas de aprobación y rechazo desde el panel de revisión humana.

En ambos escenarios se verificó que las decisiones quedaran registradas y fueran recuperables desde Consulta de resultados.

### H07 — Optimización del tiempo de conexión local de Streamlit

**Actividad relacionada:** MF-33 (GitHub Issue #69)  
**Responsable:** Mauricio Niño  
**Estado:** Mejora implementada y probada localmente; pendiente de integración.

Durante las validaciones del frontend se identificó una oportunidad de mejora en el tiempo de respuesta del panel cuando la API local no se encuentra disponible.

Mauricio implementó un ajuste para utilizar `127.0.0.1` como dirección predeterminada de conexión.

**Resultados reportados:**

- Tiempo de espera anterior: aproximadamente 30 segundos.
- Tiempo de espera posterior: aproximadamente 20 segundos.
- Comportamiento de reintentos: sin modificaciones.
- Pruebas automatizadas: 342 satisfactorias.

La mejora representa una reducción aproximada de 10 segundos en el escenario evaluado.

**Seguimiento:** Se creó MF-33 para documentar e integrar el ajuste mediante un pull request.

## 5. Seguimiento de hallazgos

| Hallazgo | Referencia | Acción pendiente |
|---|---|---|
| Clasificación de `caso-estandar.pdf` | MF-25 | Determinar si requiere ajuste del clasificador. |
| Falso negativo de `caso-urgente.png` | Nueva actividad propuesta desde MF-32 | Investigar clasificación de urgencia. |
| Contradicción no detectada en `p10.jpg` | Nueva actividad propuesta desde MF-32 | Investigar validación de inconsistencias clínicas. |
| Alertas reales durante pytest | MF-24 | Implementar protección en `conftest.py`. |
| Urgencia + HITL + alertas | MF-26 | Escenario validado; conservar evidencia. |
| Aprobación y rechazo HITL | MF-26 | Escenarios validados; conservar evidencia. |

## 6. Estado de la actividad

MF-26 continúa en progreso.

Se han identificado comportamientos funcionales satisfactorios y hallazgos que requieren seguimiento.

Los resultados coincidentes entre las pruebas de integración y las investigaciones realizadas por Jennifer se consolidan en este registro para mantener la trazabilidad y evitar duplicar incidencias.

Las nuevas actividades propuestas se actualizarán con sus identificadores una vez que se confirme su creación.

## 7. Evidencias de las pruebas

Las evidencias se incorporarán progresivamente conforme se organicen las capturas y registros de las validaciones realizadas.

| Caso evaluado | Evidencia a incorporar | Referencia |
|---|---|---|
| `caso-estandar.pdf` | Captura de clasificación, confianza y derivación a HITL. | ![Resultado de caso-estandar.pdf](assets/sprint-4/MF-26/caso-estandar-resultado.png)|
| `caso-urgente.png` | Captura del resultado de clasificación como no urgente. | ![Clasificación inesperada de caso-urgente.png](assets/sprint-4/MF-26/caso-urgente-clasificacion.png) |
| `p10.jpg` | Documento original y resultado donde no se identifica la contradicción clínica. | **[Pendiente: evidencia de p10.jpg — hallazgo reportado por Jennifer]** |
| `caso-urgente-inferido.jpg` | Captura de detección de emergencia y alerta recibida. | **Documento utilizado:** [caso-urgente-inferido.jpg](assets/sprint-4/sprint-4/MF-26/caso-urgente-inferido.jpg) ![Alerta de emergencia](assets/sprint-4/MF-26/caso-urgente-inferido-alerta.png) |
| Reporte clínico urgente 2D | Resultado en Consulta y alerta de Slack. | **Documento utilizado:** [reporte-urgente-2d.png](assets/sprint-4/MF-26/reporte-urgente-inferido-2d.png) ![Alerta del reporte urgente 2D](assets/sprint-4/MF-26/reporte-urgente-2d-alerta.png) |
| Aprobación y rechazo HITL | Capturas de las decisiones registradas y consultadas. | **Aprobación HITL:** ![Aprobación registrada](assets/sprint-4/MF-26/hitl-aprobacion.png) **Rechazo HITL:** ![Rechazo registrado](assets/sprint-4//MF-26/hitl-rechazo.png) |
| `DOC-TEST-MF11-X` | Captura de Slack con confianza y señales de gravedad vacías. | **Actividad relacionada:** MF-24 ![Alerta generada durante pytest](assets/sprint-4//MF-26/mf24-alerta-pytest-slack.png)|
| Optimización de conexión local de Streamlit (MF-33) | Mediciones antes y después del ajuste de `127.0.0.1`, con 342 pruebas satisfactorias reportadas por Mauricio. | **[Pendiente: evidencias de Mauricio en MF-33 / Issue #69]** |

**Nota:** Los espacios señalados se completarán con las capturas, rutas de archivos o enlaces correspondientes. Los hallazgos relacionados con nuevas actividades se actualizarán cuando se confirmen sus identificadores.