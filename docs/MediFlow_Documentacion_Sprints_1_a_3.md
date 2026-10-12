# MediFlow — Documentación del proyecto

Documentación acumulada por sprint. Proyecto desarrollado para el Hackathon ONE G10 (Oracle Next Education & Alura).

# Sprint 1

## Objetivo del Sprint 1

Construir el esqueleto funcional de MediFlow: recibir un documento clínico, clasificarlo, extraer sus datos estructurados y validar el resultado, integrando en un mismo flujo los contratos de datos, el agente clasificador, el agente extractor, la orquestación con LangGraph y el almacenamiento en OCI Object Storage.

## Qué se desarrolló

* **MF-01 Estructura base del proyecto** — Asignado: Katherine · Ejecutado: Katherine. Estructura de carpetas, `requirements.txt`, README inicial y diagrama de arquitectura.
* **MF-02 Contratos y schemas Pydantic** — Asignado: Manuel · Ejecutado: Kimberlyn. Contratos oficiales de datos (`DocumentoEntrada`, clasificación, extracción y respuesta), con sus pruebas.
* **MF-03 Ingesta mediante FastAPI** — Asignado: Duvan · Ejecutado: Kimberlyn. Endpoint `POST /documentos` para recibir el archivo, validar los datos de entrada y prepararlos para el flujo.
* **MF-04 Integración inicial OCI Object Storage** — Asignado: Katherine · Ejecutado: Katherine. Servicio de conexión con OCI Object Storage (subida y recuperación de documentos), con pruebas.
* **MF-05 Agente Clasificador** — Asignado: Zahir · Ejecutado: Zahir. Agente que identifica el tipo de documento y la especialidad clínica usando Gemini multimodal, con pruebas.
* **MF-06 Agente Extractor** — Asignado: Mauricio · Ejecutado: Mauricio. Agente que extrae los datos clínicos estructurados, con reintentos propios (si el LLM devuelve un JSON inválido o que no cumple el schema, o si el proveedor falla técnicamente) y una extracción vacía controlada si se agotan. El fallback técnico con Groq no forma parte de MF-06: se incorporó formalmente en MF-19 durante el Sprint 2.
* **MF-07 Orquestación base LangGraph** — Asignado: Jennifer · Ejecutado: Jennifer + Kimberlyn. Grafo de estado (Clasificador → Extractor → Validación Pydantic) y estado compartido `MediFlowState`.
* **MF-08 Integración del flujo completo** — Asignado: Kimberlyn · Ejecutado: Kimberlyn. Conecta el endpoint, el grafo y OCI en un solo flujo de punta a punta.
* **MF-16 Dataset de casos de prueba** — Asignado: Manuel · Ejecutado: Kimberlyn. 8 documentos de ejemplo (texto, PDF e imagen) que cubren los 5 tipos documentales, con sus resultados esperados.

## Herramientas utilizadas

**Lenguaje y entorno de desarrollo**
* **Python 3.11:** lenguaje base de todo el núcleo de MediFlow, la definición de tipos y la lógica del sistema.
* **Visual Studio Code:** IDE para desarrollo, depuración y gestión del proyecto.

**Orquestación e inteligencia artificial**
* **LangGraph (StateGraph, TypedDict):** orquestación basada en estados y flujo entre agentes (Clasificador → Extractor → Validación Pydantic).
* **Gemini (LLM multimodal):** modelo base del Agente Clasificador y del Agente Extractor.

**Validación de contratos y API REST**
* **Pydantic (BaseModel, Field):** validación estricta de los contratos de datos entre componentes.
* **FastAPI:** endpoint de ingesta de documentos (`POST /documentos`).

**Persistencia e infraestructura cloud**
* **OCI Object Storage (Always Free):** almacenamiento de los archivos originales en la carpeta `recibidos/` del bucket.

**Pruebas y calidad de código**
* **Pytest:** pruebas unitarias automatizadas de cada módulo, configuradas con `pytest.ini`.

