# Evidencias de validación — Sprint 4

> Evidencias de integración, pruebas funcionales y validación del MVP de MediFlow durante el Sprint 4, utilizando la rama `test/MF-31-integracion-validacion-sprint-4`, con los cambios integrados desde `develop`.

## Alcance

Durante el Sprint 4 se realizaron correcciones funcionales, mejoras en la interfaz, ampliación de formatos admitidos y pruebas de integración del MVP.

Las validaciones abarcaron:

- Clasificación y extracción de documentos clínicos.
- Procesamiento de documentos PDF, JPG y TXT.
- Enrutamiento estándar, urgente y revisión humana (HITL).
- Aprobación y rechazo de documentos mediante revisión humana.
- Persistencia de resultados e historial en OCI Object Storage.
- Generación de alertas para documentos urgentes.
- Ejecución de pruebas automatizadas y validación de regresión.

La documentación técnica de integración se encuentra en `docs/MF-31-integracion-validacion-sprint4.md`.

---

## Pruebas automatizadas — MF-31

Se ejecutó la suite completa del proyecto sobre la rama de integración.

**Resultado: 361 pruebas aprobadas en 39.18 segundos.**

![Suite automatizada — 361 pruebas](assets/sprint-4/MF-31/MF-31-01-suite-pruebas-automatizadas.png)

---

## Escenario estándar — Documento PDF

**Documento:** `06_receta_medica.pdf`  
**Formato:** PDF

Se procesó una receta médica mediante la interfaz de Streamlit.

**Resultados obtenidos:**

- Clasificación: Receta Médica.
- Confianza: Alta (0.93).
- Validación: correcta.
- Enrutamiento: estándar.

El documento se procesó correctamente sin requerir revisión humana.

![Escenario estándar PDF](assets/sprint-4/MF-31/MF-31-02-escenario-estandar-pdf.png)

---

## Escenario estándar — Imagen JPG

**Documento:** `08_orden_procedimiento.jpg`  
**Formato:** JPG

Se utilizó una orden de procedimiento en formato imagen para validar la capacidad de extracción y procesamiento multimodal del agente.

El documento siguió el flujo estándar, con confianza Alta y destino de auditoría/autorizaciones.

![Escenario estándar JPG](assets/sprint-4/MF-31/MF-31-03-escenario-estandar-jpg.png)

---

## Escenario urgente

**Documento:** `02_informe_estudio.txt`  
**ID:** `DOC-20261015-224303-AFBB`

El documento contiene un diagnóstico de tromboembolismo pulmonar agudo.

**Resultados obtenidos:**

- Clasificación: Informe de Estudio de Diagnóstico por Imágenes/Laboratorio.
- Confianza: Alta (0.93).
- Validación: correcta.
- Prioridad: urgente.
- Enrutamiento: cola de emergencia.

![Escenario urgente](assets/sprint-4/MF-31/MF-31-04-escenario-urgente.png)

### Alerta en Slack

Se realizó la verificación del mecanismo de notificación asociado al procesamiento urgente.

![Alerta en Slack](assets/sprint-4/MF-31/MF-31-05-alerta-slack.png)

---

## Escenario de revisión humana (HITL)

**Documento:** `09_receta_inconsistente_hitl.txt`

Se utilizó un documento previamente procesado y pendiente de revisión humana.

El caso permitió verificar su disponibilidad en la bandeja HITL y consultar los motivos que requieren intervención del auditor.

![Documento pendiente de revisión humana](assets/sprint-4/MF-31/MF-31-06-escenario-hitl.png)

### Decisiones de aprobación y rechazo

Desde el panel de revisión humana se verificó el registro de decisiones anteriores de aprobación y rechazo.

La tabla de casos resueltos permite consultar:

- Identificador del documento.
- Decisión registrada.
- Motivo del rechazo, cuando corresponde.
- Notas del auditor.
- Tipo documental.
- Usuario auditor y fecha.

![Historial de decisiones HITL](assets/sprint-4/MF-31/MF-31-07-historial-decisiones-hitl.png)

---

## Persistencia en OCI Object Storage

Se verificó el almacenamiento de los resultados procesados en OCI Object Storage, utilizando el documento urgente como caso de referencia.

