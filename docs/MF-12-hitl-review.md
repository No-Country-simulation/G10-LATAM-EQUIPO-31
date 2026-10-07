# MF-12 — Mecanismo HITL y panel de revisión humana

Rama: `feature/MF-12-hitl-review` · Base: `develop` (`38e8bcc`) · Apoyo de persistencia/OCI: Kate (MF-13 / MF-15 / MF-22)

## 1. Objetivo y alcance

Cerrar el ciclo de revisión humana de los documentos que el pipeline ya deriva a `revision_humana`:

- consultar los casos pendientes,
- ver la información necesaria para revisar cada caso,
- decidir **APROBAR** o **RECHAZAR** (el rechazo exige motivo),
- persistir la decisión y mantener la trazabilidad del documento sobre el historial existente (MF-15).

**Fuera de alcance (deliberadamente):**

| No se hace | Motivo |
|---|---|
| Corregir o modificar la información clínica extraída | El enunciado lo excluye; el documento es de un tercero |
| Solicitar un documento nuevo, estado «esperando», cierre manual | No está en MF-12 |
| Guardia anti-reproceso / uso de la huella para decidir | MF-22 lo excluye; la huella es solo identificación y trazabilidad |
| Alertas por Slack o correo | Son MF-14 (solo casos urgentes). HITL no envía notificaciones |
| Autenticación de auditores | Ver §8 |
| Pantalla de Triaje, métricas, modo directo a OCI desde el panel | No son necesarias para cerrar el ciclo HITL |

## 2. Flujo HITL

```
POST /documentos (develop, sin cambios)
   └─ confianza Media/Baja ──► procesados/revision_humana/{id}.json  +  historial/{id}/{ts}.json
                                          │
GET  /auditoria/bandeja  ◄────────────────┘   (pendiente = estado vigente revision_humana y último evento NO es una decisión)
        │
   revisor abre el caso en el panel (extracción, confianza, motivos, validaciones, línea de tiempo)
        │
POST /auditoria/{id}/decision
        ├─ APROBADO ───────────────► historial/{id}/{ts}_decision.json   (decision=APROBADO)
        └─ RECHAZADO + motivo+notas ► historial/{id}/{ts}_decision.json   (decision=RECHAZADO, motivo)
```

Una decisión **solo agrega** un evento al historial. No mueve ni borra `recibidos/`, `procesados/*` ni eventos previos.
Si el mismo `documento_id` se reprocesa y vuelve a `revision_humana`, queda otra vez pendiente (nuevo ciclo en la misma línea de tiempo).

## 3. Decisiones disponibles

| Decisión | Requisitos | Resultado |
|---|---|---|
| `APROBADO` | `auditor`. No admite `motivo` | Evento `decision_humana` |
| `RECHAZADO` | `auditor`, `motivo` del catálogo y `notas` | Evento `decision_humana` con `motivo` |

Catálogo de motivos de rechazo: `ILEGIBLE`, `INCOMPLETO`, `INCONSISTENTE`, `TIPO_INCORRECTO`, `OTRO` (detallar en notas).
Cualquier otro valor de `decision` (incluido `CORREGIDO`) se rechaza con 422; un campo como `extraccion_corregida` se ignora y nunca se guarda.

## 4. API (`app/api/rutas_auditoria.py`)

| Método y ruta | Uso | Códigos |
|---|---|---|
| `GET /auditoria/bandeja?limite=50` | Pendientes (más recientes primero) y decisiones recientes | 200 |
| `GET /documentos/{id}/historial` | Línea de tiempo: procesamientos y decisiones | 200 · 404 |
| `POST /auditoria/{id}/decision` | Registra la decisión | 201 · 404 (no existe) · 409 (no está pendiente o ya decidido) · 422 (datos inválidos) |

Se registra en `main.py` con dos líneas (`import` + `app.include_router(router_auditoria)`). **`routes.py` no se modifica:** las rutas estándar y urgente no cambian.

## 5. Persistencia y trazabilidad

