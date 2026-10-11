# MF-28 — Interfaz amigable de entrada

Rama: `feature/MF-28-interfaz-amigable-de-entrada` · Base: `develop` (`3af94ba`) · Apoyo de validación OCI/Gemini: Kate

## 1. Objetivo y alcance

Ofrecer una interfaz de entrada para el MVP, sin depender de Swagger como UI, usando la API existente:

| Entregable de MF-28 | Estado |
|---|---|
| Carga de documentos | Hecho (§3, §4, §5, §6) |
| Consulta de resultados | Hecho (§7) |
| Acceso a HITL | Hecho: menú lateral hacia el panel de revisión humana (§9) |
| Usar la API existente, sin modificarla | Cumplido: solo se consumen `POST /documentos` y `GET /documentos/{id}/historial` |
| Validación con OCI y Gemini reales | Hecha por Kate (§11); observaciones y decisiones en §12 |

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
| `tests/test_carga_archivos.py` | 43 pruebas automatizadas |
| `tests/test_consulta_resultados.py` | 16 pruebas automatizadas |

## 3. Carga: formatos aceptados

El formato **no se elige a mano**: se deduce del archivo (extensión y contenido).

| Extensión | Formato | Content-Type que se envía a la API |
|---|---|---|
| `.jpg`, `.jpeg` | JPG | `image/jpeg` |
| `.png` | PNG | `image/png` |
| `.pdf` | PDF | `application/pdf` |
| `.json` | JSON | `text/plain` |
| `.md`, `.markdown` | Markdown | `text/plain` |

JSON y Markdown viajan como `text/plain` porque `POST /documentos` solo acepta `text/*`, `application/pdf` e `image/*`: con `application/json` la API responde 415 (hay una prueba que lo documenta y la prueba con OCI lo confirmó, §11).

Nota: el backend etiqueta todo `text/*` con `tipo_archivo = "JSON"` (comentario temporal en `routes.py`, pendiente del contrato de MF-02). Un `.md` se procesa igual que un `.txt`, pero queda marcado como «JSON» en el documento persistido. No afecta el procesamiento ni la consulta, y no se modifica en MF-28.

## 4. Carga: validaciones en la interfaz

Antes de enviar, y con el botón «Enviar al pipeline» bloqueado mientras el archivo no sea válido:

- **Formato no válido:** muestra *«Formato o tipo de archivo no válido (.docx) en "informe.docx". Formatos permitidos: JPG, PNG, PDF, JSON y Markdown (…)»*.
- Archivo vacío o que **no pese menos de 20 MB** (`maxUploadSize` de `.streamlit/config.toml`, variable `MEDIFLOW_MAX_MB_CARGA`). El cargador de Streamlit rechaza por sí mismo los archivos de exactamente 20 MB, por eso el texto dice «menos de 20 MB».
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

**Atención al repetir un ID** (comprobado en la prueba con OCI, §12): la API acepta el reenvío y reprocesa el documento. El historial guarda cada corrida, pero el resultado de `procesados/` solo se reemplaza si el estado es el mismo; si cambia (por ejemplo, de estándar a revisión humana) queda una copia en cada carpeta. En pruebas conviene usar IDs reconocibles, por ejemplo `PRUEBA-NOMBRE-001` (ver también `docs/persistencia-resultados.md`).

## 6. Carga: contrato con la API

La interfaz envía `POST /documentos` (multipart: `documento_id`, `canal_origen`, `archivo`), sin cambios en la ruta. Errores que muestra:

| Situación | Mensaje |
|---|---|
| 415, 500, 503 u otro error de la API | `No se pudo enviar el documento: <código>: <detalle de la API>` |
| API apagada | `No hay conexión con la API (<url>). Verifique que el servicio esté en ejecución e inténtelo de nuevo.` |
| Sin respuesta en `MEDIFLOW_TIMEOUT_CARGA` (120 s) | `No se pudo confirmar el envío…`: avisa que el documento pudo haberse procesado, indica buscarlo en «Consulta de resultados» (el ID queda precargado) antes de reenviarlo, para no duplicarlo |

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

Para cada documento muestra destino, nivel de urgencia, confianza final, tipo, validación, motivos de la confianza (sin textos repetidos), justificación del enrutamiento, datos extraídos (solo lectura), campos no encontrados, modelos usados y la **línea de tiempo** (procesamientos y decisiones). Si el documento se procesó varias veces, se muestra la más reciente; una decisión humana solo cuenta si es posterior a ese procesamiento.

Las horas se muestran en la zona configurada en `MEDIFLOW_ZONA_HORARIA` (por defecto `America/Bogota`, la misma que usa el panel HITL) y la pantalla indica cuál es.

## 8. Qué se conserva

