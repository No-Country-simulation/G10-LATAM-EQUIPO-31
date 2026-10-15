# MF-25 – Revisar derivación del caso estándar a HITL
**Rama:** `feature/MF-25-derivacion-estandar-hitl`

## 1. Conclusión
Se identificaron **dos causas distintas** por las que documentos esperados como estándar terminan en revisión humana:

| | Documentos | Causa | ¿Defecto? |
|---|---|---|---|
| A | `caso-estandar.pdf` | El clasificador tipó el alta médica de una persona con una fractura como "Orden de Solicitud de Procedimiento". La matriz de MF-21 exige procedimientos en una orden y el documento no los trae | La derivación es coherente con las reglas; el origen está en la clasificación |
| B | `p11.jpg`, `p27.jpg`, `p30.png`, `p9.jpg` | Son órdenes que solicitan **estudios** (laboratorio). El extractor los coloca en `estudios_solicitados` y la matriz solo exigía `procedimientos_solicitados` | **Sí**: la matriz era más estricta que la definición de orden del clasificador. Corregido en esta actividad |

Los otros dos documentos derivados a HITL del grupo analizado (`p16.pdf` y `p20.pdf`) no traen ni estudios ni procedimientos, y la derivación es correcta: `p16.pdf` declara en su propio texto que sus datos son "intencionalmente contradictorios", y `p20.pdf` es una indicación pediátrica sintomática más que una orden.

**Corrección aplicada:** en `app/graph/confianza.py`, para una orden de solicitud de procedimiento, `estudios_solicitados` cubre a `procedimientos_solicitados`. Se validó con 12 pruebas automáticas nuevas (sin modelo) y con la suite completa: 354 pruebas aprobadas. El routing no se modificó.

## 2. Reproducción (tarea 1)
Se ejecutó el flujo real (`grafo_mediflow`) sobre `docs/assets/mf-16/caso-estandar.pdf` con la misma preparación de entrada que `routes.py`. Resultado: `destino_principal = revision_humana`, confianza Media, score 0.93, sin departamento.

## 3. Datos extraídos y clasificación (tarea 2)

### 3.1 `caso-estandar.pdf`
| Campo | Valor |
|---|---|
| Contenido real | Alta médica de una persona con una fractura (revisión manual) |
| Tipo asignado | Orden de Solicitud de Procedimiento |
| Prioridad del clasificador | Alta |
| Nivel de urgencia del extractor | `no_urgente` |
| Diagnósticos / medicamentos / estudios / procedimientos | 1 / 0 / 0 / 0 |
| Observaciones del extractor | "Alta inmediata sin restricciones, Autorización para actividad física de alto impacto mañana" |

### 3.2 Seis documentos de `mf-16` derivados a HITL por el motivo `procedimientos_solicitados`
Todos clasificados como "Orden de Solicitud de Procedimiento":

| Archivo | Medicamentos | Estudios | Procedimientos | Lectura |
|---|---|---|---|---|
| `p11.jpg` | 1 | 1 | 0 | Orden de laboratorio y control; documento de prueba de legibilidad |
| `p16.pdf` | 0 | 0 | 0 | Declara datos contradictorios; HITL correcto |
| `p20.pdf` | 0 | 0 | 0 | Indicación pediátrica sintomática; HITL correcto |
| `p27.jpg` | 1 | 1 | 0 | Orden de laboratorio y tratamiento |
| `p30.png` | 0 | 1 | 0 | Orden de TSH y T4 libre. En una corrida anterior el extractor la devolvió con 1 procedimiento |
| `p9.jpg` | 1 | 1 | 0 | Orden de laboratorio y tratamiento (gastritis) |

El caso de `p30.png` muestra que el extractor coloca el mismo tipo de ítem unas veces en procedimientos y otras en estudios, de modo que, sin la corrección, el mismo documento pasaba o iba a HITL según la corrida.

## 4. Inconsistencias y confianza (tarea 3)
En `caso-estandar.pdf`: inconsistencias vacías, `motivos_confianza = ['procedimientos_solicitados']`, score 0.93, categoría Media. En los demás documentos del grupo B, el único motivo era también `procedimientos_solicitados`.

## 5. Reglas que determinan la derivación (tarea 4)
* **Confianza (`confianza.py`, MF-10 y MF-21).** Cada tipo documental tiene entidades críticas; para una orden, `procedimientos_solicitados`. Una entidad crítica faltante resta 0.10 al score de reglas y degrada la categoría de Alta a Media cuando el score es mayor o igual a 0.80.
* **Routing (`routing.py`, MF-11).** Una confianza Media o Baja deriva a revisión humana, independientemente de la urgencia.

Se reprodujo el cálculo con `confianza.py` sobre un estado equivalente al de `caso-estandar.pdf` (score del clasificador asumido en 0.96 para igualar el 0.93 observado):

| Tipo asignado | Categoría | Score | Motivo |
|---|---|---|---|
| Orden de Solicitud de Procedimiento | Media | 0.93 | `procedimientos_solicitados` |
| Epicrisis / Informe de Alta | Media | 0.93 | `medicamentos` |
| Certificado Médico | Alta | 0.98 | ninguno |
| Orden con 1 procedimiento | Alta | 0.98 | ninguno |