![Persistencia en OCI](assets/sprint-4/MF-31/MF-31-08-persistencia-oci.png)

---

## Historial y trazabilidad

Se consultó la línea de tiempo del documento urgente.

**Evento registrado:**

- Procesamiento: 15/10/2026, 22:44 (America/Bogota).
- Estado: urgente.
- Confianza: Alta.

![Historial del documento](assets/sprint-4/MF-31/MF-31-09-historial-documento.png)

---

## Otras actividades del Sprint 4

| Actividad | Trabajo realizado | Documentación |
|---|---|---|
| MF-24 — Confianza y gravedad en receta urgente | Se investigaron los valores ausentes observados en la demo del Sprint 3. Se determinó que el comportamiento provenía de una prueba simulada con alertas activas y no de un defecto del flujo real. | `docs/MF-24-confianza-gravedad-receta-urgente.md` |
| MF-25 — Derivación estándar a HITL | Se identificó y corrigió una penalización incorrecta cuando una orden contenía `estudios_solicitados` en lugar de `procedimientos_solicitados`. También se documentó un caso de clasificación incorrecta fuera del alcance de la corrección. | `docs/MF-25-derivacion-estandar-hitl.md` |
| MF-26 — Pruebas adicionales | Se realizaron pruebas funcionales y se registraron hallazgos de clasificación, urgencia, revisión humana, alertas y conectividad. | `docs/MF-26-pruebas-validacion-hallazgos.md` |
| MF-28 — Interfaz de entrada | Se implementó la carga de documentos y consulta de resultados desde Streamlit, con acceso al panel HITL. | `docs/MF-28-interfaz-amigable-de-entrada.md` |
| MF-28 — Explicación de confianza | Se incorporó una explicación en Consulta de resultados para los casos con puntuación alta cuya categoría final es Media. | `docs/MF-28-explicacion-confianza.md` |
| MF-29 — Documentos definitivos | Se evaluaron documentos candidatos para los escenarios estándar, urgente y HITL, considerando su comportamiento y reproducibilidad. | Actividad MF-29 |
| MF-30 — Mejoras del panel HITL | Se eliminaron avisos duplicados y se mejoraron los mensajes cuando la API no está disponible, sin alterar las decisiones HITL. | `docs/MF-30-mejoras-panel-hitl.md` |
| MF-33 — Conexión local | Se cambió la URL predeterminada de `localhost` a `127.0.0.1` para mejorar el tiempo de respuesta cuando la API local no está disponible. | `docs/MF-33-api-url-ipv4.md` |
| MF-34 — Soporte TXT | Se habilitó la carga de archivos `.txt` desde Streamlit utilizando el flujo de procesamiento existente. | `docs/MF-72-soporte-txt.md` |

---

## Demostración del Sprint 4 — 15/10/2026

Durante la Sprint Demo se presentaron los tres flujos principales de MediFlow: estándar, urgente y revisión humana.

Se utilizaron documentos PDF, JPG y TXT para demostrar la capacidad multimodal del agente. También se mostró la admisión de imágenes PNG desde la interfaz.

| Escenario | Resultado |
|---|---|
| Estándar — PDF | Procesamiento correcto y enrutamiento a farmacia hospitalaria |
| Estándar — JPG | Procesamiento correcto de una orden médica en imagen |
| Urgente — TXT | Clasificación urgente y enrutamiento a la cola correspondiente |
| Revisión humana — TXT | Derivación a HITL y demostración del rechazo |
| Pruebas automatizadas posteriores | 361 pruebas aprobadas |

Se acordó reutilizar los documentos validados para la demostración final, conservando los tres escenarios principales y priorizando la capacidad multimodal de MediFlow.

---

## Resultado general

Las pruebas realizadas durante el Sprint 4 permitieron validar los principales recorridos funcionales del MVP integrado.

Se confirmó el procesamiento de documentos en distintos formatos, el enrutamiento según prioridad y confianza, la consulta de resultados, la revisión humana y el registro de trazabilidad.

La suite automatizada finalizó con **361 pruebas exitosas**.

Las investigaciones y correcciones de las actividades individuales se encuentran documentadas en sus respectivos informes técnicos.