**Control de versiones y gestión**
* **Git y GitHub:** control de versiones con Conventional Commits y ramas por funcionalidad (`feature/MF-XX`), con revisión de código mediante Pull Requests.
* **GitHub Projects:** tablero para el seguimiento del Product Backlog, issues y avance de los sprints.

## Alcance logrado

* Flujo completo Ingesta → Clasificador → Extractor → Validación funcionando de punta a punta.
* Soporte para documentos en TXT, PDF, PNG y JPG, conservando los bytes originales de PDF e imágenes.
* Conexión real con OCI Object Storage probada (subida y recuperación de documentos), con limpieza del nombre de archivo antes de guardarlo.
* Contratos de datos (Pydantic) unificados y usados de forma consistente por la API, los agentes y el grafo.
* Suite de pruebas automatizadas: 24 de 24 tests aprobados en la versión integrada, sin depender de credenciales reales.
* Demo de cierre del Sprint 1 realizada el 24/09.

## Validación del Sprint 1

Evidencias de la demo de cierre del Sprint 1 (24/09): capturas del flujo en ejecución y salidas JSON generadas por MediFlow.

🔗 [Ver evidencias de validación del Sprint 1](https://github.com/No-Country-simulation/G10-LATAM-EQUIPO-31/blob/develop/docs/evidencias-sprint-1.md)

# Sprint 2

## Objetivo del Sprint 2

Integrar en el flujo principal los componentes que completan el triaje de punta a punta (validación de consistencia clínica, evaluación de confianza, urgencia y routing, persistencia y trazabilidad de resultados en OCI, y fallback técnico del LLM) y validar los tres destinos posibles de un documento: `estandar`, `urgente` y `revision_humana`.

Flujo integrado al cierre del Sprint 2: Documento → Clasificación → Extracción → Validación de consistencia → Evaluación de confianza → Routing → Persistencia → Historial.

## Qué se desarrolló

* **MF-09 Validación de consistencia clínica** — Asignado: Tatiana · Ejecutado: Tatiana (con ajustes de integración de Kimberlyn en MF-20). Detecta datos faltantes, inválidos o contradictorios entre la clasificación y la extracción (por ejemplo, una receta que incluye un estudio solicitado) y los devuelve como `inconsistencias` para la evaluación de confianza.
* **MF-10 Evaluación de confianza** — Asignado: Duván · Reasignado y ejecutado: Jennifer. Combina la autoevaluación del modelo con penalizaciones por reglas: campos secundarios faltantes restan 0.05; campos críticos faltantes, errores de validación e inconsistencias restan 0.10. Clasifica en Alta, Media o Baja, y degrada a Media si hay inconsistencias.
* **MF-11 Urgencia y routing** — Asignado: Jennifer · Ejecutado: Jennifer. Reconcilia las señales de urgencia y decide el destino (`estandar`, `urgente` o `revision_humana`). Un caso urgente con confianza Media o Baja va a revisión humana, conservando la marca de urgencia.
* **MF-13 Persistencia de resultados en OCI** — Asignado: Katherine · Ejecutado: Katherine. Guarda el resultado de cada documento según su destino (`procesados/estandar/`, `procesados/urgente/`, `procesados/revision_humana/` y `errores_tecnicos/`), vinculado al original por `documento_id`, con verificación de escritura.
* **MF-15 Historial y trazabilidad del triaje** — Asignado: Zahir · Reasignado y ejecutado: Katherine. Registra cada procesamiento como un evento nuevo en `historial/{documento_id}/`, sin sobrescribir, con la confianza, la ruta y el recorrido (agentes ejecutados, proveedor, modelo y fallback utilizado).
* **MF-19 Fallback técnico de LLM** — Asignado: Mauricio · Ejecutado: Mauricio. Si Gemini falla por un problema técnico (timeout, 429, 5xx o indisponibilidad), el Clasificador y el Extractor continúan con Groq (`qwen/qwen3.8-27b`). Expone la metadata de proveedor y modelo usada por el historial.
* **MF-20 Integración y validación del Sprint 2** — Asignado: Kimberlyn · Ejecutado: Kimberlyn. Integra todos los componentes en el flujo de LangGraph y valida de punta a punta los tres destinos, verificados contra OCI real.

## Herramientas utilizadas

Se mantienen las herramientas del Sprint 1 y se agregan o amplían las siguientes:

**Inteligencia artificial**
* **Groq (SDK oficial, modelo `qwen/qwen3.8-27b`):** proveedor secundario de LLM para el fallback técnico, con visión y salida estructurada compatible con los contratos Pydantic.
* **PyMuPDF:** convierte la primera página de un PDF en imagen cuando el fallback con Groq procesa ese formato.

**Persistencia e infraestructura cloud**
* **OCI Object Storage (ampliado):** además de `recibidos/`, ahora guarda los resultados por destino (`procesados/*`, `errores_tecnicos/`) y el historial de trazabilidad (`historial/{documento_id}/`).

## Alcance logrado

* Flujo completo operativo de punta a punta: ingesta, clasificación, extracción, validación de consistencia, evaluación de confianza, routing, persistencia e historial.
* Los tres destinos (`estandar`, `urgente` y `revision_humana`) validados con documentos de `samples/entradas/`, incluido un caso controlado de inconsistencia clínica que se deriva a revisión humana.
* Penalización diferenciada de campos faltantes: las omisiones administrativas menores no generan revisiones humanas innecesarias.
* El procesamiento continúa aunque falle el proveedor principal de LLM, gracias al fallback con Groq.
* Persistencia e historial verificados contra OCI Object Storage real en los tres escenarios.
* Suite de pruebas automatizadas: 175 de 175 tests aprobados en `develop`.
* Demo de cierre del Sprint 2 realizada el 01/10.

## Validación del Sprint 2

Evidencias de los escenarios probados (documento usado, resultado esperado y obtenido, persistencia en OCI, capturas e historial).

🔗 [Ver evidencias de validación del Sprint 2](https://github.com/No-Country-simulation/G10-LATAM-EQUIPO-31/blob/develop/docs/evidencias-sprint-2.md)

# Sprint 3

Todas las actividades del Sprint 3 quedaron integradas en `develop`. La validación final (MF-17, PR #57) cerró la integración técnica del sprint.

## Objetivo del Sprint 3

Completar funcionalmente el MVP de MediFlow: incorporar el ciclo de revisión humana (HITL), fortalecer el modelo de confianza y el dataset de validación, mejorar la trazabilidad con una huella del documento, sumar el diferencial de alertas y validar de punta a punta el conjunto integrado.

## Qué se desarrolló

Actividades integradas en `develop`:

* **MF-22 Huella SHA-256 del documento** — Asignado: Katherine · Ejecutado: Katherine · **Integrado en `develop` (PR #46)**. Calcula la huella SHA-256 de los bytes originales del archivo recibido, justo después de leerlo y antes de cualquier transformación, y la guarda como `huella_sha256` en la información de trazabilidad: la misma huella queda en `procesados/` y en el evento de `historial/`. Cubre los tres casos (procesamiento correcto, excepción del flujo y fallo técnico del LLM); solo falta si falla la subida del archivo original. Se verificó que el mismo contenido produce la misma huella y que contenidos distintos producen huellas distintas. No altera la persistencia ni el historial existentes. El bloqueo automático de documentos ya procesados (guardia anti-reproceso) queda fuera de este sprint.
* **MF-12 Mecanismo HITL y panel de revisión humana** — Panel y reglas de auditoría: Mauricio · Apoyo en OCI: Katherine · **Integrado en `develop` (PR #47 y PR #48)**. El panel en Streamlit, conectado a una API de auditoría, permite consultar los documentos derivados a `revision_humana` y resolverlos: el revisor solo puede **aprobar** o **rechazar** (el rechazo exige un motivo del catálogo y notas), y no puede corregir la información extraída. Cada decisión se guarda como un evento nuevo en `historial/{documento_id}/`, sin sobrescribir nada. Para esto se agregaron tres métodos a `OCIStorageService` (PR #47), sin modificar los existentes: `listar` (devuelve el nombre y la fecha de cada objeto, con paginación), `leer_json` (lee un archivo del bucket como diccionario) y `escribir_json_nuevo` (guarda un archivo sin sobrescribir uno existente; si ya existe, avisa con `FileExistsError`). Se validó contra el bucket real de OCI con un caso aprobado y uno rechazado.

* **MF-16 Fortalecimiento del dataset y casos de prueba** — Asignado: Tatiana · Ejecutado: Tatiana · **Integrado en `develop` (PR #49)**. Incorpora casos de prueba realistas y anonimizados en PDF e imagen para cuatro escenarios: estándar, urgente explícito, urgencia inferida por signos clínicos (sin etiqueta de prioridad) y ambiguo para revisión humana. Se suman al set de regresión original. Incluye su documentación y la de MF-09 (validación de consistencia). Los casos se ejecutaron de punta a punta en MF-17 (el caso ambiguo se ajustó para provocar la inconsistencia de forma reproducible).

* **MF-21 Confianza según tipo documental** — Jennifer · **Integrado en `develop` (PR #55)**. Una entidad ausente solo penaliza si es crítica para ese tipo de documento: por ejemplo, un certificado médico ya no pierde confianza por no traer medicamentos, y una receta sin medicamentos baja de categoría. Un tipo desconocido se trata de forma conservadora (todo es crítico).
* **MF-23 Enrutamiento por departamento destino** — Jennifer · **Integrado en `develop` (PR #56)**. Agrega el campo `departamento_destino` (farmacia, auditoría de autorizaciones, historia clínica o cola de urgencias) sin modificar `destino_principal`, de modo que no rompe contratos existentes. La urgencia tiene precedencia sobre el tipo documental.
* **MF-14 Alertas de casos urgentes con n8n** — Zahir · **Integrado en `develop` (PR #54)**. Cuando un documento es urgente, un workflow de n8n avisa por Slack y por correo. La alerta está desacoplada: si n8n, Slack o el correo fallan, el procesamiento y la persistencia continúan. El mensaje distingue los casos urgentes en cola de emergencia de los urgentes pendientes de revisión humana. No incluye datos del paciente.

Validación final:

* **MF-17 Validación E2E y regresión final del MVP** — Kimberlyn · **Integrado en `develop` (PR #57)**. Valida sobre `develop` el flujo estándar y urgente, el HITL (aprobación y rechazo), la trazabilidad SHA-256, la persistencia e historial en OCI, la confianza, el fallback técnico y las alertas reales por Slack y correo. Resultado reportado: suite completa 272 de 272, sin regresiones bloqueantes.

## Herramientas utilizadas

Se mantienen las herramientas de los sprints anteriores y se agregan o amplían las siguientes:

**Trazabilidad y persistencia**
* **hashlib (SHA-256):** huella reproducible del contenido de cada documento recibido.
* **OCI Object Storage (ampliado):** lectura, listado y escritura sin sobrescritura de eventos del historial, para registrar las decisiones de revisión humana.

**Revisión humana**
* **Streamlit:** panel de revisión humana (consulta de casos pendientes y decisión de aprobar o rechazar).
* **FastAPI (ampliado):** endpoints de auditoría para la bandeja de pendientes, la línea de tiempo del documento y el registro de la decisión.

**Alertas y notificaciones**
* **n8n:** workflow que recibe el aviso del sistema cuando un documento es urgente y envía las alertas, desacoplado del flujo principal.
* **Slack:** canal `#mediflow-alertas-urgentes`, donde llega el aviso de cada caso urgente.
* **Correo electrónico:** aviso por correo de cada caso urgente.

**Pruebas y calidad de código**
* **Pytest:** pruebas de la huella, de los métodos nuevos de OCI y del flujo de revisión humana, con un cliente de OCI simulado para no depender de credenciales reales.

## Alcance logrado

* Huella SHA-256 del contenido registrada en la trazabilidad de todos los procesamientos y en `procesados/`.
* Ciclo de revisión humana operativo: bandeja de pendientes, decisión de aprobar o rechazar con motivo y notas, y registro de la decisión en el historial sin sobrescribir datos.
* Flujo de revisión humana validado contra el bucket real de OCI con un caso aprobado y uno rechazado.
* Dataset de validación ampliado con casos realistas en PDF e imagen (estándar, urgente explícito, urgencia inferida y ambiguo), ejecutado de punta a punta en MF-17.
* Confianza según tipo documental, enrutamiento por departamento destino y alertas de casos urgentes por Slack y correo.
* Validación E2E y de regresión final: suite de pruebas automatizadas de 272 de 272 (MF-17).
* Demo de cierre del Sprint 3 realizada el 08/10, con los tres flujos: estándar, urgente y revisión humana.

## Validación del Sprint 3

La validación final (MF-17) cubre: flujo estándar y urgente con inferencia de urgencia, HITL con aprobación y rechazo, trazabilidad SHA-256, persistencia e historial en OCI, confianza (8 pruebas), fallback técnico (33 pruebas) y alertas reales recibidas en Slack (`#mediflow-alertas-urgentes`) y por correo. La suite completa pasó 272 de 272. Antes se había validado el panel HITL contra el bucket real de OCI con un caso aprobado y uno rechazado.

### Hallazgos de la demo (pasan al Sprint 4)

La demo del 08/10 dejó dos observaciones que requieren investigación y no se consideran resueltas con el cierre del Sprint 3:

* **Flujo estándar:** el documento elegido para la demo se derivó a revisión humana (HITL). Falta revisar campos, confianza y ruta del caso para justificar la derivación o corregirla.
* **Flujo urgente:** en la receta médica usada, la confianza y las señales de gravedad se mostraron como guiones. Falta identificar si el origen está en la extracción, el transporte o la presentación.

🔗 Evidencias del Sprint 3: [docs/evidencias-sprint-3.md](https://github.com/No-Country-simulation/G10-LATAM-EQUIPO-31/blob/develop/docs/evidencias-sprint-3.md) 

# Estado actual

* **Cierre real del Sprint 3:** 08/10/2026, con MF-12, MF-14, MF-16, MF-17, MF-21, MF-22 y MF-23 integrados en `develop` y 272 pruebas aprobadas.
* **Integrado a `develop`:** MF-01 a MF-17, MF-19, MF-20, MF-21, MF-22 y MF-23. La rama `develop` contiene el flujo completo del Sprint 2 y las funcionalidades del Sprint 3 (HITL, huella SHA-256, confianza por tipo documental, departamento destino y alertas).
* **`main`:** se actualizará cuando `develop` tenga una versión estable para entregar.

# Próximos pasos

1. **Publicar la documentación final del Sprint 3** (README y evidencias) en `develop`, una vez aprobada por Kimberlyn.
2. **Sprint 4 (propuesta sujeta a validación del equipo):** estabilizar el MVP; investigar la confianza y las señales de gravedad en la receta urgente; revisar la derivación del caso estándar a HITL; pruebas adicionales del equipo; interfaz amigable de entrada; selección de documentos definitivos de demo; e integración y validación de lo resuelto. Los responsables, los identificadores y el seguimiento se gestionan desde el Plan de Trabajo y GitHub Projects.
3. **Semana 5:** cierre y entrega (feedback, ajustes menores, video final y revisión de README y evidencias).
4. **Actualizar `main`** cuando `develop` tenga una versión estable para entregar.
