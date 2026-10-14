# MF-24 – Investigar confianza y gravedad en receta urgente (Issue #60)

**Rama:** `feature/MF-24-confianza-gravedad-receta-urgente`
**Estado:** investigación concluida; causa identificada y confirmada por Kimberlyn (sección 7.3).

## 1. Resumen

El hallazgo de la demo del Sprint 3 (alerta de Slack con `Confianza: —` y `Señales de gravedad: —` en una receta médica) **no proviene del procesamiento de un documento real**. El mensaje que se tomó como evidencia lo generó una **prueba automática** (`tests/test_routes.py`, `documento_id = DOC-TEST-MF11-X`), que usa un grafo simulado sin confianza ni señales y, al ejecutarse con el webhook de n8n configurado en el entorno, envió una alerta real a Slack.

El flujo real, con el código de `develop`, produce confianza y señales de gravedad correctamente y las entrega completas a n8n, Slack y correo (sección 3). No se encontró un defecto en el código de producto. Sí se encontró un problema de higiene de pruebas: las pruebas podían enviar alertas reales; se corrigió con una fixture en `tests/conftest.py` (sección 8).

## 2. Qué se observó en la demo

Mensaje en el canal de Slack, registrado `2026-10-09T00:39:06 UTC` (08/10/2026, 20:39 hora local UTC-4):

| Campo | Valor |
|---|---|
| Título | ALERTA URGENTE: urgente, pendiente de revisión humana |
| Documento | `DOC-TEST-MF11-X` |
| Destino | `revision_humana` |
| Tipo de documento | Receta Medica |
| Especialidad | Medicina General |
| Nivel de urgencia | `no_urgente` |
| Confianza | — |
| Señales de gravedad | — |

## 3. Reproducción y verificación (tareas 1 a 4)

### 3.1 Receta urgente con el flujo real

Se ejecutó el grafo real (`grafo_mediflow`) con una receta urgente sintética (`07_urgente_receta_mf24.txt`), con la misma preparación de entrada que `routes.py` (texto como `"JSON"`, con bytes y texto):

| Salto | Resultado |
|---|---|
| Clasificador | Receta médica, prioridad `Emergencia` |
| Extractor | `nivel_urgencia: emergencia`, 3 señales de gravedad textuales |
| Confianza | `Alta`, score 1.0, presente en el estado |
| Routing | `urgente`, `cola_urgencias_medicas` |
| Evento a n8n | Incluye `categoria_confianza` y las 3 señales |
| Alerta (Slack y correo) | `Confianza: Alta` y las señales completas |

### 3.2 Documentos del repositorio

Se procesaron con el flujo real los 9 documentos de `samples/entradas` y 31 de `docs/assets/mf-16`. En ninguno apareció confianza ausente en el estado ni fallo técnico. Las señales aparecen vacías (`—`) únicamente en documentos no urgentes, como está diseñado (el extractor solo las llena cuando detecta urgencia). Las alertas reales de los casos urgentes llegaron completas a Slack y a AgentMail.

### 3.3 Transporte de los valores

- `routes.py` serializa el estado completo del grafo sin filtrar claves y arma el evento con `construir_evento_alerta`, que lee `categoria_confianza`, `score_confianza_final` y `senales_gravedad` con los mismos nombres que escriben los nodos.
- El módulo de alertas y el workflow tienen un único commit (`07d29e8`, 07/10/2026), anterior a la demo: el código que corrió en la demo es el mismo que se verificó.
- Todas las claves de confianza y routing están declaradas en `MediFlowState` (declaradas desde el 30/09/2026, commit `b500db7`), por lo que LangGraph no las descarta.
- El nodo de código del workflow muestra guión (`—`) solo cuando el campo llega ausente, vacío o, en las señales, con un tipo distinto de lista. Con eventos completos muestra los valores (verificado ejecutando el código del nodo con eventos de prueba).

### 3.4 Presentación

Slack y correo muestran los valores correctamente cuando el evento los trae. Los guiones se vieron únicamente en la alerta de Slack (confirmado por Kimberlyn), por lo que el panel de revisión humana (Streamlit) no interviene en este hallazgo y no se revisó.

### 3.5 Reproducción local de la causa

Con un receptor local que imita el webhook de n8n (escucha solo en 127.0.0.1) y `N8N_ALERT_WEBHOOK_URL` apuntando a él, se ejecutó `pytest tests/test_routes.py` (52 pruebas aprobadas). El receptor recibió **3 alertas**, sin pasar por Slack ni por n8n:

