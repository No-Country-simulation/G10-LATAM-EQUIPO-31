# MF-17 — Validación E2E y regresión final del MVP

## Objetivo

Validar de extremo a extremo el MVP integrado de MediFlow al cierre del Sprint 3, verificando que las funcionalidades implementadas en los sprints anteriores continúan operativas después de la integración de los cambios finales.

La validación incluye procesamiento estándar y urgente, revisión humana (HITL), persistencia e historial en OCI, trazabilidad, fallback técnico, cálculo de confianza, alertas externas y regresión automatizada.

---

## Escenarios validados

### 1. Flujo estándar y urgente

Se ejecutaron pruebas de regresión sobre las rutas estándar y urgente para comprobar que continúan funcionando después de las integraciones del Sprint 3.

También se validó el escenario de inferencia de urgencia a partir del contenido clínico.

**Resultado:** OK.

Evidencias:

- [Evidencia E2E — Flujo estándar y urgente](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-estandar-urgente.png)
- [Evidencia E2E — Inferencia de urgencia](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-urgente.png)

---

### 2. Flujo HITL — aprobación

Se procesó un documento que cumple una regla de inconsistencia clínica y fue derivado a `revision_humana`.

Desde el panel HITL se realizó la aprobación del caso y posteriormente se verificó su trazabilidad en el historial persistido.

**Resultado:** OK.

Evidencias:

- [Evidencia HITL — Caso pendiente](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-HITL-pendiente.png)
- [Evidencia HITL — Aprobación](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-HITL-aprobacion.png)
- [Evidencia HITL — Historial de aprobación](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-HITL-aprobacion-historial.png)
- [Evidencia HITL — Aprobación y persistencia](./assets/sprint-3/mf-17-validacion-e2e/evidencia-test-HITL-aprobacion-persistencia.png)
---

### 3. Flujo HITL — rechazo

Se procesó un segundo caso dirigido a `revision_humana`.

El caso fue rechazado desde el panel HITL indicando el motivo correspondiente y posteriormente se comprobó que la decisión quedó registrada en el historial.

**Resultado:** OK.

Evidencias:

- [Evidencia HITL — Rechazo](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-HITL-rechazo.png)
- [Evidencia HITL — Historial de rechazo](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-HITL-rechazo-historial.png)

---

### 4. Trazabilidad SHA-256

Durante las validaciones HITL se comprobó que las decisiones de aprobación y rechazo conservan la referencia y la huella SHA-256 asociadas al documento procesado, manteniendo la trazabilidad entre el procesamiento original y la decisión humana.

**Resultado:** OK.

Las evidencias del historial de aprobación y rechazo incluidas en las secciones anteriores respaldan esta validación.

---

### 5. Persistencia e historial OCI

Se verificó la persistencia de resultados procesados y del historial correspondiente en OCI Object Storage.

En la validación integrada final, el caso `MF14-E2E-MEDIFLOW-002` quedó almacenado como:

- Resultado: `procesados/revision_humana/MF14-E2E-MEDIFLOW-002.json`
- Historial: `historial/MF14-E2E-MEDIFLOW-002/`

**Resultado:** OK.

Evidencias:

- [Evidencia E2E — Resultado persistido en OCI](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-integracion-OCI-resultado.png)
- [Evidencia E2E — Historial persistido en OCI](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-integracion-OCI-historial.png)
- [Evidencia de regresión — Persistencia OCI](./assets/sprint-3/mf-17-validacion-e2e/evidencia-regresion-OCI-persistencia.png)

---

### 6. Regresión del cálculo de confianza

Se ejecutaron las pruebas específicas correspondientes al cálculo de confianza y criticidad por tipo documental.

Resultado de la ejecución:

`8 passed`

**Resultado:** OK.

Evidencia:

- [Evidencia de regresión — Cálculo de confianza MF-21](./assets/sprint-3/mf-17-validacion-e2e/evidencia-regresion-MF21-confianza.png)

---

### 7. Fallback técnico

Se ejecutaron las pruebas de regresión asociadas al fallback técnico y manejo de fallos de proveedores/modelos.

Resultado de la ejecución:

`33 passed`

**Resultado:** OK.

Evidencia:

- [Evidencia de regresión — Fallback técnico](./assets/sprint-3/mf-17-validacion-e2e/evidencia-regresion-fallback-tecnico.png)

---

### 8. Integración E2E de alertas externas

Se realizó una validación integrada utilizando el archivo de prueba:

`docs/assets/mf-16/caso-urgente-inferido.png`

El documento ingresó a MediFlow mediante `POST /documentos` con el identificador:

`MF14-E2E-MEDIFLOW-002`

MediFlow determinó:

- `estado`: `revision_humana`
- `nivel_urgencia`: `emergencia`
- señales de gravedad detectadas
- `persistencia_ok`: `true`
- `historial_ok`: `true`

El caso conservó su condición urgente aun siendo derivado a revisión humana.

Después de la persistencia, MediFlow generó el evento de alerta hacia n8n. El workflow procesó el evento y se verificó la recepción real de la alerta en:

- Slack — canal `#mediflow-alertas-urgentes`
- Correo electrónico

El mensaje generado indicó correctamente que se trataba de un caso urgente pendiente de revisión humana.

Flujo validado:

`Documento → API MediFlow → procesamiento → revisión humana + urgencia → persistencia OCI → n8n → Slack + Email`

**Resultado:** OK.

Evidencias:

- [Evidencia E2E — Alerta recibida en Slack](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-integracion-alerta-Slack.png)
- [Evidencia E2E — Alerta recibida por email](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-integracion-alerta-email.png)
- [Evidencia E2E — Resultado persistido en OCI](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-integracion-OCI-resultado.png)
- [Evidencia E2E — Historial persistido en OCI](./assets/sprint-3/mf-17-validacion-e2e/evidencia-E2E-integracion-OCI-historial.png)

---

## Dataset utilizado

Para las validaciones E2E se utilizaron los casos sintéticos disponibles en:

`docs/assets/mf-16/`

Durante MF-17 se ajustó `caso-ambiguo.pdf` para representar de forma determinista el escenario contemplado por la validación clínica actual: una `Receta Medica` que contiene estudios complejos.

Este ajuste permite provocar de manera reproducible una inconsistencia clínica y validar el flujo `revision_humana` sin utilizar datos reales de pacientes.

---

## Suite automatizada final

Después de integrar los cambios finales de `develop` en la rama de MF-17 se ejecutó la suite automatizada completa:

```text
collected 272 items
272 passed in 9.51s
```

No se registraron fallos.

**Resultado final: 272/272 pruebas satisfactorias.**

Evidencia:

- [Evidencia — Suite automatizada final 272/272](./assets/sprint-3/mf-17-validacion-e2e/evidencia-suite-final-272-tests.png)

---

## Resultado de la validación

La validación E2E y de regresión confirma que los flujos principales del MVP continúan funcionando después de la integración del Sprint 3.

Se verificaron:

- procesamiento estándar y urgente;
- inferencia de urgencia;
- HITL con aprobación y rechazo;
- trazabilidad SHA-256;
- persistencia e historial OCI;
- cálculo de confianza;
- fallback técnico;
- integración MediFlow → n8n;
- alertas reales mediante Slack y correo;
- regresión automatizada completa.

No quedaron regresiones bloqueantes abiertas durante el cierre de MF-17.

**Estado final: VALIDACIÓN SATISFACTORIA.**