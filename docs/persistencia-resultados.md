# Persistencia de resultados en OCI Object Storage (MF-13)

Este documento describe cómo MediFlow guarda en OCI Object Storage el
resultado del procesamiento de cada documento, vinculado al documento
original por `documento_id`.

## Estructura de carpetas en el bucket

| Carpeta | Contenido |
|---|---|
| `recibidos/` | Documento original, tal como llegó (MF-04). **Nunca se sobrescribe ni se modifica** al persistir un resultado — la persistencia de resultados vive en carpetas separadas. |
| `procesados/estandar/` | Resultado de un documento enrutado al flujo estándar (`destino_principal = "estandar"`). |
| `procesados/urgente/` | Resultado de un documento enrutado a la cola urgente (`destino_principal = "urgente"`). |
| `procesados/revision_humana/` | Resultado de un documento que necesita revisión humana (`destino_principal = "revision_humana"`). |
| `errores_tecnicos/` | Resultado (parcial o completo) de un documento cuyo procesamiento falló por una excepción técnica real (proveedor/modelo, un nodo del grafo que crashea), o cuyo estado trae `fallos_tecnicos` (MF-19) con al menos un elemento aunque el grafo no haya lanzado excepción. |

El nombre de objeto para un resultado es siempre
`{carpeta_del_estado}{documento_id}.json` (el `documento_id` se sanitiza con
la misma función que ya se usa para nombres de archivo, para evitar `../` u
otros caracteres problemáticos en la ruta de OCI). El documento original en
`recibidos/` usa esa misma sanitización sobre `documento_id` desde MF-13
(antes solo se sanitizaba el nombre de archivo).

El mapeo estado → carpeta vive en un único lugar:
`ESTADOS_A_PREFIJO` en `app/services/oci_storage_service.py`. De ahí se
derivan también `DESTINOS_PRINCIPALES` (los valores de `destino_principal`
que se aceptan tal cual) y `ESTADO_ERROR_TECNICO`. Sumar un destino nuevo
es agregar una entrada a ese diccionario; no requiere tocar la lógica de
subida/recuperación ni `determinar_estado`.

## Los 4 estados y cómo se determinan

Los estados de `procesados/` coinciden con el contrato confirmado de MF-11:
el estado del grafo trae `destino_principal` (`"estandar"`, `"urgente"` o
`"revision_humana"`) más los booleanos `urgente` y
`requiere_auditoria_humana`.

`app/api/routes.py` define
`determinar_estado(validacion_ok, hubo_excepcion, destino_principal=None,
fallos_tecnicos=None)`, que aplica estas reglas en orden:

1. **`error_tecnico` por excepción real** — el grafo lanzó una excepción
   real durante su ejecución (fallo del proveedor/modelo, un nodo que
   crashea de forma inesperada). La respuesta HTTP también refleja el
   fallo (código 500). Un tipo de archivo no soportado (`415`) **no**
   cuenta como error técnico: se valida antes de tocar OCI o el grafo, y
   no genera ningún objeto en `errores_tecnicos/`.
2. **`error_tecnico` por `fallos_tecnicos` (MF-19)** — si el estado del
   grafo trae la clave `fallos_tecnicos` con **al menos un elemento**,
   también se deriva a `error_tecnico`, aunque el grafo no haya lanzado
   ninguna excepción (un nodo puede capturar el fallo internamente y
   dejar que el flujo siga). Tiene la misma prioridad que una excepción
   real: manda por encima de `destino_principal`, y la respuesta HTTP es
   la misma que para el caso 1 (código 500, `status: "error"`,
   `mensaje: "Fallo técnico al procesar el documento"`). A diferencia del
   caso 1, acá sí hay `resultado` (el grafo terminó de correr), así que el
   envelope persiste el estado completo en vez de `null`. El campo `error`
   del envelope no queda en `null`: aunque no hubo una excepción real que
   capturar, se copia ahí el detalle de `resultado.fallos_tecnicos` (cada
   elemento convertido a texto y unido con `"; "`), para que alguien que
   filtre resultados por `error` vea el motivo sin tener que bucear dentro
   de `resultado`.
3. **`destino_principal` válido** — si el estado del grafo trae
   `destino_principal` con uno de los 3 valores del contrato, se usa
   directo como estado (`estandar`, `urgente` o `revision_humana`).
4. **`destino_principal` fuera del contrato** — si viene con cualquier
   valor que no sea **exactamente** `"estandar"`, `"urgente"` o
   `"revision_humana"` (por ejemplo `"Urgente"`, `"estándar"`,
   `" urgente"`, `"revision humana"`), se deriva a **`revision_humana`**
   (aunque `validacion_ok` sea `true`) y se loguea un warning. Ante la duda,
   un documento que podría ser urgente no debe terminar en `estandar`. El
   valor original se sigue guardando tal cual dentro de `resultado`, para
   poder auditarlo.
