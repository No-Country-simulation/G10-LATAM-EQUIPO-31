# Historial de triaje (MF-15)

`docs/persistencia-resultados.md` (MF-13) explica cómo se guarda el
**último** resultado conocido de cada documento, en `procesados/{estado}/`
o `errores_tecnicos/`, y cómo ese resultado se **sobrescribe** cada vez
que se reprocesa el mismo `documento_id`.

MF-15 agrega, al lado de eso, un registro que **nunca se sobrescribe**:
un evento nuevo por cada corrida de `POST /documentos`, bajo
`historial/{documento_id}/`, pensado para reconstruir — por
`documento_id` — la clasificación, la extracción, la confianza, la
decisión de routing y la derivación a HITL de cada intento de
procesamiento, no solo del último.

## Dónde se guarda

```
historial/{documento_id}/{timestamp}.json
```

`{timestamp}` es el momento exacto del procesamiento (UTC), con
microsegundos, en formato compacto y ordenable por nombre de archivo:
`20260930T153012456789` (año-mes-día-hora-minuto-segundo-microsegundos,
sin separadores). Se usa este formato en vez del ISO 8601 con `:`/`+`
porque `_sanitizar_nombre_archivo` los convertiría en `_`, dando un
nombre de archivo feo y menos legible.

Reprocesar el mismo `documento_id` agrega un objeto nuevo con un
timestamp distinto — no toca los anteriores ni lo que haya en
`procesados/*`.

## Qué guarda cada evento

Cada evento es el mismo **envelope** que ya arma MF-13 para
`procesados/*` (`documento_id`, `estado`, `timestamp`,
`oci_object_name_original`, `nivel_urgencia`, `resultado` — el estado
completo que devolvió el grafo —, `error`, y `urgente` cuando MF-11 lo
trae), más dos bloques que agrega MF-15:

```json
{
  "...": "... (todo el envelope de MF-13, sin cambios) ...",
  "resumen": {
    "score_confianza_clasificacion": 0.93,
    "destino_principal": null,
    "requiere_auditoria_humana": null,
    "validacion_ok": true
  },
  "recorrido": {
    "agentes_ejecutados": ["clasificador", "extractor", "validacion_pydantic"],
    "proveedor_modelo": {
      "clasificador": "no_disponible (pendiente de que MF-19 lo exponga en el estado)",
      "extractor": "no_disponible (pendiente de que MF-19 lo exponga en el estado)"
    },
    "fallback_utilizado": "no_disponible (pendiente de que MF-19 lo exponga en el estado)",
    "fallos_tecnicos": null
  }
}
```

- **`resumen`** — un resumen aplanado, para no tener que bucear dentro de
  `resultado` para lo más consultado: confianza de la clasificación,
  destino de routing y si requiere revisión humana (ambos `null` hasta
  que MF-11 esté integrado), y si la validación pasó.
- **`recorrido`** — el paso a paso de la corrida:
  - `agentes_ejecutados`: qué nodos del grafo llegaron a correr.
  - `proveedor_modelo` / `fallback_utilizado`: **ver limitación
    conocida** más abajo — hoy quedan en `"no_disponible"` salvo que
    haya fallado todo.
  - `fallos_tecnicos`: se copia tal cual desde el estado del grafo
    (MF-19); es la única señal de proveedor/modelo que existe hoy, y
    solo aparece cuando fallan **todos** los proveedores de un agente.

## Cómo se calcula `agentes_ejecutados`

El grafo de este sprint es lineal (`clasificador → extractor →
validación`, sin ramas condicionales), así que si el grafo terminó sin
lanzar una excepción, la validación siempre corrió. La única variación
posible hoy es MF-19: el nodo extractor corta **antes** de llamar a
cualquier LLM si el clasificador ya agotó Gemini y el fallback (no tiene
sentido gastar cuota del Extractor sin una clasificación válida) — en
ese caso el estado del grafo nunca llega a tener la clave `"extraccion"`.

Regla aplicada en `routes.py`:

1. `resultado is None` (el grafo lanzó una excepción real, se
   interrumpió) → `agentes_ejecutados = []`. No se puede saber con
   certeza en qué nodo estaba cuando crasheó, así que no se inventa.
