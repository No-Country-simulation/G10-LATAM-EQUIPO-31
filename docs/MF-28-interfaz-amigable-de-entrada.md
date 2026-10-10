# MF-28 — Interfaz amigable de entrada

Rama: `feature/MF-28-interfaz-amigable-de-entrada` · Base: `develop` (`3af94ba`)

## 1. Objetivo y alcance

Ofrecer una interfaz de entrada para el MVP, sin depender de Swagger como UI, usando la API existente:

| Entregable de MF-28 | Estado |
|---|---|
| Carga de documentos | Hecho (§3, §4, §5, §6) |
| Consulta de resultados | Hecho (§7) |
| Acceso a HITL | Hecho: menú lateral hacia el panel de revisión humana (§9) |
| Usar la API existente, sin modificarla | Cumplido: solo se consumen `POST /documentos` y `GET /documentos/{id}/historial` |

**Fuera de alcance (deliberadamente):**

| No se hace | Motivo |
|---|---|
| Modificar la API, el grafo, los agentes, OCI o la persistencia | MF-28 consume la API tal como está |
| Modificar el panel de revisión humana (`panel_hitl.py`) | Se conserva idéntico; solo se le agrega un acceso desde el menú |
| Pantalla de Triaje con métricas y gráficas | No existe en esta versión de `develop` y no se pide en MF-28 |
| Reprocesar o editar documentos desde la consulta | La consulta es de solo lectura |
| Autenticación | Sin autenticación en el MVP, igual que el panel HITL |

## 2. Qué se agregó

Solo archivos nuevos; no se modificó ningún archivo existente.

| Archivo | Uso |
|---|---|
| `frontend/carga_archivos.py` | Validación del archivo, envío a la API y sección «Enviar documento» |
| `frontend/panel_carga.py` | Página de carga (reutiliza el tema de `estilo.py`) |
| `frontend/consulta_resultados.py` | Consulta por ID: lectura del historial y sección «Consultar resultado» |
| `frontend/panel_consulta.py` | Página de consulta |
| `frontend/mediflow.py` | Punto de entrada con menú lateral: **Carga de documentos**, **Consulta de resultados** y **Revisión humana** |
| `tests/test_carga_archivos.py` | 41 pruebas automatizadas |
| `tests/test_consulta_resultados.py` | 14 pruebas automatizadas |

## 3. Carga: formatos aceptados

El formato **no se elige a mano**: se deduce del archivo (extensión y contenido).

| Extensión | Formato | Content-Type que se envía a la API |
|---|---|---|
| `.jpg`, `.jpeg` | JPG | `image/jpeg` |
| `.png` | PNG | `image/png` |
| `.pdf` | PDF | `application/pdf` |
| `.json` | JSON | `text/plain` |
| `.md`, `.markdown` | Markdown | `text/plain` |

JSON y Markdown viajan como `text/plain` porque `POST /documentos` solo acepta `text/*`, `application/pdf` e `image/*`: con `application/json` la API responde 415 (hay una prueba que lo documenta).

## 4. Carga: validaciones en la interfaz

Antes de enviar, y con el botón «Enviar al pipeline» bloqueado mientras el archivo no sea válido:

- **Formato no válido:** muestra *«Formato o tipo de archivo no válido (.docx) en "informe.docx". Formatos permitidos: JPG, PNG, PDF, JSON y Markdown (…)»*.
- Archivo vacío o de más de 20 MB (`maxUploadSize` de `.streamlit/config.toml`, variable `MEDIFLOW_MAX_MB_CARGA`).
- Contenido que no coincide con la extensión (por ejemplo, un `.txt` renombrado a `.pdf`).
- JSON mal formado (indica línea y columna) y texto que no esté en UTF-8.
- ID del documento o canal de origen vacíos o con caracteres no admitidos.

## 5. Carga: campos y manejo de ID

| Campo | Comportamiento |
|---|---|
| ID del documento | Se genera solo (`DOC-AAAAMMDD-HHMMSS-XXXX`) y es editable. Admite letras, números, `.`, `_` y `-`; sin espacios; máximo 80 caracteres |
| Canal de origen | Texto editable; por defecto `Panel_Web` |
| Cargar archivo | Un archivo por envío |

Tras cada envío exitoso el formulario se reinicia con un ID nuevo, y el ID enviado queda precargado en la pantalla de consulta.

**Atención al probar:** reenviar un mismo `documento_id` sobrescribe el resultado anterior en `procesados/` (el historial sí conserva cada corrida; ver `docs/persistencia-resultados.md`). En pruebas conviene usar IDs reconocibles, por ejemplo `PRUEBA-NOMBRE-001`.

## 6. Carga: contrato con la API

La interfaz envía `POST /documentos` (multipart: `documento_id`, `canal_origen`, `archivo`), sin cambios en la ruta. Errores que muestra:

| Situación | Mensaje |
|---|---|
| 415, 500, 503 u otro error de la API | `No se pudo enviar el documento: <código>: <detalle de la API>` |
| API apagada | `No hay conexión con la API en … (¿está corriendo uvicorn main:app?)` |
| Sin respuesta en `MEDIFLOW_TIMEOUT_CARGA` (120 s) | Avisa que el documento pudo haberse procesado y pide revisar antes de reenviarlo |

