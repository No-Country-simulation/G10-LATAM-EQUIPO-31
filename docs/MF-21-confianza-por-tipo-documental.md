# MF-21 – Criticidad de entidades por tipo documental

**Responsable:** Jennifer Silva
**Archivo principal:** `app/graph/confianza.py`
**Actividad relacionada:** MF-10 (evaluación de confianza). Este documento complementa a `docs/MF-10-criterio-confianza.md`.

## 1. Objetivo

Antes de MF-21, la evaluación de confianza penalizaba por igual la ausencia de cualquier entidad clínica, sin importar el tipo de documento. Eso castigaba documentos correctos: un certificado médico no necesita medicamentos, y no debería perder confianza por no traerlos.

MF-21 aplica la matriz de criticidad por tipo documental propuesta por Katherine: una entidad ausente solo penaliza si es crítica **para ese tipo de documento**.

## 2. Matriz de criticidad

| Entidad | Criticidad |
|---|---|
| `diagnosticos` | Siempre crítica, en todos los tipos |
| `profesional` | Siempre crítico, en todos los tipos |
| `medicamentos` | Crítica en Receta médica y Epicrisis / Informe de alta |
| `estudios_solicitados` | Crítica en Informe de estudio diagnóstico |
| `procedimientos_solicitados` | Crítica en Orden / solicitud de procedimiento |

Resumen por tipo documental (qué entidades de lista son críticas):

| Tipo documental | Entidades críticas |
|---|---|
| Receta médica | `diagnosticos`, `medicamentos` |
| Informe de estudio diagnóstico | `diagnosticos`, `estudios_solicitados` |
| Orden / solicitud de procedimiento | `diagnosticos`, `procedimientos_solicitados` |
| Epicrisis / Informe de alta | `diagnosticos`, `medicamentos` |
| Certificado médico | `diagnosticos` |
| Tipo desconocido (`NO_CLASIFICADO` u otro fuera de la matriz) | **Todas** (criterio conservador) |

Además, `profesional` se revisa siempre (ver sección 3).

## 3. Cómo se evalúa

### 3.1 Por atributo real, no por texto

Las entidades de lista (`diagnosticos`, `medicamentos`, `estudios_solicitados`, `procedimientos_solicitados`) se revisan directamente sobre el objeto `extraccion`: una lista vacía significa ausente. `profesional` se considera faltante si el objeto es `None` o no tiene `nombre_completo`.

**Por qué no se interpretan los strings de `campos_no_encontrados`:** el extractor solo sigue una convención fija ("entidad.subcampo" o "entidad") en los 4 campos que calcula por código. Lo que el LLM agregue por su cuenta no tiene ese contrato garantizado, así que depender de esos nombres haría la penalización frágil.

### 3.2 Sin doble penalización

Si el extractor o el LLM ya reportaron como texto plano alguna entidad que ahora se evalúa estructuralmente (por ejemplo, el string `"medicamentos"` o `"profesional"` dentro de `campos_no_encontrados`), ese string se descarta de la lista de texto. Así lo mismo no se penaliza dos veces.

### 3.3 Qué sigue evaluándose por texto

Los subcampos puntuales que no son entidades de lista ni `profesional` (por ejemplo `paciente.*`, `fecha`, `sexo`, `tipo_documento`, `numero_documento`) se siguen leyendo de `campos_no_encontrados`.

## 4. Penalizaciones y umbrales

El score final combina la autoevaluación del modelo y el score de reglas:

```
score_final = 0.5 × autoevaluación_modelo + 0.5 × score_reglas
```

El score de reglas parte de 1.0 y descuenta:

| Motivo | Descuento |
|---|---|
| Error de validación o inconsistencia de MF-09 | 0.10 c/u |
| Entidad de lista crítica ausente (según la matriz) | 0.10 c/u |
| `profesional` ausente | 0.10 |
| Campo de texto crítico ausente | 0.10 c/u |
| Campo de texto secundario ausente (`sexo`, `fecha`, `tipo_documento`, `numero_documento`) | 0.05 c/u, tope de 0.15 en conjunto |

Categorías: **Alta** si el score es ≥ 0.80, **Media** si es ≥ 0.50, **Baja** en otro caso.

### 4.1 Degradación de categoría

Una entidad crítica faltante (o `profesional` ausente) no solo resta score: también degrada la categoría de Alta a Media. Se corrigió así tras detectar que una receta sin medicamentos podía quedar con score alto y enrutarse como documento estándar, escondiendo que faltaba justo el dato que define a ese tipo de documento.

## 5. Ejemplos

| Caso | Resultado |
|---|---|
| Certificado médico sin medicamentos | No penaliza: la matriz no exige medicamentos para ese tipo |
| Receta médica sin medicamentos | Penaliza 0.10 y degrada la categoría Alta a Media |
| Informe de estudio sin estudios solicitados | Penaliza 0.10 y degrada la categoría |
| Documento de tipo desconocido con cualquier lista vacía | Penaliza (todo se trata como crítico) |

## 6. Impacto en pruebas existentes

El caso 7 de `tests/test_integracion_sprint2.py` (penalización combinada secundario + crítico) usaba `medicamentos` como campo crítico faltante en un Informe de estudio. Con MF-21, esa ausencia ya no penaliza (comportamiento esperado) y el score pasaba a 0.82 (Alta) en lugar de quedar por debajo de 0.80.

Se ajustó el test, no la lógica: ahora usa `paciente.nombre_completo` como campo crítico, y conserva su intención original (secundario −0.05 más crítico −0.10, para un score de reglas de 0.85 y un score final de 0.77, categoría Media, ruta `revision_humana`). Ese ajuste se registra en la rama de MF-23, donde vive la prueba de integración de MF-09, MF-10 y MF-11.

## 7. Evidencia de pruebas

- `tests/test_mf21_criticidad_por_tipo.py`: pruebas de la matriz.
- `tests/test_confianza.py`: pruebas del cálculo de confianza.
- Suite completa del proyecto: **190 passed**.

## 8. Limitaciones conocidas

- **Variantes de nombre en texto.** Solo se descartan de `campos_no_encontrados` los nombres exactos de las entidades de lista y `"profesional"`. Si el LLM escribe una variante (por ejemplo `"diagnostico"` en singular) y además la lista `diagnosticos` está vacía, esa ausencia se penaliza dos veces: una por la evaluación estructural y otra por el texto. No se corrigió para no ampliar el alcance de la actividad.
- **`paciente` no se evalúa estructuralmente.** Sus subcampos faltantes se penalizan solo si aparecen en `campos_no_encontrados`.
- **La matriz depende del tipo clasificado.** Si el clasificador asigna un tipo incorrecto, se aplica la criticidad de ese tipo. Por eso un tipo desconocido es conservador.