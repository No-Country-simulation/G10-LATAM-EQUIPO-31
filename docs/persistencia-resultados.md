# Persistencia de resultados en OCI Object Storage (MF-13)

Este documento describe cómo MediFlow guarda en OCI Object Storage el
resultado del procesamiento de cada documento, vinculado al documento
original por `documento_id`.

## Estructura de carpetas en el bucket

| Carpeta | Contenido |
|---|---|
| `recibidos/` | Documento original, tal como llegó (MF-04). **Nunca se sobrescribe ni se modifica** al persistir un resultado — la persistencia de resultados vive en carpetas separadas. |
| `procesados/` | Resultado de un documento que terminó el flujo correctamente (`validacion_ok = true`). |
| `auditoria_humana/` | Resultado de un documento que terminó el flujo pero necesita revisión humana. |
| `errores_tecnicos/` | Resultado (parcial) de un documento cuyo procesamiento falló por una excepción técnica real (proveedor/modelo, un nodo del grafo que crashea). |

El nombre de objeto para un resultado es siempre
`{carpeta_del_estado}{documento_id}.json` (el `documento_id` se sanitiza con
la misma función que ya se usa para nombres de archivo, para evitar `../` u
otros caracteres problemáticos en la ruta de OCI).

El mapeo estado → carpeta vive en un único lugar:
`ESTADOS_A_PREFIJO` en `app/services/oci_storage_service.py`. Sumar un
estado nuevo (por ejemplo, una futura ruta `urgente/`) es agregar una
entrada a ese diccionario; no requiere tocar la lógica de subida/recuperación.

## Los 3 estados y cómo se determinan hoy

`app/api/routes.py` define `determinar_estado(validacion_ok, hubo_excepcion)`:

- **`error_tecnico`** — el grafo lanzó una excepción real durante su
  ejecución (fallo del proveedor/modelo, un nodo que crashea de forma
  inesperada). La respuesta HTTP también refleja el fallo (código 500).
  Un tipo de archivo no soportado (`415`) **no** cuenta como error técnico:
  se valida antes de tocar OCI o el grafo, y no genera ningún objeto en
  `errores_tecnicos/`.
- **`auditoria_humana`** — el grafo corrió sin excepciones pero
  `validacion_ok` dio `false`.
- **`procesado_exitoso`** — el grafo corrió sin excepciones y
  `validacion_ok` dio `true`.

Esta es la única señal disponible **hoy** (Sprint 2, antes de que MF-09
—consistencia—, MF-10/MF-11 —confianza y enrutamiento HITL— y MF-19
—fallback técnico— estén integrados). Cuando esos tickets aporten una
señal real de enrutamiento (por ejemplo, un campo `requiere_revision_humana`
en el estado del grafo), **solo hay que actualizar `determinar_estado` en
`routes.py`** — el servicio de persistencia (`oci_storage_service.py`) no
necesita cambios porque no conoce reglas de negocio, solo guarda lo que se
le pasa.

## Qué se guarda

El envelope persistido incluye el **estado completo que llegó del flujo**
(no solo los campos que hoy conocemos), para no requerir cambios en la
persistencia cuando MF-09/MF-10/MF-11/MF-19 agreguen campos nuevos:

```json
{
  "documento_id": "...",
  "estado": "procesado_exitoso | auditoria_humana | error_tecnico",
  "timestamp": "ISO 8601 UTC",
  "oci_object_name_original": "recibidos/...",
  "nivel_urgencia": "no_urgente | prioritario | urgente | emergencia | null",
  "resultado": { "clasificacion": {...}, "extraccion": {...}, "validacion": {...} },
  "error": "mensaje de la excepción, solo si estado == error_tecnico"
}
```

`nivel_urgencia` se copia de `extraccion.nivel_urgencia` (ya existe en
`ExtraccionClinica`, `app/schemas/extraccion.py`) a nivel superior del
envelope únicamente para que una futura ruta urgente pueda filtrar sin tener
que desanidar `resultado.extraccion`. No es un campo inventado por MF-13: la
señal ya la produce el Agente Extractor (MF-06).

## Reprocesar el mismo `documento_id`

Si se vuelve a procesar un documento con el mismo `documento_id`, el
resultado se **sobrescribe**: no hay versionado ni historial de reprocesos
todavía. El documento original en `recibidos/` tampoco se ve afectado por
esto (vive en un namespace de objeto distinto). El historial de reprocesos
(guardar cada intento en vez de solo el último) queda para el Sprint 3.

## Verificación de escritura y manejo de errores de persistencia

`OCIStorageService.upload_resultado` verifica la escritura leyendo el
objeto inmediatamente después de subirlo y comparando el contenido. Si la
subida falla o la verificación no coincide, se levanta
`PersistenciaOCIError`.

Un fallo al **persistir el resultado** nunca tira abajo una respuesta cuyo
**procesamiento** sí fue exitoso: `routes.py` captura `PersistenciaOCIError`
por separado y responde igual, marcando `persistencia_ok: false` y
`oci_object_name_resultado: null`, con el error logueado del lado del
servidor.

## Pruebas

- `tests/test_oci_storage_service.py` — round-trip de `upload_resultado` /
  `get_resultado` para los 3 estados, sanitización de `documento_id`,
  validación de estado inválido, que escribir un resultado no toca
  `recibidos/`, y los dos caminos de fallo (`put_object` que falla,
  verificación que no coincide).
- `tests/test_routes.py` — `POST /documentos` de punta a punta (agentes
  mockeados, `OCIStorageService` reemplazado) para los 3 estados, el caso de
  tipo de archivo no soportado (no persiste nada) y el caso de fallo de
  persistencia (no tumba la respuesta).
- `samples/test_oci_resultado.py` — prueba manual contra el bucket real
  (usa el `.env` del usuario) que sube y recupera un resultado de ejemplo
  para cada uno de los 3 estados.