- Panel de revisión humana idéntico (Auditor, Filtros, Pendientes y Resueltos, aprobar y rechazar), con el mismo tema y la misma responsividad.
- `panel_hitl.py`, `panel_carga.py` y `panel_consulta.py` se siguen pudiendo arrancar por separado.

## 9. Cómo ejecutarlo

```powershell
uvicorn main:app --port 8000
streamlit run frontend/mediflow.py
```

Direcciones: `/carga`, `/consulta` y `/revision`.

## 10. Pruebas automatizadas y evidencias

**Automatizadas:** `python -m pytest` → **331 pasan** (272 existentes + 59 nuevas de MF-28: 43 de carga y 16 de consulta), con `streamlit==1.64.0`, la versión fijada en `requirements.txt`.

Cubren: validación de cada formato y de cada rechazo (incluido el límite de tamaño), campos y generación de ID, cliente HTTP (éxito, 415, 500, sin conexión y tiempo agotado), lectura del historial y situaciones de la consulta (automático, pendiente, aprobado, rechazado, reprocesado, error técnico, avisos sin repetir), **contratos contra el backend real** (los 5 formatos pasan; la consulta interpreta lo que guarda el flujo real de `POST /documentos` y de las decisiones HITL) y el flujo completo de ambas pantallas con `AppTest`.

**Evidencias** (carpeta `docs/assets/sprint-4/mf-28-interfaz-entrada/`):

*Pruebas automatizadas e interfaz (API simulada y datos de ejemplo, sobre el código final):*

| Escenario | Archivo | Estado |
|---|---|---|
| Resultado de `pytest` (331 pasan) | [evidencia-tests-automatizados.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-tests-automatizados.png) | OK |
| Carga: estado inicial | [evidencia-carga-estado-inicial.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-carga-estado-inicial.png) | OK |
| Carga: formato no válido (`.docx`) con la lista de formatos | [evidencia-carga-formato-no-valido.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-carga-formato-no-valido.png) | OK |
| Carga: archivo válido (`.pdf`) y botón habilitado | [evidencia-carga-archivo-valido.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-carga-archivo-valido.png) | OK |
| Consulta: documento pendiente de revisión | [evidencia-consulta-resultado.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-resultado.png) | OK (datos de ejemplo) |
| Consulta: ID no encontrado | [evidencia-consulta-no-encontrado.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-no-encontrado.png) | OK |
| Menú lateral, opción Carga de documentos | [evidencia-menu-carga.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-menu-carga.png) | OK |
| Menú lateral, opción Revisión humana | [evidencia-menu-revision-humana.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-menu-revision-humana.png) | OK (datos de ejemplo) |

*Prueba con OCI y Gemini reales (Kate; ver §11):*

| Escenario | Archivo | Estado |
|---|---|---|
| Carga de un PDF real: pantalla de resultado | [evidencia-carga-real-resultado.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-carga-real-resultado.png) | OK |
| Respuesta de la API de esa carga | [respuesta-carga-real.json](./assets/sprint-4/mf-28-interfaz-entrada/respuesta-carga-real.json) | OK |
| Original en `recibidos/` (OCI) | [evidencia-oci-carga-original.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-oci-carga-original.png) | OK |
| Resultado en `procesados/estandar/` (OCI) | [evidencia-oci-resultado.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-oci-resultado.png) | OK |
| Consulta de ese documento | [evidencia-consulta-real.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-real.png) | OK |
| Formato PNG: consulta | [evidencia-consulta-png.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-png.png) | OK |
| Formato JPG: consulta | [evidencia-consulta-jpg.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-jpg.png) | OK |
| Formato Markdown: consulta | [evidencia-consulta-md.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-md.png) | OK |
| Formato JSON: carga | [evidencia-carga-json.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-carga-json.png) | OK |
| Caso derivado a revisión humana (007), antes de decidir | [evidencia-consulta-007-pendiente.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-007-pendiente.png) | OK |
| Mismo caso, tras aprobarlo en HITL | [evidencia-consulta-real-decision.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-real-decision.png) | OK |
| ID inexistente (005, rechazado por la API con 415, no se guardó) | [evidencia-consulta-005-no-encontrado.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-005-no-encontrado.png) | OK |
| API apagada | [evidencia-servidor-caido.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-servidor-caido.png) | OK |
| Archivo de 20 MB exactos bloqueado | [evidencia-archivo-20mb-bloqueado.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-archivo-20mb-bloqueado.png) | OK (con observación, §12) |
| PDF de 19 MB: tiempo de espera agotado | [evidencia-archivo-19mb-timeout.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-archivo-19mb-timeout.png) | OK (con observación, §12) |

Las capturas de Kate se tomaron sobre el commit `3366b79`, antes de los ajustes de §12, por lo que algunos textos (por ejemplo «Máx. 20 MB» o la mención a `uvicorn` en el aviso de API apagada) corresponden a esa versión.

## 11. Prueba con OCI y Gemini reales

