# MF-14: Alertas de casos urgentes con n8n

## 1. Propósito

Cuando MediFlow marca un documento como urgente, notifica al equipo por **Slack**
y por **correo electrónico** a través de un workflow de n8n. La alerta es un
mecanismo externo y **desacoplado** del núcleo: si n8n, Slack o el correo fallan,
el procesamiento y la persistencia del documento continúan normalmente.

```
POST /documentos
   └─ grafo (clasificación → extracción → validación → confianza → routing)
   └─ persistencia en OCI (procesados/ + historial/)
   └─ respuesta HTTP al cliente
   └─ [segundo plano] emitir_alerta_si_corresponde()
            └─ POST webhook n8n ──► Slack
                                └─► Correo
```

## 2. Condición de la alerta

Se alerta cuando la señal reconciliada **`urgente` es `true`** (contrato de MF-11),
**sin importar el destino** (`urgente` o `revision_humana`).

Motivo: en `develop` la confianza manda sobre la ruta. Un documento urgente con
confianza Media/Baja termina en `revision_humana` pero conserva `urgente=true`;
con una condición por destino (`estado == "urgente"`) esos casos no generarían
alerta.

| `urgente` | `estado` (destino) | ¿Alerta? | Texto de la alerta |
| --- | --- | --- | --- |
| `true` | `urgente` | Sí | Caso urgente en cola de emergencia |
| `true` | `revision_humana` | Sí | Urgente, **pendiente de revisión humana** (no validado) |
| `true` | `error_tecnico` | Sí | Urgente con fallo técnico, requiere atención manual |
| `false` / ausente | cualquiera | No | — |

> **Pendiente de aprobación:** este criterio amplía lo que dice MF-14 («ruta
> urgente») y está sujeto a la aprobación de Kimberlyn. Si se prefiere alertar
> solo con `estado == "urgente"`, el cambio es una línea en
> `debe_alertar()` (`app/services/alertas_n8n.py`).

Aprobar o rechazar un caso en el panel de revisión humana (MF-12) no envía ni
cancela alertas: la alerta se emite una vez, al procesar el documento.

## 3. Evento enviado a n8n

`POST` con JSON al webhook. **No incluye datos del paciente** (nombre, documento
de identidad, edad) ni el contenido del documento.

| Campo | Descripción |
| --- | --- |
| `documento_id` | Identificador del documento |
| `estado` | Destino final: `urgente`, `revision_humana` o `error_tecnico` |
| `urgente` | Siempre `true` (solo se envían casos urgentes) |
| `timestamp` | Momento de la corrida (ISO 8601, UTC) |
| `nivel_urgencia` | Nivel que reportó el Extractor |
| `tipo_documento`, `especialidad` | Salida del Clasificador |
| `categoria_confianza`, `score_confianza_final` | Salida de MF-10 |
| `requiere_auditoria_humana` | Salida de MF-11 |
| `senales_gravedad` | Hasta 3 hallazgos textuales que respaldan la urgencia |
| `justificacion_enrutamiento` | Motivo del destino (MF-11) |

El texto de las alertas se arma **dentro del workflow** (nodo «Validar y armar
mensaje»), no en Python: se puede cambiar el formato sin tocar el código.

## 4. Desacoplamiento y tolerancia a fallas

- `notificar_caso_urgente()` nunca lanza excepciones: ante n8n caído, timeout
  (5 s), HTTP de error o URL sin configurar devuelve `False` y deja un log
  (sin la URL del webhook, que puede contener un identificador secreto).
- `emitir_alerta_si_corresponde()` absorbe además cualquier error al armar el evento.
- La ruta la agenda como **tarea en segundo plano**, después de persistir
  resultado e historial: no retrasa la respuesta ni puede alterarla.
- Dentro de n8n, los nodos Slack y Email tienen **On Error: Continue**: si uno
  falla, el otro igual se envía. El webhook responde `200` de inmediato
  (`Respond: Immediately`), antes de intentar enviar.
- Sin `N8N_ALERT_WEBHOOK_URL` el módulo queda inactivo (no hay alertas, no hay errores).

## 5. Configuración

### En MediFlow (`.env`)

| Variable | Descripción |
| --- | --- |
| `N8N_ALERT_WEBHOOK_URL` | URL de **producción** del webhook (`…/webhook/mediflow-urgente`), no la de prueba |
| `N8N_ALERT_WEBHOOK_TOKEN` | Token compartido; se envía en el header `X-MediFlow-Token` |

