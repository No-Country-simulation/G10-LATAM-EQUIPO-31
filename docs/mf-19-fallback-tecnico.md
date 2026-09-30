# MF-19 | Fallback técnico LLM para Clasificador y Extractor

Rama: `feature/MF-19-fallback-tecnico-llm` — dependencias: MF-02, MF-05, MF-06.

## Objetivo

Que el Clasificador y el Extractor puedan seguir procesando un documento
cuando el LLM **principal** (Gemini) tiene un **fallo técnico** — timeout,
indisponibilidad, error 429 o error 5xx — pasando a un modelo/proveedor
**secundario**, sin que el resto del flujo note la diferencia (mismos
contratos de salida: `Classification` y `ExtraccionClinica`).

Gemini sigue siendo el modelo principal en los dos agentes; nada de este
trabajo lo cambia.

## Decisión del equipo: proveedor secundario

Propuesta evaluada y adoptada: **Groq, modelo `qwen/qwen3.8-27b`**
(`app/services/groq_client.py`). Motivos y verificación contra la
documentación oficial de Groq al momento de implementar esto:

- Es uno de los dos únicos modelos de Groq con capacidad de **visión**
  (`qwen/qwen3.6-27b` y `qwen/qwen3.8-27b`), necesaria para procesar
  imágenes y documentos escaneados.
- Es uno de los tres únicos modelos de Groq con **Structured Outputs en
  modo estricto** (`strict: true`), junto con `openai/gpt-oss-20b` y
  `openai/gpt-oss-120b`), lo que permite validar la respuesta directo
  contra el schema Pydantic sin depender de que el LLM "se porte bien".
- Plan gratuito, sin tarjeta, con estos límites para `qwen/qwen3.8-27b`
  (confirmados en la documentación oficial de límites de Groq):
  **30 solicitudes/min, 1.000 solicitudes/día, 8.000 tokens/min,
  200.000 tokens/día**. El límite es por organización/cuenta, no por
  API key individual.
- Ventana de contexto de 131.072 tokens, hasta 16.384 tokens de salida,
  máximo 20 MB por solicitud con imagen (confirmado en la ficha oficial
  del modelo).

Se descartó la otra alternativa que se puso sobre la mesa,
`llama-3.2-90b-vision-preview`: no aparece en la lista vigente de modelos
con visión de Groq, y su modelo hermano más chico
(`llama-3.2-11b-vision-preview`) ya está confirmado como decomisionado
("model_decommissioned"). Groq viene retirando en cadena toda esa
generación de modelos. Usarlo como fallback sería contraproducente: el
día que se necesite de verdad (Gemini caído), muy probablemente
respondería con un error, no con una recuperación.

### Limitación conocida y aceptada para esta primera versión

Groq/`qwen3.8-27b` es un modelo de **imágenes**, no procesa PDF nativo
como sí hace Gemini (`Part.from_bytes(mime_type="application/pdf")`). Si
el documento que se está procesando es un PDF, `groq_client.py`
**rasteriza solo la primera página** a PNG con PyMuPDF antes de
enviarla. Para esta primera versión funcional (MF-19) es una limitación
aceptada y documentada: un PDF de varias páginas pierde el contenido de
las páginas 2 en adelante si el fallback llega a activarse justo en ese
documento. Los documentos de imagen (JPG/PNG) no tienen esta limitación.
Queda para una iteración futura (fuera del alcance de MF-19) enviar
varias páginas o resumir el documento completo antes de rasterizar.

## Diseño

### Regla central: qué SÍ y qué NO dispara el fallback

| Dispara el fallback (fallo técnico) | NO dispara el fallback (problema de contenido) |
|---|---|
| Error 429 (cuota) | Baja confianza (`score_confianza_clasificacion` bajo) |
| Error 5xx / indisponibilidad | Documento ambiguo o con datos inconsistentes |
| Timeout / error de conexión | `NO_CLASIFICADO` cuando el LLM respondió y decidió eso |
| Respuesta vacía por bloqueo de seguridad | — |

Esta distinción vive en `app/services/errores_llm.py`
(`ErrorTecnicoProveedor`). Cualquier respuesta **válida** del modelo
(incluida una de baja confianza o `NO_CLASIFICADO`) se acepta tal cual,
sin reintentar ni tocar el fallback.

Matiz importante: una respuesta que **no cumple el schema** (JSON
inválido) no es baja confianza ni ambigüedad; el agente la reintenta
hasta `MAX_INTENTOS` con el mismo modelo y, si persiste, escala al
fallback (igual que el Extractor de MF-06). Un error de configuración
(por ejemplo, falta la API key) también termina agotando los intentos. Antes vivía dentro de `extractor.py` (MF-06); se movió a un
módulo compartido para que también la use `classifier.py` sin que un
agente tenga que importar del otro.

### Clasificador (`app/agents/classifier.py`)

No tenía ningún manejo de fallos antes de MF-19. Ahora:

