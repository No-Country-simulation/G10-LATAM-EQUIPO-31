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
    "score_confianza_final": null,
    "categoria_confianza": null,
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
    "fallos_tecnicos": null
  }
}
```

Cuando MF-19 esté integrado y el agente haya corrido, cada entrada de
`proveedor_modelo` deja de ser el placeholder y pasa a ser el detalle
completo tal cual lo trae el estado:

```json
"proveedor_modelo": {
  "clasificador": {
    "proveedor_usado": "groq", "modelo_usado": "qwen/qwen3.8-27b",
    "fallback_utilizado": true, "intentos_principal": 3, "intentos_fallback": 1
  },
  "extractor": {
    "proveedor_usado": "gemini", "modelo_usado": "gemini-3.5-flash-lite",
    "fallback_utilizado": false, "intentos_principal": 1, "intentos_fallback": 0
  }
}
```

- **`resumen`** — un resumen aplanado, para no tener que bucear dentro de
  `resultado` para lo más consultado:
  - `score_confianza_clasificacion`: la autoevaluación cruda del modelo
    (MF-05/MF-06), un solo número de Gemini.
  - `score_confianza_final` / `categoria_confianza` (MF-10): el score ya
    combinado con las reglas de completitud/consistencia, y su categoría
    ("Alta"/"Media"/"Baja") — es la señal que `nodo_routing_condicional`
    (MF-11) usa para decidir `destino_principal`. `null` hasta que MF-10
    esté integrado; no se inventan ni se recalculan acá, se copian tal
    cual del estado, mismo criterio que `destino_principal`.
  - `destino_principal` / `requiere_auditoria_humana` (MF-11): destino de
    routing y si requiere revisión humana. `null` hasta que MF-11 esté
    integrado.
  - `validacion_ok`: si la validación estructural (Sprint 1) pasó.

  `score_confianza_clasificacion` y `score_confianza_final` se mantienen
  ambos porque responden preguntas distintas: uno es "qué pensó el
  modelo" (autoevaluación cruda), el otro es "en qué confiamos al final"
  (ya ponderado con completitud/consistencia). Ninguno pisa al otro.
- **`recorrido`** — el paso a paso de la corrida:
  - `agentes_ejecutados`: qué nodos del grafo llegaron a correr.
  - `proveedor_modelo.clasificador` / `proveedor_modelo.extractor`
    (MF-19): el contenido de `metadata_clasificacion` /
    `metadata_extraccion` del estado, copiado tal cual, **por agente**
    — `{proveedor_usado, modelo_usado, fallback_utilizado,
    intentos_principal, intentos_fallback}`. Mismo criterio que
    `destino_principal`/la confianza: nunca se inventa. Si el estado no
    trae la metadata de ese agente (MF-19 sin integrar, o ese agente
    nunca llegó a correr — ver más abajo), queda
    `"no_disponible (pendiente de que MF-19 lo exponga en el estado)"`.
  - `fallos_tecnicos`: se copia tal cual desde el estado del grafo
    (MF-19); solo aparece cuando fallan **todos** los proveedores de un
    agente.

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

## Proveedor y modelo (MF-19)

Mauricio (MF-19, todavía sin integrar a `develop`) agregó al estado del
grafo `metadata_clasificacion` / `metadata_extraccion`, cada uno con
`{proveedor_usado, modelo_usado, fallback_utilizado, intentos_principal,
intentos_fallback}` — ver `docs/mf-19-fallback-tecnico.md`. `recorrido`
los copia tal cual, por agente, con el mismo criterio defensivo
(`.get()`) que ya usa el resto de `routes.py` para `destino_principal`
y la confianza de MF-10.

Dos casos en los que un agente queda en `"no_disponible"` aunque el otro
sí tenga su metadata — no significa necesariamente que MF-19 no esté
integrado, el mensaje es el mismo en ambos casos:

1. **MF-19 todavía no está en `develop`** → ninguno de los dos agentes
   trae metadata.
2. **El Clasificador falló del todo** → el Extractor nunca llega a
   correr (corta antes de llamar a cualquier LLM, ver
   `app/graph/graph.py::nodo_extractor` en la rama de MF-19) y por lo
   tanto nunca genera `metadata_extraccion`, aunque el Clasificador sí
   tenga la suya (con `proveedor_usado`/`modelo_usado` en `None`, pero
   `fallback_utilizado: true` si llegó a intentarlo).

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
  extractor total (lo incluye, porque sí llegó a correr), que sin MF-10
  integrado `score_confianza_final`/`categoria_confianza` quedan en
  `null`, que cuando el estado los trae se copian tal cual al resumen
  (manteniendo `score_confianza_clasificacion` en paralelo, sin pisarlo),
  que sin MF-19 integrado `proveedor_modelo.clasificador`/`.extractor`
  quedan en `"no_disponible"`, que cuando el estado trae
  `metadata_clasificacion`/`metadata_extraccion` se copian tal cual, y
  que cuando falla el clasificador total el recorrido muestra la
  metadata del Clasificador pero el Extractor sigue en
  `"no_disponible"` (nunca corrió).
- `samples/test_oci_historial.py` — script manual contra el bucket real
  (Gemini y Groq simulados, sin claves de modelos), con los 8 archivos
  de `samples/entradas/`: reprocesa cada uno dos veces y confirma -contra
  OCI de verdad- que quedan dos eventos de historial recuperables y
  distintos, más dos escenarios extra (fallback simulado exitoso, y
  fallo técnico total) para revisar `recorrido` en cada caso.