2. `resultado` existe → `"clasificador"` siempre está.
   `"extractor"` está **salvo** que `fallos_tecnicos` esté poblado **y**
   `"extraccion"` esté ausente del estado (el caso exacto en el que
   MF-19 lo omite). Si el extractor SÍ corrió — con éxito o con su
   propio fallo total degradado — `"extraccion"` está presente, así que
   cuenta como ejecutado aunque `fallos_tecnicos` también esté poblado.
   `"validacion_pydantic"` siempre está (último nodo, sin ramas).

Esta regla asume un grafo sin ramas condicionales; cuando MF-11 agregue
bifurcaciones, conviene revisarla.

## Limitación conocida: proveedor y modelo en el caso exitoso

MF-19 (fallback técnico Gemini → Groq) no expone hoy, en el estado del
grafo, **qué proveedor/modelo produjo el resultado final** cuando un
agente SÍ tiene éxito — ni siquiera si tuvo que reintentar o caer al
fallback antes de lograrlo. Esa información existe como variable local
dentro de `clasificar_documento()` / `extraer_datos_clinicos()`
(`app/agents/classifier.py`, `app/agents/extractor.py`) pero se
descarta si el proveedor principal responde bien; solo sobrevive como
texto embebido en `justificacion`/`observaciones` cuando fallan
**todos** los proveedores de un agente.

Por eso `recorrido.proveedor_modelo` y `recorrido.fallback_utilizado`
quedan en `"no_disponible"` en vez de inventar el dato. Se le propuso a
Mauricio (MF-19) exponer ese detalle como un campo adicional y opcional
del estado (p. ej. `metadata_clasificacion` / `metadata_extraccion` con
`proveedor_usado`/`modelo_usado`/`fallback_activado`/`intentos`) — sin
tocar el contrato de `Classification`/`ExtraccionClinica` ni de nadie
más. Cuando eso exista, `recorrido` puede leerlo con el mismo patrón
`.get()` defensivo que ya usa el resto de `routes.py`.

## Reutiliza el servicio de OCI de MF-13

`OCIStorageService` (MF-04/MF-13) suma dos métodos, mismo patrón que
`upload_resultado`/`get_resultado` (put + verificación por lectura
inmediata, `PersistenciaOCIError` en los mismos casos):

- `upload_historial(documento_id, momento, evento) -> object_name`
- `get_historial(object_name) -> dict`

Un fallo al guardar el historial (`PersistenciaOCIError`) **no** afecta
la respuesta HTTP ni la persistencia en `procesados/*`, que es
independiente — igual que ya pasa con un fallo de `upload_resultado`. La
respuesta de `POST /documentos` suma `historial_ok` y
`oci_object_name_historial`, en paralelo a `persistencia_ok` y
`oci_object_name_resultado`.

## Pruebas

- `tests/test_oci_storage_service.py` — round-trip de
  `upload_historial`/`get_historial`, que dos `momento` distintos no se
  pisan, sanitización de `documento_id`, aislamiento de `recibidos/` y
  `procesados/*`, y los dos casos de fallo (falla la subida, falla la
  verificación).
- `tests/test_routes.py` — que un reproceso genera dos eventos de
  historial distintos (mientras `procesados/*` sigue pisando), que una
  excepción real del grafo igual registra un evento (con
  `agentes_ejecutados` vacío), que un fallo al guardar el historial no
  tumba la respuesta, y los dos casos de `agentes_ejecutados` cuando
  falla el clasificador total (excluye extractor) vs. cuando falla el
  extractor total (lo incluye, porque sí llegó a correr).
- `samples/test_oci_historial.py` — script manual contra el bucket real
  (Gemini y Groq simulados, sin claves de modelos), con los 8 archivos
  de `samples/entradas/`: reprocesa cada uno dos veces y confirma -contra
  OCI de verdad- que quedan dos eventos de historial recuperables y
  distintos, más dos escenarios extra (fallback simulado exitoso, y
  fallo técnico total) para revisar `recorrido` en cada caso.
