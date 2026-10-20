# MF-23 – Enrutamiento por departamento destino

**Responsable:** Jennifer Silva
**Archivos principales:** `app/graph/routing.py`, `app/schemas/state.py`, `app/api/routes.py`

## 1. Objetivo

Indicar a qué área de la institución debe ir cada documento procesado, mediante un campo nuevo del estado: `departamento_destino`.

**Este campo complementa a `destino_principal`, no lo reemplaza.** `destino_principal` (`estandar` / `urgente` / `revision_humana`) sigue respondiendo "cómo se trata el documento" y determina la ruta de persistencia en OCI. `departamento_destino` responde "a qué área le corresponde".

## 2. Mapeo

| Condición | `departamento_destino` |
|---|---|
| Documento urgente (cualquier tipo) | `cola_urgencias_medicas` |
| Receta médica | `farmacia_hospitalaria` |
| Orden / solicitud de procedimiento | `auditoria_autorizaciones` |
| Epicrisis / Informe de alta | `historia_clinica_electronica` |
| Informe de estudio diagnóstico | `historia_clinica_electronica` |
| Certificado médico | `historia_clinica_electronica` |
| Tipo desconocido | Sin departamento inferido |
| `destino_principal = revision_humana` | Sin departamento (fuera de alcance) |

## 3. Precedencia

1. La **urgencia** tiene precedencia sobre el tipo documental: un documento urgente va a `cola_urgencias_medicas` aunque sea, por ejemplo, una receta.
2. Si no es urgente, manda el **tipo documental** según la tabla.
3. Un tipo desconocido no recibe departamento inferido: no se adivina un destino sin base.

La urgencia se reconcilia con criterio conservador (`or`, no `and`) entre `clasificacion.nivel_prioridad` y `extraccion.nivel_urgencia` (MF-11): si cualquiera de los dos indica urgencia, el documento se considera urgente.

## 4. Decisión de diseño: campo aditivo

Se evaluaron dos opciones:

| Opción | Descripción | Resultado |
|---|---|---|
| A | Ampliar los valores de `destino_principal` con los departamentos | Descartada: rompía 4 pruebas ya aprobadas y contratos integrados por el equipo |
| **B** | **Campo nuevo `departamento_destino`, aditivo** | **Elegida: no modifica ningún contrato existente** |

Se priorizó la opción de menor riesgo para lo ya probado e integrado. Los 3 valores de `destino_principal` quedan sin cambios.

## 5. Dónde se expone el campo

`MediFlowState` es un `TypedDict(total=False)`, por lo que el campo se lee siempre con `.get()` (no hay valores por defecto en tiempo de ejecución).

En `app/api/routes.py`, `departamento_destino` aparece en:

| Lugar | Propósito |
|---|---|
| `resumen` del evento de historial | Lo pide la especificación de Kimberly |
| Respuesta HTTP (`cuerpo_resultado`) | Que el consumidor de la API lo reciba directamente |
| `envelope` persistido en OCI (nivel superior) | Filtrar resultados sin desanidar, igual que `urgente` y `nivel_urgencia` |

La especificación solo exige el campo en `resumen`. Su presencia en los otros dos lugares es una ampliación que debe confirmar Duvan, dueño de `routes.py`. Si no se acepta, se retira de ambos sin afectar el resto.

El campo no interviene en la elección del prefijo de persistencia: eso depende solo de `destino_principal` (y de los fallos técnicos).

## 6. Evidencia de pruebas

- `tests/test_mf23_enrutamiento_departamento.py`: mapeo y precedencia.
- `tests/test_routes.py`: se actualizó una aserción que esperaba `None` y ahora espera `farmacia_hospitalaria` para una receta no urgente con confianza Alta; también se verifica que el valor llegue a la respuesta HTTP y al resultado persistido.
- `tests/test_integracion_sprint2.py`: prueba de integración de MF-09, MF-10 y MF-11; se ajustó el caso 7 por el efecto de MF-21 (ver `docs/MF-21-confianza-por-tipo-documental.md`).
- Suite completa del proyecto: **190 passed**.

Nota: los tests parametrizados de `routes` que usan un grafo simulado emplean valores de ejemplo (`"Farmacia"`, `"Urgencias"`) que MF-23 nunca produce. Solo verifican que la ruta copia lo que recibe del estado.

## 7. Fuera de alcance

- **Departamento para `revision_humana`.** Hoy esos documentos no llevan departamento, lo que puede dejar un vacío en los logs. Se propone a Kimberly, como mejora de seguimiento, que también lleven un departamento o una señal equivalente.
- **Conexión de `routing_condicional` con `add_conditional_edges`** en `graph.py`. No es necesaria para que `departamento_destino` funcione.