5. **Fallback (MF-11 todavía no integrado)** — si `destino_principal` no
   viene, se usa la única señal disponible hoy: `validacion_ok = false` →
   `revision_humana`; el resto → `estandar`.

El servicio de persistencia (`oci_storage_service.py`) no conoce reglas de
negocio: solo guarda lo que se le pasa en la carpeta del estado.

> **Nota de integración:** `MediFlowState` (`app/schemas/state.py`) es un
> `TypedDict` y LangGraph solo devuelve las claves declaradas ahí. Para que
> `destino_principal`/`urgente`/`requiere_auditoria_humana` lleguen a
> `routes.py`, MF-11 tiene que agregarlos a `MediFlowState`. Hasta entonces
> aplica siempre el fallback del punto 5. Lo mismo aplica a `fallos_tecnicos`
> (punto 2): hasta que MF-19 lo agregue a `MediFlowState`, `routes.py` nunca
> lo encuentra en el estado y esa regla no se dispara.

## Qué se guarda

El envelope persistido incluye el **estado completo que devuelve
`grafo_mediflow.invoke(...)`**, serializado tal cual (`resultado` es un
volcado plano de esas claves, no un subconjunto elegido a mano), más
metadata de trazabilidad:

```json
{
  "documento_id": "...",
  "estado": "estandar | urgente | revision_humana | error_tecnico",
  "timestamp": "ISO 8601 UTC",
  "oci_object_name_original": "recibidos/...",
  "nivel_urgencia": "no_urgente | prioritario | urgente | emergencia | null",
  "urgente": true,
  "resultado": {
    "documento": { "documento_id": "...", "tipo_archivo": "...", "canal_origen": "...", "nombre_archivo": "...", "mime_type": "..." },
    "clasificacion": { ... } ,
    "extraccion": { ... },
    "validacion_ok": true,
    "errores_validacion": [],
    "destino_principal": "urgente",
    "urgente": true,
    "requiere_auditoria_humana": false
  },
  "error": "mensaje de la excepción, o el detalle de resultado.fallos_tecnicos (MF-19) si no hubo excepción; solo si estado == error_tecnico"
}
```

`urgente` (a nivel superior) y los campos `destino_principal`/`urgente`/
`requiere_auditoria_humana` dentro de `resultado` **solo aparecen cuando el
estado del grafo los trae** (es decir, con MF-11 integrado). No se inventan
valores por defecto.

`resultado` refleja las claves de `MediFlowState` (`app/schemas/state.py`)
tal como el grafo las deja: por eso `validacion_ok`/`errores_validacion`
quedan al mismo nivel que `clasificacion`/`extraccion`, en vez de anidados
bajo una clave `validacion` (esa forma más "cómoda" la sigue teniendo la
respuesta HTTP, para no romper el contrato de la API). La serialización
(`_serializar_estado_grafo` en `app/api/routes.py`) recorre las claves del
estado y llama `.model_dump()` sobre cualquier valor que sea un modelo
Pydantic, así que un campo nuevo que agreguen MF-09/MF-10/MF-11/MF-19 (por
ejemplo un score de confianza combinado o el motivo de derivación) se
persiste automáticamente sin tocar esta función, siempre que sea un valor
plano o un modelo Pydantic (el patrón que ya usa todo el proyecto).

**Excepción**: la clave `documento` (el `DocumentoEntrada` original) se
serializa **sin** `contenido_bytes` ni `documento_texto` — ese contenido ya
vive en `recibidos/` (MF-04), y duplicarlo acá solo agranda el objeto en
OCI sin aportar nada nuevo. El resto de los campos del documento
(`documento_id`, `tipo_archivo`, `canal_origen`, `nombre_archivo`,
`mime_type`) sí se guardan, porque son metadata liviana y útil para
trazabilidad.

`nivel_urgencia` se copia de `extraccion.nivel_urgencia` (ya existe en
`ExtraccionClinica`, `app/schemas/extraccion.py`) y `urgente` se copia del
booleano de MF-11, ambos a nivel superior del envelope únicamente para poder
filtrar sin desanidar `resultado`. Ninguno es un campo inventado por MF-13:
las señales las producen el Agente Extractor (MF-06) y el enrutamiento
(MF-11).

## Reprocesar el mismo `documento_id`

Si se vuelve a procesar un documento con el mismo `documento_id`, el
resultado en `procesados/*`/`errores_tecnicos/` se **sobrescribe**: no hay
versionado ahí. El documento original en `recibidos/` tampoco se ve
afectado por esto (vive en un namespace de objeto distinto).

Desde MF-15, cada corrida (sobrescriba o no el resultado) además queda
registrada como un evento nuevo en `historial/{documento_id}/`, que
**nunca se pisa** — ver [`historial-triaje.md`](historial-triaje.md).

## Verificación de escritura y manejo de errores de persistencia

