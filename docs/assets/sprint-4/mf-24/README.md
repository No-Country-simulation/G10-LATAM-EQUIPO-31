# Documentos sintéticos de prueba (MF-24)

Siete documentos **100 % ficticios** (nombres, documentos de identidad y matrículas inventados, sin relación con personas reales) para probar los tres flujos del MVP con el flujo real de MediFlow: estándar, urgente y revisión humana (HITL).

## Resultado validado

Cada documento se ejecutó **3 veces** con el flujo real (Gemini como proveedor principal) el 14/10/2026 y dio el mismo resultado en las tres corridas.

| Archivo | Flujo | `destino_principal` | `departamento_destino` | Confianza |
|---|---|---|---|---|
| `01_estandar_receta.txt` | Estándar | `estandar` | `farmacia_hospitalaria` | Alta |
| `02_estandar_orden_procedimiento.txt` | Estándar | `estandar` | `auditoria_autorizaciones` | Alta |
| `03_estandar_certificado.txt` | Estándar | `estandar` | `historia_clinica_electronica` | Alta |
| `04_urgente_epicrisis.txt` | Urgente | `urgente` | `cola_urgencias_medicas` | Alta |
| `05_revision_receta_con_estudios.txt` | HITL (inconsistencia) | `revision_humana` | sin departamento | Media |
| `06_revision_incompleto.txt` | HITL (datos faltantes) | `revision_humana` | sin departamento | Baja |
| `07_urgente_receta_mf24.txt` | Urgente (receta) | `urgente` | `cola_urgencias_medicas` | Alta |

## Qué cubre cada uno

- **01, 02, 03:** documentos completos y no urgentes de tres tipos (receta, orden de procedimiento, certificado), que siguen el flujo automático.
- **04:** epicrisis con emergencia declarada y datos completos.
- **07:** receta médica con condición de urgencia y señales de gravedad explícitas; con ella se verificó que la confianza y las señales llegan completas hasta la alerta de Slack y el correo (MF-24).
- **05:** receta que incluye estudios solicitados, lo que dispara la regla de inconsistencia de MF-09.
- **06:** nota ambigua y sin datos clave, que produce confianza Baja.

## Advertencias

- Los resultados dependen de un modelo de lenguaje, así que no son 100 % deterministas. Si un documento da un resultado distinto, repite la prueba 2 o 3 veces antes de considerarlo un error.
- Estos resultados corresponden a los archivos **tal como están**, incluidas las líneas de encabezado que indican que son ficticios y describen el caso. El modelo lee esas líneas: si se editan o se retiran, hay que volver a validar.
- No están pensados para usarse con la API de producción: cada procesamiento por `POST /documentos` escribe en OCI.