Al terminar bien, muestra el documento, el destino (Automático, Alerta urgente o Auditoría humana), el nivel de urgencia y la respuesta JSON completa.

## 7. Consulta de resultados

Dado el ID de un documento ya enviado, muestra cómo quedó su procesamiento. **Solo lectura:** usa `GET /documentos/{id}/historial` (ya existente), que devuelve cada corrida con su resultado y las decisiones de revisión humana. Reutiliza la misma normalización del panel HITL (`utils_frontend._item_desde_evento`), por lo que ambos paneles muestran lo mismo.

| Situación del documento | Qué muestra |
|---|---|
| Procesado automáticamente | Aviso verde; si es urgente, aviso rojo de alerta urgente |
| Derivado a revisión humana, sin decisión | Aviso «Pendiente de revisión humana» |
| Con decisión humana | «Aprobado por …» o «Rechazado por … — motivo y notas» |
| Error técnico del pipeline | Aviso de error técnico |
| ID inexistente (404) | «No se encontró ningún documento con el ID …» |
| API apagada u otro error | `No se pudo consultar el documento: …` |

Para cada documento muestra destino, nivel de urgencia, confianza final, tipo, validación, motivos de la confianza, justificación del enrutamiento, datos extraídos (solo lectura), campos no encontrados, modelos usados y la **línea de tiempo** (procesamientos y decisiones). Si el documento se procesó varias veces, se muestra la más reciente; una decisión humana solo cuenta si es posterior a ese procesamiento.

## 8. Qué se conserva

- Panel de revisión humana idéntico (Auditor, Filtros, Pendientes y Resueltos, aprobar y rechazar), con el mismo tema y la misma responsividad.
- `panel_hitl.py`, `panel_carga.py` y `panel_consulta.py` se siguen pudiendo arrancar por separado.

## 9. Cómo ejecutarlo

```powershell
uvicorn main:app --port 8000
streamlit run frontend/mediflow.py
```

Direcciones: `/carga`, `/consulta` y `/revision`.

## 10. Pruebas y evidencias

**Automatizadas:** `python -m pytest` → **327 pasan** (272 existentes + 55 nuevas de MF-28: 41 de carga y 14 de consulta), con `streamlit==1.64.0` como fija `requirements.txt`.

Cubren: validación de cada formato y de cada rechazo, campos y generación de ID, cliente HTTP (éxito, 415, 500, sin conexión y timeout), lectura del historial y situaciones de la consulta (automático, pendiente, aprobado, rechazado, reprocesado, error técnico), **contratos contra el backend real** (los 5 formatos pasan; la consulta interpreta lo que guarda el flujo real de `POST /documentos` y de las decisiones HITL) y el flujo completo de ambas pantallas con `AppTest`.

**Evidencias** (carpeta `docs/assets/sprint-4/mf-28-interfaz-entrada/`):

| Escenario | Archivo | Estado |
|---|---|---|
| Resultado de `pytest` | [evidencia-tests-automatizados.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-tests-automatizados.png) | OK |
| Carga: estado inicial | [evidencia-carga-estado-inicial.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-carga-estado-inicial.png) | OK |
| Carga: formato no válido (`.docx`) con la lista de formatos | [evidencia-carga-formato-no-valido.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-carga-formato-no-valido.png) | OK |
| Carga: archivo válido (`.pdf`) y botón habilitado | [evidencia-carga-archivo-valido.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-carga-archivo-valido.png) | OK |
| Consulta: resultado de un documento pendiente de revisión | [evidencia-consulta-resultado.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-resultado.png) | OK (datos de ejemplo) |
| Consulta: ID no encontrado | [evidencia-consulta-no-encontrado.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-no-encontrado.png) | OK |
| Menú lateral, opción Carga de documentos | [evidencia-menu-carga.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-menu-carga.png) | OK |
| Menú lateral, opción Revisión humana | [evidencia-menu-revision-humana.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-menu-revision-humana.png) | OK (datos de ejemplo) |

Las capturas de la interfaz se tomaron con la API simulada y datos de ejemplo; no incluyen OCI ni Gemini.

## 11. Pendiente

**Prueba con OCI y Gemini reales** (a cargo de Kate, que opera el entorno OCI y las credenciales; las evidencias se registran en esta misma subcarpeta):

- [ ] Enviar un PDF real y ver la pantalla de resultado completa.
- [ ] Confirmar el original en `recibidos/` y el resultado en `procesados/…`.
- [ ] Consultar ese mismo documento en «Consulta de resultados» (el ID llega precargado) y comparar con lo enviado.
- [ ] Probar los 5 formatos contra Gemini (JSON y Markdown como texto plano).
- [ ] Probar un archivo pesado (~15-20 MB): el tope real podría quedar por debajo de 20 MB por el límite de Gemini y el timeout de 120 s.
- [ ] Derivar un caso a revisión humana, aprobarlo o rechazarlo en HITL y verificar que la consulta muestra la decisión.
- [ ] Verificar los avisos con la API apagada (carga y consulta).
