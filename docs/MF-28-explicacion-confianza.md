# MF-28 — Explicación de la categoría de confianza en la consulta

Rama: `fix/MF-28-explicacion-confianza` · Base: `develop` (`6587ba1`, con el PR #67 integrado)

## 1. Objetivo y alcance

Atender la observación 8 de la revisión de MF-28: un puntaje de 0.93 aparece como «Alta» en un caso y «Media» en otro, y la pantalla no explica por qué.

**Fuera de alcance (deliberadamente):**

| No se hace | Motivo |
|---|---|
| Modificar `confianza.py` (MF-10 / MF-21) | La categoría se sigue calculando igual; solo se explica en pantalla |
| Modificar la API, el grafo o el panel HITL | El cambio es de presentación en la consulta |

## 2. Qué se cambió

| Archivo | Cambio |
|---|---|
| `frontend/consulta_resultados.py` | Función `categoria_degradada_a_media`, constante `UMBRAL_CONFIANZA_ALTA` (0,80) y nota explicativa en la consulta |
| `tests/test_consulta_resultados.py` | 4 pruebas nuevas; las 18 existentes no se modificaron |

## 3. Cómo funciona

Cuando el puntaje es igual o mayor a 0,80 y la categoría es Media, la consulta muestra una nota con el puntaje y el umbral de Alta. La nota explica que la categoría no pasa a Alta si hay errores de validación, inconsistencias o falta de medicamentos, diagnósticos, estudios o profesional, y remite a los motivos que se listan debajo.

Los datos del paciente que falten (nombre, fecha, sexo) solo restan puntaje y no cambian la categoría, por eso la nota no los menciona.

No aparece cuando la categoría es Alta, cuando el puntaje es menor a 0,80 o cuando no hay puntaje.

**Limitación:** el umbral está duplicado en el frontend y debe coincidir con `UMBRAL_ALTA` de `app/graph/confianza.py`. Una prueba lo comprueba: si el backend cambia el valor, esa prueba falla y avisa de que hay que actualizar la pantalla.

## 4. Qué se conserva

El resto de la pantalla de consulta no cambia: métricas, datos extraídos, campos no encontrados, motivos y línea de tiempo. Las 18 pruebas existentes del archivo pasan sin modificarse.

## 5. Pruebas automatizadas

`python -m pytest` → **342 pasan** (338 de `develop` + 4 nuevas), tras integrar `develop` con el PR #67.

| Prueba | Qué comprueba |
|---|---|
| `test_categoria_degradada_a_media_solo_cuando_el_puntaje_alcanza_el_umbral_de_alta` | Se detecta con 0,93 y 0,80 en Media; no con Alta, con 0,64 ni sin puntaje |
| `test_umbral_de_confianza_alta_coincide_con_el_backend` | El umbral del frontend es igual a `UMBRAL_ALTA` del backend |
| `test_ui_explica_por_que_la_categoria_es_media_con_puntaje_alto` | La pantalla muestra la nota con puntaje 0,93 y categoría Media |
| `test_ui_no_explica_la_categoria_cuando_no_hubo_degradacion` | No aparece con (0,93, Alta) ni con (0,64, Media) |

## 6. Evidencias

Carpeta `docs/assets/sprint-4/mf-28-interfaz-entrada/`:

| Escenario | Archivo | Estado |
|---|---|---|
| Consulta con categoría Media y puntaje ≥ 0,80 (nota visible) | [evidencia-consulta-explicacion-categoria.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-consulta-explicacion-categoria.png) | OK |
| Resultado de `pytest` (342 pasan) | [evidencia-verificacion-pytest-342.png](./assets/sprint-4/mf-28-interfaz-entrada/evidencia-verificacion-pytest-342.png) | OK |

La captura de la consulta corresponde al documento `PRUEBA-KATE-007` con la API y OCI reales, y la aportó @ksegovia81 durante la revisión. La captura de `pytest` es del entorno local.

## 7. Cómo probarlo

```powershell
python -m pytest -q
streamlit run frontend/mediflow.py
```

En **Consulta de resultados**, consulta un documento con puntaje 0.93 y categoría Media (el caso 007): debe verse la nota bajo las métricas. Con un documento de categoría Alta no debe aparecer.