| `documento_id` | `estado` | Tipo | Nivel de urgencia | Confianza | Señales |
|---|---|---|---|---|---|
| `DOC-TEST-MF11` | `urgente` | Receta Medica | `no_urgente` | `None` | 0 |
| `DOC-TEST-MF11-URG` | `revision_humana` | Receta Medica | `no_urgente` | `None` | 0 |
| `DOC-TEST-MF11-X` | `revision_humana` | Receta Medica | `no_urgente` | `None` | 0 |

La tercera coincide campo por campo con el mensaje de Slack de la demo. La primera, con estado `urgente`, produce una alerta de "caso urgente en cola de emergencia" con los mismos guiones: es probable que esa sea la que se vio como flujo urgente en la demo, y puede comprobarse buscando los tres identificadores en el historial del canal alrededor de las 20:39 (UTC-4) del 08/10/2026.

## 4. Campos de confianza y gravedad (tarea 2)

La confianza (`categoria_confianza`, `score_confianza_final`, `motivos_confianza`) la escribe el nodo `evaluacion_confianza` en todos los recorridos. Las señales de gravedad las produce el extractor (campo `senales_gravedad` de `ExtraccionClinica`) y quedan vacías cuando el nivel de urgencia no es alto. Ante un fallo técnico del clasificador, la confianza queda `Baja` (0.4) y las señales `[]`; tampoco produce un guion de confianza.

## 5. Causa (tarea 5)

### 5.1 Evidencia

1. `DOC-TEST-MF11-X` es un identificador de prueba: aparece en `tests/test_routes.py`, en `test_post_documentos_destino_principal_desconocido_va_a_revision_humana`.
2. Ese test sustituye el grafo por `GrafoFalso({"destino_principal": "Urgente", "urgente": True})`. El estado simulado contiene únicamente `CLASIFICACION_PRUEBA`, `EXTRACCION_PRUEBA`, `validacion_ok` y esos dos campos, y **no incluye `categoria_confianza` ni señales de gravedad**.
3. Cada campo del mensaje de Slack coincide con ese estado simulado:

| Campo del mensaje | Origen en la prueba |
|---|---|
| Documento `DOC-TEST-MF11-X` | `documento_id` del test |
| Receta Medica / Medicina General | `CLASIFICACION_PRUEBA` |
| Nivel de urgencia `no_urgente` | `EXTRACCION_PRUEBA` (`NivelUrgencia.NO_URGENTE`) |
| Confianza `—` | El grafo simulado no devuelve `categoria_confianza` |
| Señales `—` | `EXTRACCION_PRUEBA` no define señales de gravedad |
| Destino `revision_humana` | `"Urgente"` (con mayúscula) está fuera del contrato y `routes.py` lo deriva a `revision_humana` |
| "Urgente" en la alerta | `urgente: True` forzado por el grafo simulado |

4. El cliente de prueba (`_crear_client`) solo sustituye el servicio de OCI; no neutraliza el envío de alertas. Si en el entorno de quien ejecuta `pytest` está definida `N8N_ALERT_WEBHOOK_URL`, la tarea en segundo plano de la alerta envía un POST real a n8n.

Esto también explica la incongruencia observada en el mensaje (alerta urgente con `Nivel de urgencia: no_urgente`): no hubo extracción real, y el estado simulado fuerza `urgente: True`.

### 5.2 Hipótesis descartadas

- Alucinación u omisión del modelo: en ese mensaje no intervino ningún modelo.
- Pérdida de campos por `MediFlowState`: las claves están declaradas desde el 30/09 y la traza las muestra en el estado final.
- Versión distinta del evento o del workflow en la demo: un solo commit, anterior a la demo.
- Falla técnica del clasificador: produce confianza `Baja`, no ausente.

## 6. Qué se probó (evidencias)

- Traza nodo por nodo del grafo real sobre la receta urgente (sección 3.1).
- Lote de 40 documentos (9 de `samples/entradas` y 31 de `docs/assets/mf-16`), con tabla comparativa y banderas heurísticas; resultados guardados fuera del repositorio.
- Alertas reales a Slack y AgentMail desde el flujo real, con confianza y señales completas.
- Reproducción local de la causa: `pytest tests/test_routes.py` con el webhook apuntando a un receptor local genera 3 alertas con confianza `None` y 0 señales (sección 3.5).
- Validación de la corrección: con la fixture, el receptor recibe 0 alertas y la suite completa pasa sin fallos (sección 8.1).
- Ejecución del código del nodo "Validar y armar mensaje" con cuatro variantes de evento (completo, sin campos, señales como texto, campos vacíos).