Objeto: `historial/{documento_id_sanitizado}/{AAAAMMDDTHHMMSSffffff}_decision.json`, escrito con `OCIStorageService.escribir_json_nuevo` (apoyo de Kate, PR #47), que usa `if_none_match="*"` (no sobrescribe; si otro auditor escribe en el mismo instante, el segundo recibe 409).
El orden por nombre garantiza que la decisión queda después del último evento aunque el reloj del servidor vaya atrasado.

Ejemplo (generado con el código real):

```json
{
  "schema_version": 1,
  "tipo_evento": "decision_humana",
  "documento_id": "TEST-MF20-FINAL-HITL",
  "decision": "RECHAZADO",
  "motivo": "INCONSISTENTE",
  "notas": "La dosis de la receta es incompatible con el diagnóstico.",
  "auditor": "kimberlyn.r",
  "timestamp": "2026-10-01T12:14:00+00:00",
  "tipo_documento": "Receta Medica",
  "nivel_urgencia": "no_urgente",
  "urgente": false,
  "categoria_confianza": "Media",
  "evento_referencia": "historial/TEST-MF20-FINAL-HITL/20261001T120000000000.json",
  "huella_sha256": "e3b0c442…b855"
}
```

- `evento_referencia`: evento de procesamiento sobre el que se decidió.
- `huella_sha256`: MF-22 (ya en `develop`) la escribe en el envelope de cada evento de procesamiento. La decisión la **copia del evento base** solo para trazabilidad y no la usa para decidir nada. En eventos anteriores a MF-22 no existe y la decisión se guarda igual, sin el campo. El nombre es la constante `CAMPO_HUELLA` de `auditoria_eventos.py`.
- Cada decisión deja una línea de log (`mediflow.app.api.rutas_auditoria`) con documento, decisión, motivo y auditor; nunca el texto de las notas ni datos clínicos.

## 6. Integración con el resto del flujo

- **Estándar y urgente:** sin cambios. Los documentos de esas rutas no entran a la bandeja y no se pueden «decidir» (409). Hay pruebas que lo verifican contra el `POST /documentos` real.
- **MF-14 (alertas urgentes):** independiente. HITL no envía ni cancela alertas. En `develop`, un documento urgente con confianza Media/Baja va a `revision_humana` conservando `urgente=true`; el panel lo muestra primero. Criterio confirmado por Kimberlyn para MF-14: la alerta se dispara por `urgente = true` y no solo por el destino, de modo que un urgente que por confianza Media/Baja termina en `revision_humana` también genera alerta, con un mensaje que indica que está pendiente de revisión humana. Decidir en el panel no cancela ni modifica una alerta ya enviada.
- **MF-21 (confianza):** el panel muestra `motivos_confianza` tal cual llegan (lista de textos) y no depende de su contenido.
- **MF-22 (huella):** ver §5.

## 7. Ajustes sobre la base existente del panel

El panel previo se reutilizó solo en lo necesario:

| Ajuste | Detalle |
|---|---|
| Decisiones | Solo APROBADO / RECHAZADO. Se eliminó la opción de «solicitar documento nuevo» |
| Pestañas | De 3 a 2: *Pendientes* y *Resueltos recientemente* (se eliminó *Esperando documento nuevo*) |
| Datos | Solo vía API (`MEDIFLOW_API_URL`); se eliminó el modo de lectura directa a OCI, que obligaba a tener credenciales en el panel |
| Eliminado | Pantalla de Triaje, métricas, cierre manual de solicitudes, aviso de reenvío sin huella |
| Conflicto 409 | El aviso «ya no está pendiente» ya no se borra con `st.rerun()`; se muestra hasta que el auditor actualiza |
| Notas | La tabla de resueltos muestra también las notas |
| Dependencias | `requests` se declara en `requirements.txt` (el panel la usa) |

## 8. Limitaciones y decisiones abiertas

1. **Auditor sin autenticación (decisión del equipo):** `auditor` es texto libre. Cualquier integrante puede aprobar o rechazar escribiendo su nombre, y queda registrado tal cual. Aceptado para el MVP/pruebas; no es una garantía de identidad.
2. **Alertas:** MF-14 notifica solo lo urgente (`urgente = true`, criterio confirmado por Kimberlyn; lo implementa Sair). Los pendientes de auditoría que no son urgentes se consultan únicamente en el panel. MF-12 no agrega lógica de alertas.
3. **Documento original:** el panel muestra la extracción y los metadatos, pero no el archivo original (`recibidos/`); no existe un endpoint que lo sirva.
4. **Persistencia OCI:** la bandeja y las decisiones usan `OCIStorageService.listar`, `leer_json` y `escribir_json_nuevo` (PR #47, apoyo de Kate). Esos métodos se probaron contra el bucket real en una clave temporal de `pruebas/`: no sobrescriben (412 → `FileExistsError`) y `listar` devuelve fechas reales.
5. **Caché del panel:** la bandeja se cachea 30 s; «Actualizar bandeja» fuerza la lectura.
6. **Flujo HITL validado contra OCI real:** las pruebas automáticas usan el `OCIStorageService` real sobre un cliente OCI simulado, y las evidencias de APROBAR y RECHAZAR (§11) se generaron contra el bucket real.

## 9. Pruebas

| Archivo | Pruebas | Qué cubre |
|---|---|---|
| `tests/test_auditoria_eventos.py` | 20 | Reglas de bandeja y decisión: pendiente/resuelto, reprocesos, validaciones, no sobrescritura, huella opcional, reloj atrasado, objetos corruptos |
| `tests/test_rutas_auditoria.py` | 5 | Endpoints: aprobar, rechazar con motivo, códigos 404/409/422, sin corrección clínica, logs |
| `tests/test_hitl_flujo_integrado.py` | 6 | `POST /documentos` real + `OCIStorageService` real (cliente OCI simulado) → `revision_humana` → bandeja → aprobar / rechazar → historial; la decisión hereda el SHA-256 real (MF-22); estándar y urgente intactos; urgente de baja confianza |
| `tests/test_panel_hitl_ui.py` | 7 | Panel (Streamlit AppTest): sin edición, auditor obligatorio, motivo y notas al rechazar, conflicto |

Resultado: `python -m pytest` → **229 pasan** (191 existentes: `develop` con MF-22 y los métodos OCI del PR #47; más 38 nuevas de MF-12).

## 10. Cómo ejecutarlo (PowerShell, desde la raíz del repo)

```powershell
pip install -r requirements.txt
uvicorn main:app --port 8000                              # terminal 1 (necesita .env con credenciales de OCI)
streamlit run frontend/panel_hitl.py --server.port 8502   # terminal 2
```

Variables del panel: `MEDIFLOW_API_URL` (por defecto `http://localhost:8000`), `MEDIFLOW_ZONA_HORARIA` (`America/Bogota`), `MEDIFLOW_MAX_COLA` (50).

## 11. Evidencias

Evidencias generadas por Kate con la versión final (#48, `7bf578e`) contra el bucket OCI real, usando el archivo `samples/entradas/09_receta_inconsistente_hitl.txt` con los IDs `MF12-EVID-APROBAR` y `MF12-EVID-RECHAZAR`.

| Escenario | Archivos en `docs/assets/sprint-3/` | Estado |
|---|---|---|
| Caso pendiente en el panel (APROBAR) | `evidencia-hitl-pendiente.png` | [x] |
| Caso pendiente en el panel (RECHAZAR) | `evidencia-hitl-rechazar-pendiente.png` | [x] |
| **APROBAR** — panel | `evidencia-hitl-aprobar-panel.png` | [x] |
| **APROBAR** — objeto `_decision.json` en OCI | `evidencia-hitl-aprobar-oci.png` y `respuesta-hitl-aprobar.json` | [x] |
| **RECHAZAR** (con motivo y notas) — panel | `evidencia-hitl-rechazar-panel.png` | [x] |
| **RECHAZAR** — objeto `_decision.json` en OCI | `evidencia-hitl-rechazar-oci.png` y `respuesta-hitl-rechazar.json` | [x] |
| Suite automatizada en verde | `evidencia-tests-automatizados.png` | [x] |

Notas sobre las evidencias:

- `MF12-EVID-APROBAR` tiene un evento extra en `historial/` y un objeto en `errores_tecnicos/MF12-EVID-APROBAR.json`: el primer envío falló porque el `.env` no tenía las claves de Gemini (no fue un fallo del código). El segundo envío salió bien y es el que referencia la decisión (`evento_referencia`).
- Ambos casos usan el mismo archivo de entrada, por eso la `huella_sha256` coincide. Cada caso tiene un `documento_id` distinto, porque una decisión no se puede repetir sobre el mismo ciclo.
- El panel muestra hora de Bogotá y el bucket UTC (5 horas de diferencia).