## 6. ¿Justificado o requiere corrección? (tarea 6)
* **Causa A:** justificado con las reglas actuales. El prompt del clasificador define "Epicrisis / Informe de Alta" y limita la orden a lo que "todavía no se realizó"; según esas definiciones, un informe de alta no corresponde a una orden. Se deja como seguimiento (sección 9).
* **Causa B:** defecto de la matriz. El prompt del clasificador define la orden como "solicitud de un estudio/procedimiento", pero la matriz solo aceptaba procedimientos. Requería corrección.

## 7. Ajustes aplicados (tarea 7)
**Cambio en `app/graph/confianza.py`** (aditivo): se añade `ENTIDADES_EQUIVALENTES`, que para el tipo "Orden de Solicitud de Procedimiento" hace que `estudios_solicitados` cubra a `procedimientos_solicitados`. Una orden sin estudios ni procedimientos sigue yendo a HITL. El cambio no afecta a los demás tipos.

**No se modificó `routing.py`.** No intervino en la derivación. Se registra una observación, sin acción: `_es_urgente` reconoce la prioridad del clasificador solo cuando es exactamente `"Urgente"`, mientras que en las ejecuciones el clasificador devolvió otros valores ("Emergencia", "Alta", "Media", "Prioritario"). Ningún caso real muestra una urgencia perdida (la de la receta urgente la detectó el extractor), y "Alta" es ambiguo (`caso-estandar.pdf` tuvo prioridad "Alta" y no es urgente), por lo que un ajuste ingenuo generaría alertas falsas.

## 8. Pruebas (tarea 8)

### 8.1 Flujo real, con tres corridas cada uno, antes del cambio
Ninguno de estos documentos es de tipo orden, por lo que la corrección no los afecta.

| Archivo | Destino | Departamento | Confianza |
|---|---|---|---|
| `samples/entradas/01_receta_medica.txt` | `estandar` | `farmacia_hospitalaria` | Alta |
| `samples/entradas/06_receta_medica.pdf` | `estandar` | `farmacia_hospitalaria` | Alta |
| `samples/entradas/05_certificado_medico.txt` | `estandar` | `historia_clinica_electronica` | Alta |
| `samples/entradas/02_informe_estudio.txt` | `urgente` | `cola_urgencias_medicas` | Alta |
| `samples/entradas/09_receta_inconsistente_hitl.txt` | `revision_humana` | sin departamento | Media |
| `docs/assets/mf-16/caso-ambiguo.pdf` | `revision_humana` | sin departamento | Media |

### 8.2 Pruebas automáticas (`tests/test_mf25_derivacion_hitl.py`, 12 pruebas, sin modelo)
* Siguen yendo a HITL: orden sin procedimientos ni estudios (aunque el score sea 0.93), epicrisis sin medicamentos (regla actual), receta sin medicamentos y orden urgente incompleta (conservando `urgente=True`).
* Siguen el flujo automático: un documento completo de cada uno de los cinco tipos (con su departamento), un certificado sin medicamentos y una orden que solicita estudios sin procedimientos (la corrección).
* Se comprobó que las pruebas detectan un cambio en la regla: al retirar la degradación por entidad crítica faltante, 4 de las 10 pruebas originales fallan. Con la corrección aplicada, la suite completa pasa sin fallos (354 pruebas aprobadas), incluidas las de MF-21.

## 9. Estado de los criterios de aceptación
| Criterio | Estado |
|---|---|
| Se identifica y documenta la causa de la derivación | Cumplido: dos causas (secciones 1, 3 y 5) |
| Se determina si corresponde a las reglas actuales o es un defecto | Cumplido (sección 6) |
| Si corresponde, se corrige la lógica y se valida mediante pruebas | Cumplido: corrección en `confianza.py`, validada con pruebas (secciones 7 y 8.2) |
| Se valida al menos un caso estándar adecuado | Cumplido (sección 8.1) |
| Los casos que requieren HITL siguen yendo a HITL | Cumplido: ejecución real (8.1) y pruebas automáticas (8.2) |
| Se registran evidencias | Cumplido (este documento) |

## 10. Limitaciones y seguimientos
* **Altas médicas tipadas como orden (causa A):** seguimiento propuesto para el clasificador. No se registra como issue en esta actividad.
* **Matriz de epicrisis (pregunta abierta):** una epicrisis sin medicamentos baja a Media y va a HITL. Si un alta sin medicación es válida, la matriz sería demasiado estricta, por tanto se mantiene la regla como está, abierta a futuras modificaciones.
* **Variabilidad del extractor:** el modelo no es 100 % determinista; los resultados de documentos concretos pueden variar entre corridas.

Los componentes mencionados en los seguimientos son una propuesta, no una asignación.

## 11. Alcance de estos hallazgos
La corrección reduce las derivaciones innecesarias a revisión humana de las órdenes que solicitan estudios y no cambia el resto del comportamiento. No impide los tres flujos del MVP (estándar, urgente y revisión humana), que se validaron con documentos estables. Las limitaciones de la sección 10 afectan a casos concretos.