1. Hasta `MAX_INTENTOS` (3) intentos con Gemini (principal).
2. Si todos fallan por `ErrorTecnicoProveedor`, y hay un
   `generador_fallback` configurado (función `(documento, prompt) ->
   Classification`, no un nombre de modelo — así no importa si el
   secundario es otro modelo de Gemini, Groq, o lo que el equipo decida
   después), hasta 3 intentos más con el secundario.
3. Si ambos agotan sus intentos: **no se lanza excepción**. Se devuelve
   una `Classification` degradada (`tipo_documento=NO_CLASIFICADO`,
   `score_confianza_clasificacion=0.0`, con el motivo técnico en
   `justificacion`) para que el flujo la mande a revisión humana en vez
   de presentarla como un resultado exitoso.

#### Fallo total: nunca se presenta como exitoso

Cuando Gemini y Groq fallan, `nodo_clasificador` (`app/graph/graph.py`)
detecta la salida degradada, escribe el motivo en
`state["fallos_tecnicos"]` y la validación final devuelve
`validacion_ok = False` con ese motivo en `errores_validacion`. Además
se omite el Extractor (sin clasificación no hay tipo de documento que
extraer) y el error queda registrado también en el log
(`mediflow.app.agents.classifier`, nivel ERROR). Una clasificación
`NO_CLASIFICADO` con baja confianza devuelta por un modelo que sí
respondió **no** se considera fallo técnico y sigue su curso normal.

