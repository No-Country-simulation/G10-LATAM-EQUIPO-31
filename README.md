# MediFlow

Sistema inteligente para procesamiento y triaje de documentos clínicos.

Proyecto desarrollado para Hackathon ONE G10.

## Descripción general del proyecto

MediFlow es un sistema inteligente basado en agentes de IA para el triaje, extracción y enrutamiento de documentos clínicos. El sistema recibe documentos clínicos y administrativos en distintos formatos (PDF, imagen o texto), los clasifica automáticamente, extrae los datos esenciales con un LLM multimodal, y los enruta al destino correcto según su nivel de urgencia y confianza de extracción — sin intervención humana manual para los casos estándar.

Proyecto desarrollado para el Hackathon ONE G10 (Oracle Next Education & Alura).

## Objetivo del proyecto

Reducir el tiempo y los errores del procesamiento manual de documentos clínicos en hospitales, laboratorios y aseguradoras de salud, mediante un pipeline automatizado de clasificación, extracción y enrutamiento, con revisión humana (Human-in-the-Loop) para los casos que el sistema detecta como ambiguos, inconsistentes o de baja confianza.

## Arquitectura aprobada

La arquitectura está orquestada con LangGraph y combina dos agentes especializados, validación estructural y lógica de decisión condicional:

- **Agente Clasificador:** identifica el tipo de documento y la especialidad clínica correspondiente.
- **Agente Extractor:** extrae los datos clínicos estructurados según el tipo de documento clasificado.
- **Validación (Pydantic):** valida tipos, formato y campos requeridos del JSON extraído.
- **Validación de consistencia (MF-09):** detecta inconsistencias estructurales y de enrutamiento entre lo que informa el Clasificador y lo que extrae el Extractor (por ejemplo, una receta médica que además incluye un estudio solicitado). No valida la plausibilidad clínica de los datos (ver [Alcance y limitaciones conocidas del MVP](#alcance-y-limitaciones-conocidas-del-mvp)). Detalle en [docs/MF-10-criterio-confianza.md](docs/MF-10-criterio-confianza.md).
- **Evaluación de confianza:** calcula un score de confianza combinando la autoevaluación del modelo con una penalización por reglas (campos faltantes, errores de validación e inconsistencias detectadas) y lo clasifica en Alta, Media o Baja. MediFlow detecta inconsistencias estructurales y entre clasificación y extracción, pero no garantiza identificar contradicciones clínicas complejas (ver [Alcance y limitaciones conocidas del MVP](#alcance-y-limitaciones-conocidas-del-mvp)). Detalle en [docs/MF-10-criterio-confianza.md](docs/MF-10-criterio-confianza.md).
- **Enrutamiento condicional:** deriva el documento a uno de tres destinos (`estandar`, `urgente` o `revision_humana`) según la urgencia y la categoría de confianza, con precedencia de la confianza sobre la urgencia. Detalle en [docs/MF-11-urgencia-routing.md](docs/MF-11-urgencia-routing.md).
- **Fallback técnico:** ante fallos de la API del LLM principal (timeout, error 429/5xx, indisponibilidad), el sistema reintenta con un proveedor secundario (Groq) antes de fallar. Detalle en [docs/mf-19-fallback-tecnico.md](docs/mf-19-fallback-tecnico.md).
- **Persistencia:** los documentos originales se almacenan en `recibidos/`, y el resultado del flujo se persiste aparte según su destino (`procesados/estandar/`, `procesados/urgente/`, `procesados/revision_humana/`, `errores_tecnicos/`), vinculado al original por `documento_id`. Detalle en [docs/persistencia-resultados.md](docs/persistencia-resultados.md).
- **Historial y trazabilidad:** cada corrida de procesamiento queda registrada como un evento nuevo en `historial/{documento_id}/`, que nunca se sobrescribe, para reconstruir la clasificación, extracción, confianza, routing y derivación a HITL de cada intento. Detalle en [docs/historial-triaje.md](docs/historial-triaje.md).
- **Huella del contenido (MF-22):** cada procesamiento registra el SHA-256 de los bytes originales del archivo recibido (`huella_sha256`), tanto en `procesados/` como en el evento de `historial/`. Sirve solo para identificación y trazabilidad: no bloquea ni decide nada. Detalle en [docs/historial-triaje.md](docs/historial-triaje.md).
- **Confianza por tipo documental (MF-21):** una entidad ausente solo penaliza si es crítica para ese tipo de documento (por ejemplo, un certificado médico no necesita medicamentos). Detalle en [docs/MF-21-confianza-por-tipo-documental.md](docs/MF-21-confianza-por-tipo-documental.md).
- **Departamento destino (MF-23):** campo `departamento_destino`, que indica a qué área corresponde cada documento y complementa (no reemplaza) a `destino_principal`. Detalle en [docs/MF-23-enrutamiento-departamento.md](docs/MF-23-enrutamiento-departamento.md).
- **Alertas de casos urgentes (MF-14):** cuando un documento es urgente, MediFlow avisa por Slack y correo mediante un workflow de n8n, desacoplado del flujo principal: si la alerta falla, el procesamiento continúa. Detalle en [docs/MF-14-alertas-n8n.md](docs/MF-14-alertas-n8n.md).
- **Revisión humana, HITL (MF-12):** los documentos que el flujo deriva a `revision_humana` se consultan y resuelven desde un panel en Streamlit conectado a una API de auditoría. El revisor solo puede **aprobar** o **rechazar** (el rechazo exige motivo y notas). La decisión se guarda como un evento nuevo en `historial/` sin sobrescribir nada. En el Sprint 4 se mejoró su usabilidad (MF-30). Detalle en [docs/MF-12-hitl-review.md](docs/MF-12-hitl-review.md) y [docs/MF-30-mejoras-panel-hitl.md](docs/MF-30-mejoras-panel-hitl.md).
- **Interfaz de carga y consulta (MF-28):** aplicación en Streamlit para cargar documentos (PDF, JPG, PNG, TXT, JSON y Markdown) y consultar su resultado, su estado y su historial a través de la API, con una explicación de la confianza. Detalle en [docs/MF-28-interfaz-amigable-de-entrada.md](docs/MF-28-interfaz-amigable-de-entrada.md).

### Diagrama de arquitectura

![Arquitectura MediFlow](docs/arquitectura.png)

## Alcance y limitaciones conocidas del MVP

MediFlow deriva a revisión humana los casos que **detecta** como dudosos: confianza Media o Baja, por ejemplo por datos faltantes o por inconsistencias estructurales. El MVP tiene estas limitaciones conocidas, documentadas al cierre de MF-32 y MF-35 (no se corrigieron con cambios de código):

- **Sin validación de plausibilidad clínica:** el sistema no detecta contradicciones biológicas o médicas, como un paciente masculino con diagnóstico de embarazo (`p10.jpg`, MF-35) o un paciente de 8 meses con Alzheimer avanzado (`caso-urgente.png`, MF-32). Estos documentos pueden procesarse como estándar con confianza Alta.
- **Urgencia solo con señales explícitas:** la ruta urgente requiere señales explícitas en el texto (signos vitales o términos de alarma); el sistema no infiere gravedad implícita.
- **Dependencia de la calidad del documento:** el sistema procesa el texto tal como llega, sin corregir datos incoherentes de origen.

**Mejoras futuras:** un motor de reglas de plausibilidad clínica (sexo, edad y diagnósticos) y una configuración sin código para que el hospital ajuste reglas de triaje, destinos y umbrales.

## Versión desplegada

MediFlow está desplegado en dos partes:

| Componente | Plataforma | Enlace |
|---|---|---|
| Interfaz (Streamlit): carga, consulta y revisión humana | Streamlit Community Cloud | https://mediflow-g10-equipo31.streamlit.app |
| API (FastAPI) | Render | https://mediflow-api-test.onrender.com/docs |

**Video de demostración:** https://youtu.be/bXamIpZETGY

- La interfaz se conecta con la API mediante la variable `MEDIFLOW_API_URL`.
- Las claves (Gemini, Groq, OCI y n8n) se cargan como variables de entorno en cada plataforma y no se guardan en el repositorio. Ver [.env.example](.env.example).
- La API no tiene página de inicio. Su documentación interactiva está en `/docs`.
- Render, en su plan gratuito, apaga el servidor cuando no se usa. La primera carga puede tardar hasta un minuto.

## Tecnologías definidas

- Python 3.11
- FastAPI — ingesta y API REST
- LangGraph — orquestación del flujo del agente
- Pydantic — validación estructural de datos
- Google Gemini — modelo LLM multimodal (clasificación y extracción)
- Groq (`qwen/qwen3.8-27b`) — proveedor secundario para el fallback técnico del LLM
- PyMuPDF — rasteriza PDF a imagen para el fallback de Groq
- OCI Object Storage — almacenamiento de documentos originales, resultados por destino e historial de trazabilidad
- Streamlit — interfaz de carga y consulta, y panel de revisión humana (HITL)
- n8n — workflow de alertas de casos urgentes (aviso por Slack y correo)

## Estructura del repositorio

```
G10-LATAM-EQUIPO-31/
├── app/
│   ├── agents/       # Agentes de clasificación y extracción
│   ├── api/           # Endpoints FastAPI (ingesta de documentos y auditoría HITL)
│   ├── graph/          # Orquestación del flujo con LangGraph
│   ├── schemas/        # Modelos Pydantic (validación de datos)
│   ├── services/        # Servicios externos (OCI, LLM, etc.)
│   └── config/           # Configuración del proyecto
├── frontend/               # Interfaz de carga y consulta, y panel de revisión humana (Streamlit)
├── tests/                 # Pruebas automatizadas
├── samples/                # Casos de prueba / documentos de ejemplo
├── docs/                     # Documentación y diagramas
├── requirements.txt            # Dependencias del proyecto
├── .env.example                 # Variables de entorno de referencia
├── main.py                       # Punto de entrada de la aplicación
└── README.md
```

`app/services/oci_storage_service.py` — servicio de conexión con OCI Object Storage: carga y recuperación de documentos originales (MF-04), persistencia del resultado del flujo por estado (MF-13, ver [docs/persistencia-resultados.md](docs/persistencia-resultados.md)), registro del historial de trazabilidad por documento (MF-15, ver [docs/historial-triaje.md](docs/historial-triaje.md)), y métodos para consultar y registrar decisiones de revisión humana sin sobrescribir datos: `listar`, `leer_json` y `escribir_json_nuevo` (MF-12, ver [docs/MF-12-hitl-review.md](docs/MF-12-hitl-review.md)).

## Configuración inicial del entorno

1. Verificar que tenés Python 3.11 instalado.
2. Crear y activar un entorno virtual:
   ```
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   source .venv/bin/activate   # macOS/Linux
   ```
3. Instalar las dependencias:
   ```
   pip install -r requirements.txt
   ```
4. Copiar .env.example como .env y completar los valores reales (API keys de Gemini —`GEMINI_CLASSIFIER_API_KEY` y `GEMINI_EXTRACTOR_API_KEY`—, credenciales de OCI, y opcionalmente la API key de Groq para el fallback técnico). Si las claves de Gemini quedan vacías, los documentos terminan como fallo técnico. Para las alertas (MF-14) se usan además `N8N_ALERT_WEBHOOK_URL` y `N8N_ALERT_WEBHOOK_TOKEN` (opcionales: sin ellas las alertas quedan inactivas):
   ```
   cp .env.example .env
   ```

## Cómo procesar un documento desde Swagger

Con el `.env` completo y la API en marcha (`python -m uvicorn main:app --port 8000`):

1. Abrir Swagger en `http://localhost:8000/docs`.
2. Expandir `POST /documentos` y presionar **Try it out**.
3. Completar los tres campos requeridos:
   - `documento_id`: identificador del documento (usar uno distinto para cada documento).
   - `canal_origen`: canal por el que llega el documento (texto).
   - `archivo`: el documento a procesar (PDF, imagen PNG o JPG, o texto).
4. Presionar **Execute**.

La respuesta indica el `estado` del documento (`estandar`, `urgente` o `revision_humana`), si el resultado y el historial se guardaron en OCI (`persistencia_ok` e `historial_ok`) y el detalle de la clasificación, la extracción y la validación. Los documentos derivados a `revision_humana` se resuelven desde el panel de revisión humana.

## Cómo ejecutar la interfaz de carga y consulta

Con el `.env` completo (claves de Gemini y credenciales de OCI), desde la raíz del repositorio y en dos terminales:

```
python -m uvicorn main:app --port 8000          # terminal 1: API
python -m streamlit run frontend/mediflow.py    # terminal 2: interfaz
```

La interfaz necesita la API en marcha: si está apagada, muestra un aviso de falta de conexión. Streamlit usa su puerto por defecto (`http://localhost:8501`). La interfaz tiene tres pantallas, accesibles desde el menú lateral:

| Pantalla | Dirección | Qué permite |
|---|---|---|
| Carga de documentos | `/carga` | Cargar PDF, JPG, PNG, TXT, JSON o Markdown (estos dos últimos se envían como texto) |
| Consulta de resultados | `/consulta` | Ver resultado, estado e historial de un documento |
| Revisión humana | `/revision` | Panel HITL para aprobar o rechazar casos |

Detalle en [docs/MF-28-interfaz-amigable-de-entrada.md](docs/MF-28-interfaz-amigable-de-entrada.md).

## Cómo ejecutar el panel de revisión humana

Con el `.env` completo (claves de Gemini y credenciales de OCI), desde la raíz del repositorio y en dos terminales:

```
python -m uvicorn main:app --port 8000                     # terminal 1: API
python -m streamlit run frontend/panel_hitl.py --server.port 8502   # terminal 2: panel
```

El panel queda en `http://localhost:8502`. El nombre del auditor se escribe a mano (no hay autenticación en el MVP) y queda registrado en cada decisión. Detalle completo en [docs/MF-12-hitl-review.md](docs/MF-12-hitl-review.md).

## Flujo de trabajo con Git

- **main** — rama estable. Solo recibe código ya integrado y probado.
- **develop** — rama de integración. Base para todas las actividades del equipo.
- **feature/*** — una rama por actividad, creada desde develop (ej: feature/MF-01-estructura-base).
- Al finalizar una actividad, se abre un Pull Request hacia develop para su revisión e integración.
- Cuando develop tenga una versión estable, se integra a main.

## Equipo

Integrantes que participaron en el desarrollo de MediFlow y sus contribuciones generales. El detalle de las actividades está en la sección siguiente, y las asignaciones vigentes se pueden consultar en GitHub Projects.

| Integrante | Contribuciones generales |
|---|---|
| Kimberlyn | Liderazgo y coordinación del equipo, desarrollo de contratos Pydantic e ingesta con FastAPI, integración y validación del flujo, seguimiento de actividades, revisión e integración de Pull Requests |
| Katherine | Estructura base del proyecto, integración con OCI Object Storage, persistencia de resultados e historial, huella SHA-256, apoyo en OCI al panel HITL, pruebas adicionales y selección de los documentos definitivos de la demo |
| Mauricio | Agente Extractor, fallback técnico con Groq, panel de revisión humana (HITL) y soporte de archivos TXT |
| Jennifer | Orquestación con LangGraph, evaluación de confianza (incluida la de tipo documental), urgencia y routing, enrutamiento por departamento y pruebas adicionales |
| Zahir | Participación inicial en la creación del repositorio, Agente Clasificador y alertas de casos urgentes con n8n |
| Tatiana | Validación de consistencia (MF-09) y fortalecimiento del dataset de casos de prueba |

## Actividades desarrolladas por sprint

Registro de las actividades (MF) de cada sprint. El detalle de cada una está en los documentos de la carpeta `docs/` y en los Pull Requests indicados.

### Sprint 1

| Actividad | Descripción | Referencia |
|---|---|---|
| MF-01 Estructura base del proyecto | Carpetas, dependencias, README inicial y diagrama de arquitectura | — |
| MF-02 Contratos y schemas Pydantic | Contratos de entrada, clasificación, extracción y respuesta, con sus pruebas | — |
| MF-03 Ingesta con FastAPI | Endpoint `POST /documentos` para recibir y validar el archivo | — |
| MF-04 Integración inicial con OCI Object Storage | Subida y recuperación de documentos originales | — |
| MF-05 Agente Clasificador | Identifica el tipo de documento y la especialidad con Gemini multimodal | — |
| MF-06 Agente Extractor | Extracción estructurada según el tipo, con reintentos propios | — |
| MF-07 Orquestación base con LangGraph | Estado y grafo inicial que conecta los componentes | — |
| MF-08 Integración del flujo completo | Conecta endpoint, grafo y OCI de punta a punta | — |
| MF-16 Dataset inicial | Dataset de 8 casos de prueba | [docs/MF-16-arquitectura-dataset.md](docs/MF-16-arquitectura-dataset.md) |

### Sprint 2

| Actividad | Descripción | Referencia |
|---|---|---|
| MF-09 Validación de consistencia | Validaciones estructurales y de consistencia entre clasificación y extracción; no garantiza detectar contradicciones de plausibilidad clínica (ver MF-32 y MF-35 en [Alcance y limitaciones conocidas del MVP](#alcance-y-limitaciones-conocidas-del-mvp)) | [docs/MF-09-validacion-consistencia.md](docs/MF-09-validacion-consistencia.md) |
| MF-10 Evaluación de confianza | Score de confianza (Alta, Media o Baja) | [docs/MF-10-criterio-confianza.md](docs/MF-10-criterio-confianza.md) |
| MF-11 Urgencia y routing | Decide el destino: `estandar`, `urgente` o `revision_humana` | [docs/MF-11-urgencia-routing.md](docs/MF-11-urgencia-routing.md) |
| MF-13 Persistencia de resultados en OCI | Guarda el resultado según su destino | [docs/persistencia-resultados.md](docs/persistencia-resultados.md) |
| MF-15 Historial y trazabilidad | Registro de cada corrida en `historial/{documento_id}/` | [docs/historial-triaje.md](docs/historial-triaje.md) |
| MF-19 Fallback técnico de LLM | Respaldo con Groq ante fallos técnicos de Gemini | [docs/mf-19-fallback-tecnico.md](docs/mf-19-fallback-tecnico.md) |
| MF-20 Integración y validación del Sprint 2 | Valida los tres destinos contra OCI real | [docs/MF-20-integracion-validacion-sprint2.md](docs/MF-20-integracion-validacion-sprint2.md) |

### Sprint 3

| Actividad | Descripción | Referencia |
|---|---|---|
| MF-22 Huella SHA-256 | `huella_sha256` en `procesados/` y en el historial | PR #46 · [docs/historial-triaje.md](docs/historial-triaje.md) |
| MF-12 Mecanismo HITL y panel de revisión humana | Panel en Streamlit, API de auditoría y decisiones aprobar o rechazar | PR #47 y #48 · [docs/MF-12-hitl-review.md](docs/MF-12-hitl-review.md) |
| MF-16 Fortalecimiento del dataset | Casos realistas en PDF e imagen | PR #49 · [docs/MF-16-dataset-casos-prueba.md](docs/MF-16-dataset-casos-prueba.md) |
| MF-21 Confianza por tipo documental | Matriz de criticidad por tipo de documento | PR #55 · [docs/MF-21-confianza-por-tipo-documental.md](docs/MF-21-confianza-por-tipo-documental.md) |
| MF-23 Enrutamiento por departamento | Campo `departamento_destino` | PR #56 · [docs/MF-23-enrutamiento-departamento.md](docs/MF-23-enrutamiento-departamento.md) |
| MF-14 Alertas de casos urgentes con n8n | Aviso por Slack y correo, desacoplado del flujo | PR #54 · [docs/MF-14-alertas-n8n.md](docs/MF-14-alertas-n8n.md) |
| MF-17 Validación E2E y regresión final del MVP | Validación de punta a punta sin código nuevo | PR #57 · [docs/MF-17-validacion-e2e-regresion.md](docs/MF-17-validacion-e2e-regresion.md) |

### Sprint 4

| Actividad | Descripción | Referencia |
|---|---|---|
| MF-24 Confianza y gravedad en receta urgente | Corrección de los guiones en la confianza y las señales de gravedad; alertas aisladas durante las pruebas | PR #77 · [docs/MF-24-confianza-gravedad-receta-urgente.md](docs/MF-24-confianza-gravedad-receta-urgente.md) |
| MF-25 Derivación del caso estándar a HITL | Reglas de clasificación explicadas y equivalencia estudios/procedimientos corregida | PR #78 · [docs/MF-25-derivacion-estandar-hitl.md](docs/MF-25-derivacion-estandar-hitl.md) |
| MF-26 Pruebas adicionales y registro de hallazgos | Pruebas del equipo (formatos, OCI, HITL y alertas) con hallazgos reproducibles | PR #70 · [docs/MF-26-pruebas-validacion-hallazgos.md](docs/MF-26-pruebas-validacion-hallazgos.md) |
| MF-28 Interfaz amigable de entrada | Interfaz de carga y consulta en Streamlit, con explicación de la confianza | [docs/MF-28-interfaz-amigable-de-entrada.md](docs/MF-28-interfaz-amigable-de-entrada.md) |
| MF-29 Selección de documentos definitivos de demo | Tres documentos elegidos tras 19 corridas por API y 9 por la interfaz | [docs/MF-29-seleccion-documentos-definitivos.md](docs/MF-29-seleccion-documentos-definitivos.md) |
| MF-30 Usabilidad del panel HITL | Avisos duplicados y mensajes de API o bandeja no disponible corregidos | PR #67 · [docs/MF-30-mejoras-panel-hitl.md](docs/MF-30-mejoras-panel-hitl.md) |
| MF-31 Integración y validación del Sprint 4 | Validación de las actividades del sprint: 361 pruebas aprobadas | PR #79 · [docs/MF-31-integracion-validacion-sprint4.md](docs/MF-31-integracion-validacion-sprint4.md) |
| MF-33 Mejora de conexión y respuesta de la interfaz | Uso de `127.0.0.1` y mejor respuesta con la API apagada | PR #71 · [docs/MF-33-api-url-ipv4.md](docs/MF-33-api-url-ipv4.md) |
| MF-34 Soporte TXT en la interfaz y API | Carga de archivos de texto UTF-8 como `text/plain` | PR #74 · [docs/MF-72-soporte-txt.md](docs/MF-72-soporte-txt.md) |

## Cierre del Sprint 1

Al cierre del Sprint 1 quedó integrado y validado el flujo completo de procesamiento de documentos clínicos:

**Flujo de procesamiento:** Ingesta → Clasificador → Extractor → Validación

**Persistencia:** documento original almacenado en OCI Object Storage (`recibidos/`).

El sistema recibe el documento a través del endpoint `POST /documentos`, lo clasifica, extrae los datos clínicos estructurados con el LLM multimodal y valida la respuesta contra los contratos Pydantic.

- **Formatos probados:** TXT, PDF, PNG y JPG, incluyendo casos multimodales de imagen.
- **Pruebas automatizadas:** 24/24 aprobadas sobre la rama `develop`.
- **Evidencias:** el detalle de cada ejecución y las respuestas generadas se documentan en [docs/evidencias-sprint-1.md](docs/evidencias-sprint-1.md).

## Cierre del Sprint 2

Al cierre del Sprint 2 quedó integrado y validado el flujo completo de triaje, desde la ingesta hasta el registro de trazabilidad:

**Flujo de procesamiento:** Ingesta → Clasificador → Extractor → Validación → Consistencia → Confianza → Routing → Persistencia → Historial

El sistema, además de clasificar, extraer y validar (Sprint 1), ahora valida la consistencia entre clasificación y extracción, calcula un score de confianza combinando la autoevaluación del modelo con reglas de completitud, y enruta cada documento a uno de tres destinos: `estandar`, `urgente` o `revision_humana`. El resultado se persiste en OCI Object Storage según su destino, y cada corrida queda además registrada en un historial de trazabilidad que nunca se sobrescribe. Si el proveedor principal del LLM (Gemini) falla por un problema técnico, el sistema reintenta automáticamente con un proveedor secundario (Groq) antes de marcar el documento como fallo técnico.

- **Pruebas automatizadas:** 175/175 aprobadas sobre la rama `develop`.
- **Evidencias:** el detalle de cada escenario validado (estándar, urgente y revisión humana), con persistencia e historial verificados en OCI, se documenta en [docs/evidencias-sprint-2.md](docs/evidencias-sprint-2.md).

## Cierre del Sprint 3

Al cierre del Sprint 3 (08/10/2026) quedó integrado y validado el MVP completo en `develop`: además del flujo del Sprint 2, el sistema suma revisión humana (HITL), huella SHA-256 del documento, confianza según tipo documental, departamento destino y alertas de casos urgentes por Slack y correo. El conjunto se presentó en la demo de cierre del Sprint 3 con los tres flujos: estándar, urgente y revisión humana.

- **Pruebas automatizadas:** 272/272 aprobadas sobre la rama `develop`.
- **Evidencias:** el detalle de cada escenario validado se documenta en [docs/evidencias-sprint-3.md](docs/evidencias-sprint-3.md), [docs/MF-12-hitl-review.md](docs/MF-12-hitl-review.md) y [docs/MF-17-validacion-e2e-regresion.md](docs/MF-17-validacion-e2e-regresion.md).

**Hallazgos de la demo (atendidos en el Sprint 4):** la demostración dejó dos observaciones que se investigaron y corrigieron en el Sprint 4:

- **Flujo estándar:** el documento elegido para la demo se derivó a revisión humana (HITL). Se revisaron los campos, la confianza y la ruta del caso, se explicaron las reglas de clasificación y se corrigió una equivalencia de campos (MF-25).
- **Flujo urgente:** en la receta médica usada, la confianza y las señales de gravedad se mostraron como guiones. Se investigó el origen y se corrigió (MF-24).

## Cierre del Sprint 4

Al cierre de la etapa de desarrollo del Sprint 4 (16/10/2026) quedaron integradas en `develop` la interfaz amigable de carga y consulta, el soporte de archivos TXT, las correcciones de los hallazgos de la demo del Sprint 3 y las mejoras de usabilidad del panel HITL. En la Sprint Demo 4 se presentaron los tres escenarios (estándar, urgente y revisión humana, incluido el rechazo de un caso) con entradas PDF, JPEG, PNG y TXT.

**Documentos definitivos de la demo (MF-29):** `01_receta_medica.txt` (flujo estándar), `02_informe_estudio.txt` (flujo urgente) y `09_receta_inconsistente_hitl.txt` (revisión humana). Además, se validaron con pruebas satisfactorias `06_receta_medica.pdf` (flujo estándar, PDF) y `08_orden_procedimiento.jpg` (flujo estándar, imagen), documentadas en [docs/MF-29-seleccion-documentos-definitivos.md](docs/MF-29-seleccion-documentos-definitivos.md) y [docs/MF-26-pruebas-validacion-hallazgos.md](docs/MF-26-pruebas-validacion-hallazgos.md).

- **Pruebas automatizadas:** 361 aprobadas en la validación de integración del Sprint 4 (MF-31).
- **Evidencias:** el detalle de los escenarios validados se documenta en [docs/evidencias-sprint-4.md](docs/evidencias-sprint-4.md).

**Hallazgos MF-32 y MF-35:** se cerraron como **limitaciones conocidas del MVP**, sin cambios de código. Ver [Alcance y limitaciones conocidas del MVP](#alcance-y-limitaciones-conocidas-del-mvp).

**Semana 5 (cierre del proyecto):** consolidación de `develop` en `main`, despliegue de la versión final, actualización de la documentación y del diagrama de arquitectura, video del entregable y preparación del Demo Day.