## 7. Estado de los criterios de aceptación

| Criterio | Estado |
|---|---|
| El escenario fue reproducido y analizado | Cumplido: la receta urgente real funciona, y el mensaje de la demo se reprodujo con `pytest` y un receptor local (sección 3.5) |
| Se identificó y documentó la causa | Cumplido (sección 5) y confirmado por Kimberlyn (sección 7.3) |
| Confianza y gravedad se generan y presentan según la lógica del sistema, o se justifica su ausencia | Cumplido: su ausencia en el mensaje se justifica por el grafo simulado |
| Si hubo un defecto, se corrigió y validó | No hay defecto en código de producto. Se corrigió el aislamiento de las pruebas y se validó (sección 8) |
| Pruebas y evidencias registradas | Cumplido (sección 6) |

### 7.3 Confirmación

Kimberlyn confirmó que ejecutó `pytest` el 08/10/2026 alrededor de las 20:39 (UTC-4) con la URL del webhook de n8n definida en su entorno, y que los guiones se vieron en la pantalla de alertas de Slack. Esto coincide con el sello de tiempo del mensaje (`2026-10-09T00:39:06 UTC`) y con la ausencia de intervención de la interfaz de revisión humana.

## 8. Corrección aplicada: aislamiento de las pruebas

No hay defecto en el código de producto. Se corrigió el aislamiento de las pruebas con una fixture automática en `tests/conftest.py`, que retira `N8N_ALERT_WEBHOOK_URL` del entorno durante cada prueba, para que `pytest` nunca envíe alertas reales:

```python
@pytest.fixture(autouse=True)
def _sin_alertas_reales(monkeypatch):
    monkeypatch.delenv("N8N_ALERT_WEBHOOK_URL", raising=False)
```

El cambio es aditivo: no modifica código de producto ni pruebas existentes. Las pruebas del módulo de alertas (`tests/test_alertas_n8n.py`) definen su propia URL con `monkeypatch.setenv`, por lo que no se ven afectadas.

### 8.1 Validación

Con el mismo montaje de la sección 3.5 (`N8N_ALERT_WEBHOOK_URL` apuntando a un receptor local):

| Situación | Alertas recibidas por el receptor |
|---|---|
| Antes del cambio: `pytest tests/test_routes.py` | 3 (`DOC-TEST-MF11`, `DOC-TEST-MF11-URG`, `DOC-TEST-MF11-X`) |
| Después del cambio: `pytest` completo (342 pruebas, incluye `tests/test_routes.py`) | 0 |

La suite completa pasa sin fallos tras el cambio (342 pruebas aprobadas) y el receptor, activo durante toda la ejecución, no recibió ninguna alerta.

## 9. Hallazgos derivados (no pertenecen a MF-24)

Se registrarán como bugs o actividades propias (IDs desde MF-32):

| Hallazgo | Severidad | Detalle |
|---|---|---|
| `caso-urgente.png` se clasifica como estándar con confianza alta | Crítica | Falso negativo de urgencia: sin urgencia detectada no hay alerta |
| `caso-estandar.pdf` termina en revisión humana | Alta | El clasificador lo tipa como "Orden de Solicitud de Procedimiento"; la matriz de MF-21 exige procedimientos y la categoría baja a Media (relacionado con MF-25) |
| `p10.jpg` (paciente masculino embarazado) pasa como estándar con confianza 0.99 | Alta | La validación de consistencia no cubre contradicciones clínicas como esta |
| Fallo técnico del clasificador deja `urgente=False` | Media | Un caso urgente con fallo técnico no genera alerta (observado en una corrida con claves mal configuradas) |
| La API responde 415 a archivos `.json` | Media | El MVP lista JSON como entrada |
| `senales_gravedad` en documentos no urgentes contiene frases tranquilizadoras o diagnósticos | Baja | No afecta, porque no generan alerta |
| Fallos de Slack/correo no se ven en el resultado de la ejecución | Baja | Consecuencia de `On Error: Continue` y `Respond: Immediately` |