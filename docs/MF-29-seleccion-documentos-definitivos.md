# MF-29 · Selección de tres documentos definitivos

MediFlow · Hackathon ONE G10 (equipo 31) · Elaborado por Katherine ([@ksegovia81](https://github.com/ksegovia81)) · 16/10/2026

Issue: #64 (MF-29). Relacionado con #62 (MF-26), MF-24, MF-25 y MF-34.

**Resumen:** la selección parte de la lista de Jennifer, confirmada por ella como la lista final (01, 02 y 09). Las pruebas por la API (sección 2) y por la interfaz (secciones 2b y 2c) confirman que el resultado se repite en 01, 02, 09 y 06.

Los documentos son los que están en `samples/entradas/` y `docs/assets/` del repositorio. Según el requisito del issue, deben ser sintéticos o anonimizados, sin datos personales reales.

Nota: con MF-34 ya integrado, la pantalla de Carga acepta .txt. Los .txt se probaron (a) por la API con el original, (b) por la interfaz con copias .md (14/10) y (c) por la interfaz con los archivos originales .txt, más un PDF y una imagen (15/10). Los tres métodos coinciden.

## 1. Candidatos

| Escenario | Archivo (samples/entradas/ salvo indicación) | Resultado de Jennifer | Observaciones |
|---|---|---|---|
| Estándar | 01_receta_medica.txt (interfaz: original y copia .md) | estandar · farmacia_hospitalaria · Alta 0.93 | Propuesta principal de Jennifer. |
| Urgente | 02_informe_estudio.txt (interfaz: original y copia .md) | urgente · cola_urgencias_medicas · 2 señales · alerta Slack/correo OK | Propuesta principal de Jennifer. |
| HITL | 09_receta_inconsistente_hitl.txt (interfaz: original y copia .md) | revision_humana por inconsistencia (Media 0.85) | Propuesta principal de Jennifer. |
| Estándar (alt.) | 06_receta_medica.pdf | Igual que 01, en PDF | Se sube por la interfaz sin cambios. |
| HITL (alt.) | docs/assets/mf-16/caso-ambiguo.pdf | revision_humana por la misma inconsistencia | Se sube por la interfaz sin cambios. |
| Urgente + HITL | 07_informe_estudio.png | urgente=True pero revision_humana (Media 0.88) | Ilustra la precedencia; no es un urgente «limpio». |
| Estándar (alt.) | 05_certificado_medico.txt | historia_clinica_electronica | Alternativa de Jennifer; es .txt. |
| Urgente (alt.) | docs/assets/sprint-4/mf-24/07_urgente_receta_mf24.txt | Jennifer: urgente · Alta 1.0 · 3 señales. Interfaz (15/10): urgente, emergencia, Alta 1.0, 3 señales | Ya está en el repositorio. Alternativa de urgente. |
| NO USAR | caso-estandar.pdf | Se clasifica como Orden y va a HITL | Según Jennifer. |
| NO USAR | caso-urgente.png | No detecta la urgencia | Según Jennifer (bug nuevo). |
| NO USAR | p10.jpg | Contradictorio, pasa como estándar | Según Jennifer (bug nuevo). |

## 2. Resultados por la API (19 corridas, 14/10/2026)

Corridas hechas por Katherine con el original (.txt, .pdf, .png) vía POST /documentos, canal_origen = MF29_Prueba. Todas devolvieron HTTP 200, sin errores.

| Caso | Corrida | documento_id | Estado | Urgencia | Confianza | Destino | Departamento | Señales / Obs. | ¿Coincide con Jennifer? |
|---|---|---|---|---|---|---|---|---|---|
| 01 estándar (.txt) | 1 | MF29-EST-A1 | estandar | No | Alta 0.93 | estandar | farmacia_hospitalaria | — | Sí |
| 01 estándar (.txt) | 2 | MF29-EST-A2 | estandar | No | Alta 0.93 | estandar | farmacia_hospitalaria | — | Sí |
| 01 estándar (.txt) | 3 | MF29-EST-A3 | estandar | No | Alta 0.93 | estandar | farmacia_hospitalaria | — | Sí |
| 02 urgente (.txt) | 1 | MF29-URG-A1 | urgente | Sí | Alta 0.93 | urgente | cola_urgencias_medicas | 2 señales (texto varía levemente) | Sí |
| 02 urgente (.txt) | 2 | MF29-URG-A2 | urgente | Sí | Alta 0.93 | urgente | cola_urgencias_medicas | 2 señales (texto varía levemente) | Sí |
| 02 urgente (.txt) | 3 | MF29-URG-A3 | urgente | Sí | Alta 0.93 | urgente | cola_urgencias_medicas | 2 señales (texto varía levemente) | Sí |
| 09 HITL (.txt) | 1 | MF29-HITL-A1 | revision_humana | No | Media 0.85 | revision_humana | — | Inconsistencia | Sí |
| 09 HITL (.txt) | 2 | MF29-HITL-A2 | revision_humana | No | Media 0.85 | revision_humana | — | Inconsistencia | Sí |
| 09 HITL (.txt) | 3 | MF29-HITL-A3 | revision_humana | No | Media 0.85 | revision_humana | — | Inconsistencia | Sí |
| 06 estándar (PDF) | 1 | MF29-ALT-06-1 | estandar | No | Alta 0.93 | estandar | farmacia_hospitalaria | — | Sí |
| 06 estándar (PDF) | 2 | MF29-ALT-06-2 | estandar | No | Alta 0.93 | estandar | farmacia_hospitalaria | — | Sí |
| 06 estándar (PDF) | 3 | MF29-ALT-06-3 | estandar | No | Alta 0.93 | estandar | farmacia_hospitalaria | — | Sí |
| caso-ambiguo.pdf | 1 | MF29-ALT-AMB-1 | revision_humana | No | Media 0.93 | revision_humana | — | «Urgencia: no urgente.» | Sí (destino); el puntaje varía |
| caso-ambiguo.pdf | 2 | MF29-ALT-AMB-2 | revision_humana | No | Media 0.88 | revision_humana | — | «Urgencia: no urgente.» | Sí (destino); el puntaje varía |
| caso-ambiguo.pdf | 3 | MF29-ALT-AMB-3 | revision_humana | No | Media 0.93 | revision_humana | — | «Urgencia: no urgente.» | Sí (destino); el puntaje varía |
| 07 png | 1 | MF29-ALT-07-1 | urgente | Sí | Alta 0.93 | urgente | cola_urgencias_medicas | PRIORIDAD: URGENTE; defecto de llenado | No (corrida atípica) |
| 07 png | 2 | MF29-ALT-07-2 | revision_humana | Sí | Media 0.88 | revision_humana | — | PRIORIDAD: URGENTE; defecto de llenado | Sí |
| 07 png | 3 | MF29-ALT-07-3 | revision_humana | Sí | Media 0.88 | revision_humana | — | PRIORIDAD: URGENTE; defecto de llenado | Sí |
| 07 png | 4 | MF29-ALT-07-4 | revision_humana | Sí | Media 0.88 | revision_humana | — | PRIORIDAD: URGENTE; defecto de llenado | Sí |

**Resumen:** 01, 02, 09 y 06 dieron lo mismo en las 3 corridas y coinciden con Jennifer. caso-ambiguo.pdf: mismo destino siempre, pero el puntaje varía (0.93 / 0.88 / 0.93). 07 png: 3 de 4 corridas coinciden; la primera fue distinta (urgente directo, Alta 0.93).

## 2b. Resultados por la interfaz con copias .md (14/10/2026)

Pantalla Carga con las copias .md (copias .md del mismo texto de los .txt). Datos de «Consulta de resultados». Equivalencia de nombres: la API dice estandar / urgente / revision_humana; la pantalla dice Automático / Alerta urgente / Auditoría humana.

| Caso | documento_id | Estado | Urgencia | Confianza | Destino | Departamento | Señales / Obs. | ¿Coincide con la API? |
|---|---|---|---|---|---|---|---|---|
| 01 estándar (.md) | MF29-EST-I1 | Procesado automáticamente (estandar) | no_urgente | 0.93 · Alta | Automático | farmacia_hospitalaria | — | Sí |
| 02 urgente (.md) | MF29-URG-I1 | Alerta urgente (urgente) | urgente | 0.93 · Alta | Alerta urgente | No visible en pantalla (API: cola_urgencias_medicas) | 2 señales: «Tromboembolismo pulmonar agudo»; «defecto de llenado en arterias pulmonares segmentarias…» | Sí |
| 09 HITL (.md) | MF29-HITL-I1 | Pendiente de revisión humana | no_urgente | 0.85 · Media | Auditoría humana | — | Motivo: «Receta Medica pero incluye estudios complejos». Aparece en la pantalla Revisión humana. | Sí |

## 2c. Resultados por la interfaz con archivos originales (15/10/2026)

Pantalla Carga con los archivos originales (.txt, .pdf, .jpg), una corrida cada uno. Datos leídos de `GET /documentos/{id}/historial`.

| Caso | documento_id | Estado | Urgencia | Confianza | Destino | Departamento | Señales / Obs. | Tipo archivo (API) | ¿Coincide? |
|---|---|---|---|---|---|---|---|---|---|
| 01 estándar (.txt) | MF29-U-01 | estandar | no_urgente | Alta 0.93 | estandar | farmacia_hospitalaria | — | JSON | Sí |
| 02 urgente (.txt) | MF29-U-02 | urgente | urgente | Alta 0.93 | urgente | cola_urgencias_medicas | 1 señal (verificada en el JSON): defecto de llenado en arterias pulmonares, compatible con TEP agudo | JSON | Sí |
| 09 HITL (.txt) | MF29-U-09 | revision_humana | no_urgente | Media 0.85 | revision_humana | — | Inconsistencia: «Receta Medica pero incluye estudios complejos» | JSON | Sí |
| 07 MF-24 (.txt) | MF29-U-07MF24 | urgente | emergencia | Alta 1.0 | urgente | cola_urgencias_medicas | PA 220/130 mmHg; cefalea intensa y visión borrosa; dolor torácico opresivo | JSON | Sí (Jennifer: urgente, Alta 1.0, 3 señales) |
| 06 estándar (PDF) | MF29-U-06PDF | estandar | no_urgente | Alta 0.93 | estandar | farmacia_hospitalaria | — | PDF | Sí (igual que 01) |
| 08 orden (JPG) | MF29-U-08JPG | estandar | no_urgente | Alta 0.93 | estandar | auditoria_autorizaciones | — | Imagen | Sin resultado previo; dato nuevo |

**Resumen:** los 6 resultados coinciden con la API y con Jennifer. Se muestran los tres formatos (texto, PDF, imagen).

Sobre el tipo de archivo: los `.txt` figuran como «JSON» en el campo `tipo_archivo` de la API (`GET /documentos/{id}/historial`). Es una limitación conocida de MF-28, no un error nuevo. En la pantalla de Carga, el resultado de un `.txt` muestra `tipo_contenido: text/plain`.

## 3. Criterio de elección

- Mismo resultado en las 3 corridas.
- Coincide con lo que dice Jennifer y con lo esperado del escenario.
- Confianza, destino y señales se pueden ver (en la pantalla o en los datos técnicos).
- Se puede subir por la pantalla de Carga (JPG, PNG, PDF, JSON, Markdown o TXT).
- El archivo está en el repositorio, para que cualquiera repita la prueba.

## 4. Elección final

| Escenario | Documento elegido | Formato / vía | Resultado esperado | Estabilidad |
|---|---|---|---|---|
| Estándar | `01_receta_medica.txt` | Texto (.txt) | estandar · farmacia_hospitalaria · Alta 0.93 | API 3/3 · interfaz .md 1/1 · interfaz original 1/1 |
| Urgente | `02_informe_estudio.txt` | Texto (.txt) | urgente · cola_urgencias_medicas · señales de TEP agudo | API 3/3 · interfaz .md 1/1 · interfaz original 1/1 |
| Ambiguo / HITL | `09_receta_inconsistente_hitl.txt` | Texto (.txt) | revision_humana · Media 0.85 | API 3/3 · interfaz .md 1/1 · interfaz original 1/1 |

Formatos demostrados por la interfaz: texto (.txt, 01/02/09), PDF (06_receta_medica.pdf, igual que 01) e imagen (08_orden_procedimiento.jpg).

## 5. Cumplimiento de los criterios de aceptación (issue #64)

| Criterio | Estado |
|---|---|
| Tres documentos definitivos: estándar, urgente y ambiguo/HITL | Cumplido: 01, 02 y 09 |
| Considera los hallazgos y correcciones de MF-24 y MF-25 | Cumplido: se usó 07 de MF-24 como alternativa urgente, y se mantiene 09 para HITL |
| Recorridos completos validados en el MVP integrado | Cumplido: 19 corridas por la API y 9 por la interfaz |
| Resultados consistentes y reproducibles | Cumplido en 01, 02 y 09 (3 corridas iguales por la API) |
| Resultados esperados y evidencias documentados | Cumplido en este documento (secciones 2, 2b y 2c) |
| Documentos identificados y disponibles para la demo | Cumplido: rutas indicadas en la sección 1 |

## 6. Pendientes y observaciones para el equipo

- Equipo: la pantalla de Consulta no muestra el departamento_destino de los urgentes (solo «ruta a cola de emergencia»), y las señales de gravedad solo se ven en «datos técnicos (JSON)». ¿Se deja así?
- Equipo: la cantidad de señales de gravedad del 02 varía entre corridas (2 por API y en la interfaz con .md; 1 en la interfaz con el original); el resultado (urgente, Alta 0.93, cola_urgencias_medicas) no cambia.
- Equipo: revisar la variación del PNG 07 y del puntaje del caso ambiguo; «Urgencia: no urgente.» aparece como señal de gravedad en caso-ambiguo.pdf.
- Limpieza del bucket de las pruebas `MF29-*` y `PRUEBA-KATE-*`: autorizada por Kimberlyn para después de la demo, conservando las evidencias y sin afectar otros documentos.
