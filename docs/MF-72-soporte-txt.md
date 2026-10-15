# MF-34 (issue #72) — Soporte de archivos .txt en la carga

> Nota: este trabajo corresponde al ticket MF-34 (issue #72). El nombre de este archivo, la carpeta de evidencias y el ID de prueba conservan el prefijo «MF-72» por una confusión inicial de nomenclatura.

Rama: `feature/MF-34-soporte-txt-carga` · Base: `develop` (`b5f991a`) · Issue: #72 · PR: #74

## 1. Objetivo y alcance

Habilitar la carga de archivos `.txt` en la pantalla «Enviar documento» (MF-28), para que se procesen por el flujo existente de clasificación, extracción y enrutamiento.

| Requisito del issue | Estado |
|---|---|
| La interfaz permite seleccionar y cargar `.txt` | Hecho (§3) |
| Los `.txt` se envían al backend como texto plano | Hecho (§3); la API los acepta con agentes simulados (§5) y con OCI real (§8) |
| El contenido se procesa por el flujo habitual con el clasificador real | Hecho: verificado con OCI real por @ksegovia81 (§8) |
| Se mantienen los formatos previamente soportados | Comprobado (§4, §5) |
| Pruebas ejecutadas y documentadas | Hecho (§5, §6, §8) |

**Fuera de alcance (deliberadamente):**

| No se hace | Motivo |
|---|---|
| Modificar el backend, el grafo, los agentes, OCI o la persistencia | Este ticket solo cambia la interfaz de carga |
| Cambiar reglas de clasificación, urgencia o enrutamiento | Lo pide el alcance del issue |
| Corregir el `tipo_archivo` que el backend asigna a los textos | Ver limitación conocida (§4) |

## 2. Qué se cambió

| Archivo | Cambio |
|---|---|
| `frontend/carga_archivos.py` | Nueva entrada `"txt": ("TXT", "text/plain")` en `FORMATOS`; `LISTA_FORMATOS`, docstring y comentario de tipo incluyen TXT; el `.txt` entra en el bloque que valida UTF-8 y contenido no vacío |
| `tests/test_carga_archivos.py` | 8 pruebas nuevas (7 de validación y 1 de contrato con la API); se actualizaron 3 comprobaciones de la lista de formatos y se retiró `nota.txt` de los ejemplos de formato inválido |
| `docs/MF-28-interfaz-amigable-de-entrada.md` | Lista de formatos actualizada |

## 3. Cómo funciona ahora

- El formato se deduce de la extensión, como antes. `.txt` viaja a la API como `text/plain`, igual que JSON y Markdown (el backend acepta `text/*`; `application/json` daría 415).
- Un `.txt` pasa por la misma validación que JSON y Markdown: debe estar en UTF-8 (se admite BOM) y no estar vacío ni solo con espacios.
- Un `.txt` **no** se valida como JSON: el texto `{esto no es json}` se acepta si el archivo es `.txt`.
- Los avisos de formato no válido y el pie del cargador listan TXT.

## 4. Qué se conserva y limitación conocida

- JPG, JPEG, PNG, PDF, JSON, MD y MARKDOWN se aceptan y validan igual que antes. Un `.png` falso (texto renombrado) sigue rechazándose por contenido; `.docx`, `.exe`, `.csv` y similares siguen rechazándose.
- **Limitación conocida:** el backend etiqueta todo `text/*` como `tipo_archivo = "JSON"` (MF-28, línea 55), así que un `.txt` queda marcado como «JSON» en el documento guardado. @ksegovia81 reportó que así ocurrió en la verificación con OCI real (§8). No afecta al procesamiento y queda fuera del alcance porque no se modifica el backend.
- La captura `evidencia-carga-formato-no-valido.png` de MF-28 corresponde a la lista anterior (sin TXT) y no se reemplazó; la nueva está en §6.
- La regresión de los formatos previos (JPG, PNG, PDF, JSON y Markdown) se demuestra con las pruebas automáticas, incluida la prueba de contrato contra la API, y no con capturas de pantalla: los 342 casos existentes siguen pasando.

## 5. Pruebas automatizadas

`python -m pytest` → **349 pasan** (342 existentes + 7 netas), con `streamlit==1.64.0`. Línea base antes del cambio: 342 pasan.

| Prueba | Qué comprueba |
|---|---|
| `test_formatos_validos` (3 casos nuevos) | `.txt` válido en UTF-8, `.txt` con BOM y `.txt` con texto que no es JSON se aceptan con MIME `text/plain` |
| `test_txt_latin1_se_rechaza` | Un `.txt` en Latin-1 se rechaza |
| `test_txt_vacio_o_solo_espacios_se_rechaza` | `.txt` vacío o en blanco se rechaza |
| `test_png_falso_sigue_rechazandose` | Un texto renombrado a `.png` sigue rechazándose |
| `test_formatos_no_permitidos_siguen_rechazandose` | `.exe`, `.docx`, `.csv` y `.txt.exe` siguen rechazándose |
| `test_contrato_backend_acepta_cada_formato_permitido[a.txt]` | La API (agentes simulados y almacenamiento falso) acepta el `.txt` con `text/plain` y responde 200 `procesado`, sin 415 |

Ajustes a pruebas existentes: la lista de formatos esperada en el aviso incluye TXT, y `nota.txt` se retiró de los ejemplos de formato inválido porque ahora es válido.

## 6. Evidencias

Carpeta `docs/assets/sprint-4/mf-72-soporte-txt/`:

| Escenario | Archivo | Estado |
|---|---|---|
| Resultado de `pytest` (349 pasan) | [evidencia-tests-automatizados.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-tests-automatizados.png) | OK |
| Pantalla de Carga con TXT en el pie y la ayuda | [evidencia-carga-estado-inicial-con-txt.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-carga-estado-inicial-con-txt.png) | OK |
| `.txt` válido cargado | [evidencia-carga-txt-valido.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-carga-txt-valido.png) | OK |
| `.txt` con llaves aceptado (no se valida como JSON) | [evidencia-carga-txt-no-es-json.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-carga-txt-no-es-json.png) | OK |
| `.txt` vacío rechazado | [evidencia-carga-txt-vacio.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-carga-txt-vacio.png) | OK |
| `.txt` en Latin-1 rechazado | [evidencia-carga-txt-latin1.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-carga-txt-latin1.png) | OK |
| `.docx` rechazado, la lista incluye TXT | [evidencia-carga-docx-lista-con-txt.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-carga-docx-lista-con-txt.png) | OK |
| Envío real del `.txt` (OCI), aportado por @ksegovia81 | [evidencia-oci-carga-txt-kate.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-oci-carga-txt-kate.png) | OK |
| Resultado del `.txt` en Consulta (OCI), aportado por @ksegovia81 | [evidencia-oci-consulta-txt-kate.png](./assets/sprint-4/mf-72-soporte-txt/evidencia-oci-consulta-txt-kate.png) | OK |

Los archivos de prueba usan datos ficticios.

## 7. Cómo probarlo

```powershell
python -m pytest -q
streamlit run frontend/mediflow.py
```

En **Carga**, sube un `.txt` en UTF-8 con una nota de ejemplo (por ejemplo, `samples/entradas/01_receta_medica.txt`): debe cargarse y poder enviarse. Con un `.txt` vacío debe verse el aviso de contenido vacío; con uno en Latin-1, el aviso de UTF-8; con un `.docx`, «formato no válido» con TXT en la lista. Sube un `.md`, un `.pdf` y una imagen para confirmar que nada cambió.

## 8. Verificación con OCI real

La prueba de contrato (§5) demuestra que la API acepta el `.txt` con agentes simulados y almacenamiento falso. La verificación con el clasificador real en OCI la ejecutó @ksegovia81 sobre el PR #74, con credenciales de OCI, igual que en MF-33.

| Dato | Resultado |
|---|---|
| Archivo probado | `samples/entradas/01_receta_medica.txt` (ya estaba en el repo) |
| ID del documento | `MF72-TXT-001` |
| Carga | La pantalla de Carga aceptó el `.txt` y lo procesó correctamente |
| Clasificación | Tipo de documento: Receta Médica |
| Urgencia | `no_urgente` (ruta estándar) |
| Confianza final | 0.93 · Alta |
| Enrutamiento | Procesado automáticamente; departamento sugerido: `farmacia_hospitalaria` |
| `tipo_archivo` guardado | «JSON» (reportado por @ksegovia81; limitación conocida de MF-28, línea 55, ver §4) |

Con esto, el `.txt` recorre clasificación, extracción y enrutamiento con el clasificador real. Capturas en §6.

**Observaciones:**

- No se usó `nota_clinica.txt`, el archivo previsto inicialmente, porque no estaba versionado en el repo ni en el PR. La verificación se hizo con `01_receta_medica.txt`, que demuestra lo mismo: un `.txt` válido recorre el flujo completo.
- En Consulta aparecen «campos no encontrados» (tipo y número de documento del paciente, sexo y fecha del documento). Corresponde al contenido de esa receta de muestra y no tiene relación con el soporte de `.txt`.
- El valor `tipo_archivo = "JSON"` no se ve en las capturas (la respuesta JSON está colapsada); se documenta según lo reportado.