### En n8n

1. Importar `n8n/mf14-alerta-caso-urgente.json` (**Workflows → Import from file**).
2. Nodo **Webhook caso urgente**: crear/asignar una credencial *Header Auth*
   con nombre `X-MediFlow-Token` y como valor el mismo token de MediFlow.
3. Nodo **Slack alerta**: asignar la credencial de Slack y ajustar el canal.
   Crear un canal del equipo para las alertas (el workflow trae
   `mediflow-alertas-urgentes` como ejemplo) e **invitar al bot** a ese canal.
   Si el canal no se resuelve por nombre, usar «By ID».
4. Nodo **Email alerta**: asignar una credencial SMTP y reemplazar el remitente y
   los destinatarios de ejemplo (`example.com`). Si se prefiere Gmail, se puede
   cambiar por el nodo de Gmail sin tocar el resto del workflow.
5. **Activar** el workflow. Las credenciales no forman parte del JSON ni del repositorio.

## 6. Pruebas

### Automáticas (no usan red)

```bash
pytest tests/test_alertas_n8n.py
```

Cubren: condición de alerta, contenido del evento (sin datos del paciente),
envío con token y timeout, y que **una falla de n8n (caído, timeout, HTTP 4xx/5xx,
error inesperado) no bloquea el procesamiento**: la respuesta sigue siendo
`200` con `persistencia_ok` e `historial_ok` en `true`. También verifican que la
alerta se emite *después* de persistir resultado e historial.

### Validación local del workflow (n8n 2.29.10)

El workflow se importó y ejecutó en una instancia local de n8n con un servidor
SMTP de captura (`127.0.0.1:1025`), una credencial de Slack con token falso y
eventos sintéticos:

| Caso | Resultado |
| --- | --- |
| Webhook sin token o con token incorrecto | `403`, no se ejecuta el workflow |
| Evento `urgente` con token | `200` en ~40 ms (responde antes de enviar); mensaje «caso urgente en cola de emergencia» |
| Evento `revision_humana` con token | `200`; mensaje «urgente, pendiente de revisión humana» |
| Evento con `urgente: false` | `200`; el workflow lo ignora sin enviar nada |
| Slack falla (`invalid_auth`) | El correo se envía igual (el SMTP respondió `250 OK`); la ejecución termina en `success` |

Así quedó comprobado el aislamiento entre canales y el envío de correo contra un
SMTP de prueba. **No se probó el envío real a un workspace de Slack ni a una
bandeja de correo real**: eso requiere las credenciales del equipo (ver
la sección siguiente).

Notas de esta validación:

- El nodo Webhook trae un `webhookId` fijo; sin él, n8n registraría la URL como
  `/webhook/{id-del-workflow}/{nombre-del-nodo}/mediflow-urgente`. Con el
  `webhookId`, la URL de producción es `…/webhook/mediflow-urgente`.
- Si a un nodo de canal **no se le asigna ninguna credencial**, n8n lo marca como
  error de configuración («Node does not have any credentials set») y la
  ejecución queda en `error`. Es un problema de configuración, no de envío:
  asignar las credenciales antes de activar.

### Envío real por Slack y correo

Con el workflow activo y las variables configuradas:

```bash
python samples/probar_alerta_n8n.py                        # destino urgente
python samples/probar_alerta_n8n.py --estado revision_humana
```

Debe llegar un mensaje al canal de Slack y un correo a los destinatarios, con
datos sintéticos. Para comprobar el aislamiento de fallas de punta a punta:

1. Desactivar el workflow (o poner una URL inválida en `N8N_ALERT_WEBHOOK_URL`).
2. Enviar un documento urgente a `POST /documentos`.
3. La respuesta debe ser normal, con el resultado en `procesados/` y el evento en
   `historial/`; en el log de la API aparece una advertencia de alerta no enviada.
4. Opcional: dejar el webhook activo pero sin credencial de Slack (o de correo)
   y comprobar que el otro canal igual envía.

## 7. Archivos

- `app/services/alertas_n8n.py` — condición, evento y envío al webhook.
- `app/api/routes.py` — agenda la alerta como tarea en segundo plano (paso 9).
- `n8n/mf14-alerta-caso-urgente.json` — workflow importable (`active: false`, sin credenciales).
- `tests/test_alertas_n8n.py` — pruebas automáticas.
- `samples/probar_alerta_n8n.py` — envío manual de un evento sintético.
