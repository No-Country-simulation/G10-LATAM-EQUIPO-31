# MF-20 — Integración y validación Sprint 2

## Objetivo

Integrar los componentes desarrollados durante el Sprint 2 dentro del
workflow principal de MediFlow y validar el funcionamiento del flujo
completo de extremo a extremo.

## Componentes integrados

Durante MF-20 se integraron los siguientes componentes:

- MF-09 — Validación de consistencia clínica.
- MF-10 — Evaluación de confianza.
- MF-11 — Evaluación de urgencia y routing.
- MF-13 — Persistencia de resultados procesados en OCI.
- MF-15 — Trazabilidad e historial de procesamiento.
- MF-19 — Fallback técnico de LLM.

El flujo integrado queda:

Documento
→ Clasificación
→ Extracción
→ Validación de consistencia
→ Evaluación de confianza
→ Routing
→ Persistencia
→ Historial

Los posibles destinos del routing son:

- `estandar`
- `urgente`
- `revision_humana`

## Ajustes realizados durante la integración

Durante las pruebas de integración se identificaron y corrigieron
incompatibilidades entre componentes desarrollados de forma independiente.

### Integración MF-09 con LangGraph

Se incorporó un adaptador entre `MediFlowState` y
`RespuestaProcesamiento` para ejecutar la validación de consistencia
manteniendo el contrato del estado del grafo.

También se ajustó la validación del paciente para soportar escenarios
de prueba donde algunos atributos pueden no estar presentes.

### Integración MF-10

Durante las pruebas se detectó que los campos faltantes tenían inicialmente
la misma penalización, provocando que omisiones administrativas menores
pudieran reducir innecesariamente la confianza.

Se integró el criterio diferenciado definido en MF-10:

- Campo secundario faltante: penalización de `0.05`.
- Campo crítico faltante: penalización de `0.10`.
- Error de validación: penalización de `0.10`.
- Inconsistencia detectada por MF-09: penalización de `0.10`.

Esto permite mantener el envío automático cuando las omisiones no son
críticas y utilizar revisión humana cuando existen señales relevantes.

### Integración MF-11

Se validó la precedencia del routing:

- Confianza Alta + no urgente → `estandar`.
- Confianza Alta + urgente → `urgente`.
- Confianza Media/Baja → `revision_humana`.

La revisión humana tiene precedencia cuando existen problemas de confianza
o consistencia, incluso si el documento contiene señales de urgencia.

### Integración MF-19

Durante la validación E2E del fallback se identificaron ajustes necesarios
para el proveedor secundario Groq:

- Tratamiento correcto de archivos TXT como texto y no como imagen.
- Ajuste de `max_tokens` para respetar los límites del proveedor.
- Alineación del prompt de clasificación con los valores exactos del enum
  `DocumentType`.

Luego de los ajustes se validó correctamente el procesamiento mediante
fallback técnico.

## Pruebas automatizadas

Se ejecutó la suite completa del proyecto después de integrar los
componentes del Sprint 2.

Resultado final:

`175 passed`

También se incorporaron pruebas específicas para validar las penalizaciones
diferenciadas de MF-10 y la interacción MF-09 → MF-10 → MF-11.

## Validación funcional E2E

### Escenario estándar

**Documento:** `01_receta_medica.txt`  
**ID de prueba:** `TEST-MF20-FINAL-ESTANDAR`  
**Resultado esperado:** `estandar`  
**Resultado obtenido:** `estandar`  
**Persistencia OCI:** OK  
**Historial:** OK  
**Validación:** OK

El documento fue clasificado como receta médica y procesado correctamente.
Los campos administrativos faltantes fueron tratados como campos secundarios
y no provocaron una revisión humana innecesaria.

### Escenario urgente

**Documento:** `02_informe_estudio.txt`  
**ID de prueba:** `TEST-MF20-FINAL-URGENTE`  
**Resultado esperado:** `urgente`  
**Resultado obtenido:** `urgente`  
**Persistencia OCI:** OK  
**Historial:** OK  
**Validación:** OK

El documento contiene un diagnóstico de tromboembolismo pulmonar agudo y
prioridad urgente. El flujo conservó correctamente la señal de urgencia y
el documento fue enviado al destino `urgente`.

### Escenario revisión humana (HITL)

**Documento:** `09_receta_inconsistente_hitl.txt`  
**ID de prueba:** `TEST-MF20-FINAL-HITL`  
**Resultado esperado:** `revision_humana`  
**Resultado obtenido:** `revision_humana`  
**Persistencia OCI:** OK  
**Historial:** OK  
**Validación:** OK

Para esta prueba se utilizó un documento controlado específicamente creado
para validar HITL.

El documento se presenta como una receta médica, pero contiene además un
estudio solicitado. Esta combinación activa una regla de consistencia de
MF-09.

La inconsistencia afecta la evaluación de confianza de MF-10 y MF-11
direcciona finalmente el documento a `revision_humana`.

El archivo `09_receta_inconsistente_hitl.txt` fue creado específicamente
como caso controlado para provocar una inconsistencia y validar el routing
hacia revisión humana.

## Persistencia y trazabilidad

La persistencia y trazabilidad se verificaron directamente en OCI Object Storage
después de ejecutar los tres escenarios E2E.

Se confirmó la existencia de los resultados procesados en:

- `procesados/estandar/TEST-MF20-FINAL-ESTANDAR.json`
- `procesados/urgente/TEST-MF20-FINAL-URGENTE.json`
- `procesados/revision_humana/TEST-MF20-FINAL-HITL.json`

También se verificó la creación del historial correspondiente para:

- `TEST-MF20-FINAL-ESTANDAR/`
- `TEST-MF20-FINAL-URGENTE/`
- `TEST-MF20-FINAL-HITL/`

De esta forma se validó que el resultado se almacena según el destino
determinado por el routing y que cada procesamiento genera su registro
de trazabilidad.

## Resultado final

La integración del Sprint 2 permite ejecutar el flujo:

Documento
→ Clasificación
→ Extracción
→ Consistencia
→ Confianza
→ Routing
→ Persistencia
→ Historial

Se validaron funcionalmente los tres destinos definidos por el workflow:
`estandar`, `urgente` y `revision_humana`.

La suite automatizada finaliza con 175 pruebas exitosas y los escenarios
E2E verificaron persistencia e historial en OCI.

## Evidencias

Las evidencias de la validación final del Sprint 2 se encuentran en:

`docs/assets/sprint-2/`

Incluyen:

- respuestas JSON de los escenarios `estandar`, `urgente` y `revision_humana`;
- evidencia de persistencia de los tres resultados en OCI Object Storage;
- evidencia de creación del historial de procesamiento;
- resultado de la ejecución de la suite automatizada.