`OCIStorageService.upload_resultado` verifica la escritura leyendo el
objeto inmediatamente después de subirlo y comparando el contenido. Si la
subida falla o la verificación no coincide, se levanta
`PersistenciaOCIError`.

`POST /documentos` distingue 3 momentos en los que algo puede fallar, cada
uno con una respuesta distinta:

1. **Falla la subida del documento ORIGINAL a `recibidos/`** (paso 3 de
   `routes.py`, antes de correr el grafo). Es una caída de infraestructura,
   no un fallo del flujo: no tiene sentido gastar una llamada al LLM si ni
   siquiera se pudo guardar lo que se va a procesar, y tampoco tiene
   sentido intentar persistir un registro de error contra el mismo OCI que
   acaba de fallar. La API responde **503** con un cuerpo estructurado
   (`status`, `documento_id`, `mensaje`, `error`) y **no** ejecuta el grafo
   ni intenta ninguna otra escritura en OCI.
2. **El grafo lanza una excepción real** (proveedor/modelo, un nodo que
   crashea) — estado `error_tecnico`. Acá sí se intenta persistir un
   registro (con el resultado en `null` y el mensaje de la excepción en
   `error`), y la API responde **500**.
3. **El procesamiento termina bien, pero falla guardar el RESULTADO en
   OCI** (`PersistenciaOCIError`). Esto nunca tira abajo una respuesta cuyo
   procesamiento sí fue exitoso: `routes.py` captura `PersistenciaOCIError`
   por separado y responde con el código que le corresponda al
   procesamiento (200 o 500), marcando `persistencia_ok: false` y
   `oci_object_name_resultado: null`, con el error logueado del lado del
   servidor.

## Limitaciones conocidas

- **Colisión de `documento_id` sanitizados.** `_sanitizar_nombre_archivo`
  reemplaza cualquier carácter fuera de `[A-Za-z0-9._-]` por `_`, y si el
  resultado queda vacío devuelve `"archivo"`. Dos `documento_id` distintos
  pero "sucios" (por ejemplo `"???"` y `"!!!"`) sanitizan al mismo string y
  uno pisaría silenciosamente el resultado (o el original) del otro. Baja
  probabilidad si `documento_id` lo genera el sistema (como en
  `samples/test_oci_connection.py`), pero como viene de un campo de
  formulario del cliente, no hay garantía hoy de que sea único después de
  sanitizar.
- **Condición de carrera en la verificación de escritura.**
  `upload_resultado` hace `put_object` y enseguida `get_object` para
  verificar. Si el mismo `documento_id` se reprocesa en paralelo (dos
  requests concurrentes), la lectura de verificación de una request podría
  leer el contenido que escribió la otra, disparando un falso
  `PersistenciaOCIError`. Es consistente con que ya no hay versionado de
  resultados (ver "Reprocesar el mismo `documento_id`"). `upload_historial`
  (MF-15) tiene la misma limitación de fondo en su propia verificación,
  aunque ahí el riesgo de colisión es mucho menor: cada evento usa un
  nombre de archivo distinto (con microsegundos), así que dos requests
  concurrentes solo chocarían si el reloj del sistema repitiera el mismo
  microsegundo exacto para el mismo `documento_id`.

## Pruebas

- `tests/test_oci_storage_service.py` — round-trip de `upload_resultado` /
  `get_resultado` para los 4 estados, sanitización de `documento_id` (en
  `upload_resultado` y también en `upload_document`), validación de estado
  inválido, que escribir un resultado no toca `recibidos/`, y los dos
  caminos de fallo (`put_object` que falla, verificación que no coincide).
- `tests/test_routes.py` — `POST /documentos` de punta a punta (agentes
  mockeados, `OCIStorageService` reemplazado) para el fallback sin
  `destino_principal` (`estandar`, `revision_humana`, `error_tecnico`), los
  3 valores de `destino_principal` presentes (con `urgente` copiado al
  envelope), `urgente = true` con destino `revision_humana` (se conserva
  sin pisarse), un `destino_principal` fuera del contrato (va a
  `revision_humana` y deja warning), una tabla de casos de
  `determinar_estado` (incluyendo `fallos_tecnicos` de MF-19 con y sin
  excepción, con y sin `destino_principal`), el caso de `fallos_tecnicos`
  sin excepción real a nivel de `POST /documentos` (respuesta 500 igual a
  la de una excepción real, pero con `resultado` completo y `error: null`
  en el envelope), el caso de
  tipo de archivo no soportado (no persiste nada), el caso de fallo de
  persistencia del resultado (no tumba la respuesta), el caso de fallo al
  guardar el original (503 estructurado, no corre el grafo) y los 3
  formatos binarios de `samples/entradas/` (PDF, PNG, JPG), verificando que
  el documento persistido no incluye el contenido binario.
- `samples/test_oci_resultado.py` — prueba manual contra el bucket real
  (usa el `.env` del usuario) que sube y recupera un resultado de ejemplo
  para cada uno de los 4 estados.