Lo mismo aplica al **Extractor**: si Gemini y Groq fallan, `extractor.py`
devuelve una extracción vacía con una observación fija ("No fue posible
obtener una extracción válida del LLM…"). `nodo_extractor` la reconoce,
registra el motivo en `state["fallos_tecnicos"]` y la validación final
devuelve `validacion_ok = False`. Una extracción incompleta devuelta por
un modelo que sí respondió (datos que el documento no trae) **no** es
fallo técnico: sigue por validación, confianza y HITL. Los tests
`tests/test_mf19_fallo_total.py` y `tests/test_mf19_extractor_fallo_total.py`
verifican ambos casos y que el detector del grafo coincida con el texto
que producen los agentes.

### Extractor (`app/agents/extractor.py`)

Ya tenía el mecanismo de MF-06 (`proveedor_fallback: ProveedorLLM |
None`), pero nunca quedó conectado en el grafo. MF-19 lo conecta (ver
abajo) y agrega `ProveedorGroq` (`app/services/groq_client.py`), que
implementa el mismo protocolo `ProveedorLLM` que ya usa `ProveedorGemini`
— el Extractor no sabe ni le importa con qué proveedor está hablando.

De paso se corrigió un bug preexistente (de MF-06, no de MF-19): el
método `generar` de `ProveedorLLM` estaba sin indentar y quedaba fuera
de la clase `Protocol`, anulando el chequeo de tipos de esa interfaz
(sin afectar el comportamiento en tiempo de ejecución, porque Python no
valida un `Protocol` salvo con `@runtime_checkable`).

### Grafo (`app/graph/graph.py`)

Conecta el fallback en los dos nodos, leyendo `GROQ_API_KEY` del
entorno. **Sin esa variable, el fallback simplemente no se activa** y
todo funciona igual que antes de MF-19 (solo reintentos + degradación
controlada) — así cualquiera puede correr el proyecto sin tener cuenta
de Groq.

## Cómo probarlo en local

```bash
cp .env.example .env
# completar GEMINI_CLASSIFIER_API_KEY / GEMINI_EXTRACTOR_API_KEY como siempre
# y, para activar el fallback de verdad:
# GROQ_API_KEY=<tu key gratuita de https://console.groq.com/keys>

pytest -q                                    # toda la suite
pytest -q tests/test_groq_client.py          # solo Groq
pytest -q tests/test_classifier.py -k Fallback
pytest -q tests/test_graph.py -k MF19
```

## Pruebas realizadas

Todas son pruebas controladas y automatizadas (no requieren credenciales
reales de Gemini ni de Groq: se reemplazan los clientes HTTP por dobles
de prueba, así son deterministas y no consumen cuota). **65/65 en
verde** (59 de la implementación de MF-19 + 6 del grafo para el fallo total), `ruff check .` sin deuda nueva sobre `develop`. Se verificaron
además con *mutation testing* manual (desactivar a propósito cada pieza
del mecanismo — la traducción de errores, el salto al fallback, el
cableado en el grafo, la rasterización del PDF — y confirmar que la
prueba correspondiente sí falla), para asegurar que las pruebas
realmente detectan una regresión y no solo pasan en falso.

| Archivo | Qué valida |
|---|---|
| `tests/test_classifier.py` (`TestFallbackTecnicoClasificador`) | Fallo técnico → reintentos → fallback → recuperación; sin `generador_fallback` configurado → reintentos → degradación; ambos fallan → no lanza excepción, no se presenta como éxito; **baja confianza/ambigüedad NO dispara el fallback**; JSON inválido reintenta con el mismo modelo antes de escalar; `classifier_node` propaga el fallback |
| `tests/test_extractor.py` | Mecanismo de fallback ya existente de MF-06 (reintentos, fallback, degradación) |
| `tests/test_gemini_client.py` | Traducción de errores reales de Gemini (429/5xx/timeout/respuesta vacía) a `ErrorTecnicoProveedor`, sin confundir un JSON inválido (problema de contenido) con un fallo técnico |
| `tests/test_groq_client.py` | Traducción de errores de Groq (429/5xx/timeout/respuesta vacía); `ProveedorGroq` cumple el protocolo del Extractor, incluida una integración real con `extraer_datos_clinicos`; modo estricto (`strict: true`) del Clasificador — schema, respuesta válida, respuesta que no cumple el schema; rasterización de PDF a imagen (con un PDF real generado con PyMuPDF) y el límite de 20 MB por imagen |
| `tests/test_mf19_fallo_total.py` | Si fallan el principal y el fallback del **Clasificador**, el grafo devuelve `validacion_ok = False` con el motivo y no ejecuta el Extractor; una clasificación ambigua de un LLM que sí respondió **no** es fallo técnico; el detector del grafo coincide con la salida degradada real del Clasificador |
| `tests/test_mf19_extractor_fallo_total.py` | Lo mismo para el **Extractor**: fallo total → `validacion_ok = False`; extracción incompleta de un LLM que sí respondió → sigue el flujo normal; el detector coincide con `_extraccion_vacia` |
| `tests/test_graph.py` (`TestCableadoDelFallbackMF19`) | Sin `GROQ_API_KEY` → el grafo NO conecta ningún fallback; con la key → se conecta en los dos agentes con los parámetros correctos |

### Documentos utilizados para la validación

- `samples/ejemplo_receta_medica.txt` — caso de clasificación válida
  (recuperación con fallback y reintentos).
- `samples/ejemplo_informe_radiologico.txt` — referencia del caso de baja
  confianza/ambigüedad. En las pruebas automáticas la respuesta del LLM se
  simula para verificar que el fallback **no** se activa; este archivo no
  se usó en las corridas reales descritas más abajo.
- Un PDF real de una página generado en la propia prueba con PyMuPDF
  (`tests/test_groq_client.py::_pdf_de_prueba`), para la rasterización
  del fallback de Groq.

### Resultados del smoke test con credenciales reales

Fecha: 30/09/2026 · Documento: `samples/ejemplo_receta_medica.txt` (texto) ·
Flujo completo (`grafo_mediflow`) · Modelo de fallback: `qwen/qwen3.8-27b`
(estado *Preview* en la documentación de Groq: puede cambiar o retirarse).

El fallo técnico del modelo principal se forzó usando API keys de Gemini
inválidas solo en el proceso de prueba (HTTP 400 `API_KEY_INVALID`); el
script de prueba no se versiona y no escribe ninguna clave en disco.

| Escenario | Qué se forzó | Resultado observado |
|---|---|---|
| **A** | Gemini falla; Groq real | Gemini falló 3/3 intentos en cada agente; Groq respondió `200 OK` en ambos. Clasificación `RECETA_MEDICA` (score 0.98, Medicina General) y extracción válida (paciente "Ana Torres", 1 diagnóstico). `validacion_ok = True`. Tiempo total: 9,7 s |
| **B** | Gemini y Groq fallan en el Clasificador | Gemini 3/3 y Groq 3/3 (HTTP 401). Se registró `ERROR` en el log del Clasificador; `validacion_ok = False`, con el motivo en `errores_validacion` y `fallos_tecnicos`. El Extractor no se ejecutó |
| **C** | Clasificador OK vía Groq; Extractor falla en Gemini y en Groq (modelo inexistente, HTTP 404) | Se registró `ERROR` en el log del Extractor; `validacion_ok = False` con el motivo `Extractor: fallaron el modelo principal y el fallback` |

Con esto se comprobó con servicios reales: que el fallback se activa solo
ante fallos técnicos, que respeta los contratos de salida (Groq devolvió
objetos válidos con el schema estricto y `reasoning_effort="none"`), y que
un fallo total no se marca como exitoso y queda registrado.

### Límites de lo verificado y recomendaciones para MF-20

- Las corridas reales usaron un documento de **texto**. La ruta de
  **PDF/imagen** del fallback (rasterización de la primera página y envío
  a Groq como imagen) está cubierta por pruebas automáticas, pero no se
  ejecutó contra la API real de Groq.
- No se hizo una corrida de control con una API key válida de Gemini
  (todo real, sin fallo forzado) ni con `ejemplo_informe_radiologico.txt`.
- Límites del plan gratuito de Groq para este modelo: 30 req/min,
  1.000 req/día, 8.000 tokens/min y 200.000 tokens/día; cada imagen
  consume del orden de 2.048 tokens. Al ser un modelo *Preview*, conviene
  repetir el smoke test antes de un despliegue real.
- `errores_validacion` y `fallos_tecnicos` guardan el detalle completo de
  cada intento fallido, que puede ser muy largo. Para los registros de
  MF-15 conviene resumirlo.
- El comentario de `app/services/gemini_provider.py` sobre
  `GEMINI_API_KEY` está desactualizado: el Extractor lee
  `GEMINI_EXTRACTOR_API_KEY`.