Realizada por Kate en su entorno local, sobre el commit `3366b79`, con acceso al bucket y a Gemini reales. IDs `PRUEBA-KATE-xxx`.

| # | Punto | Resultado |
|---|---|---|
| 1 | Cargar un PDF real | OK |
| 2 | Archivos en el bucket | OK: `recibidos/PRUEBA-KATE-001_06_receta_medica.pdf`, `procesados/estandar/PRUEBA-KATE-001.json` y `historial/PRUEBA-KATE-001/…json` |
| 3 | Consultar el documento | OK: Receta Médica, `no_urgente`, 0.93 Alta, datos extraídos, campos no encontrados y línea de tiempo |
| 4 | Los 5 formatos desde la app | OK: PNG (002, 010), JPG (003, 011), Markdown (004, 012) y JSON (006, 013), además del PDF |
| 5 | Caso derivado a revisión humana (007) | OK: aparece pendiente en «Revisión humana»; tras aprobarlo, la consulta muestra «Aprobado por …», destino Auditoría humana y la decisión en la línea de tiempo |
| 6 | API apagada (008) | OK: aviso claro, sin romper la pantalla |
| 7 | Archivo pesado | OK con observación: 19 MB pasa; 20 MB exactos se bloquea |

Además, enviado directamente a la API, `application/json` responde 415 (`Tipo de archivo no soportado`); la app lo evita enviando `.json` y `.md` como `text/plain`, y la consulta del rechazado confirma que no se guardó nada.

## 12. Observaciones de la prueba y decisión

| # | Observación | Decisión |
|---|---|---|
| 1 | `application/json` directo a la API da 415 | Comportamiento esperado de la API. La app ya lo evita (§3). Sin cambios |
| 2 | Un ID repetido con archivos distintos deja el resultado en `procesados/estandar` y en `procesados/revision_humana`, con dos entradas en el historial | **Corresponde al backend** (persistencia), fuera del alcance de MF-28. Queda documentado en §5. Se sugiere evaluarlo en MF-31 u otra actividad |
| 3 | El PDF de 19 MB tarda más de 120 s; la API termina bien y queda en revisión humana, y reenviar por el aviso duplicaría el documento | **Ajustado:** el aviso ahora indica buscar el documento en «Consulta de resultados» (ID precargado) antes de reenviar. El tiempo se puede subir con `MEDIFLOW_TIMEOUT_CARGA` |
| 4 | Dice «Máx. 20 MB» pero 20 MB exactos se rechaza, sin motivo visible | **Ajustado:** el texto dice «menos de 20 MB» y la validación propia usa la misma regla |
| 5 | El aviso de API apagada menciona `uvicorn main:app`, algo técnico | **Ajustado:** el mensaje ya no lo menciona (§6) |
| 6 | «Datos extraídos» muestra filas vacías (tipo y número de documento, sexo) | Coherente con «Campos no encontrados» y con el panel HITL, que usa la misma función. Sin cambios |
| 7 | Un aviso aparece repetido (motivo e inconsistencia con el mismo texto) | **Ajustado en la consulta:** se muestra una sola vez. El panel HITL existente (MF-12) lista motivos e inconsistencias por separado y tiene la misma repetición; no se modificó aquí. Se sugiere corregirlo allí |
| 8 | Un puntaje de 0.93 queda «Alta» en el caso 001 y «Media» en el 007 | La categoría parece depender de más factores que el puntaje (los motivos del 007 incluyen una inconsistencia: «Receta Médica» con estudios complejos). Es lógica de confianza del backend, no de MF-28; para MF-24 y MF-25 |
| 9 | Las horas aparecen en UTC-5, no en la hora local de quien consulta (Kate está en UTC-3) | La zona **ya es configurable** con `MEDIFLOW_ZONA_HORARIA` (por defecto `America/Bogota`), compartida con el panel HITL. **Ajustado:** la consulta indica la zona usada. Para UTC-3, por ejemplo: `$env:MEDIFLOW_ZONA_HORARIA = "America/Argentina/Buenos_Aires"` antes de iniciar `streamlit` |
| 10 | Las pruebas `PRUEBA-KATE-*` quedaron en el bucket | Kate las limpia más adelante |

Los ajustes 3, 4, 5, 7 y 9 se verificaron con pruebas automatizadas y con capturas de la interfaz (API simulada); no se repitieron contra OCI.

## 13. Pendiente

- [ ] Anexar `evidencia-id-repetido-listado.txt` (listado de objetos del bucket con el ID repetido, observación 2), que Kate adjuntó en su comentario del PR.
- [ ] Opcional: que Kate repita en su entorno el PDF de 19 MB y el archivo de 20 MB para ver los mensajes ajustados.
- [ ] Decidir con el equipo dónde se atienden las observaciones 2, 7 y 8, que corresponden a otras partes del sistema.
