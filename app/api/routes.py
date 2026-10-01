import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.oci_storage_service import (
    DESTINOS_PRINCIPALES,
    ESTADO_ERROR_TECNICO,
    OCIStorageService,
    PersistenciaOCIError,
)
from app.graph.graph import grafo_mediflow
from app.schemas.documento import DocumentoEntrada

logger = logging.getLogger("mediflow.app.api.routes")

router = APIRouter()

# Campos del documento original que NO se persisten junto con el resultado:
# el contenido ya vive en recibidos/ (MF-04), así que duplicarlo acá solo
# infla el JSON de resultado sin necesidad.
_CAMPOS_DOCUMENTO_EXCLUIDOS_DEL_RESULTADO = {"contenido_bytes", "documento_texto"}


def _serializar_valor_estado(clave: str, valor):
    """Convierte un valor del estado del grafo a algo JSON-serializable."""
    if isinstance(valor, DocumentoEntrada):
        return valor.model_dump(exclude=_CAMPOS_DOCUMENTO_EXCLUIDOS_DEL_RESULTADO)
    if isinstance(valor, BaseModel):
        return valor.model_dump()
    return valor


def _serializar_estado_grafo(resultado: dict) -> dict:
    """
    Serializa el estado COMPLETO que devuelve `grafo_mediflow.invoke(...)`,
    sin asumir de antemano qué claves va a tener: MF-09/MF-10/MF-11/MF-19
    todavía pueden agregar campos nuevos al estado (score de confianza,
    motivo de derivación, reintentos técnicos, etc.) y no hace falta tocar
    esta función para que se persistan — alcanza con que sean valores
    planos o instancias de un modelo Pydantic (el patrón que ya usa todo
    el proyecto para las salidas de los agentes).

    Excluye el contenido pesado del documento original (bytes y texto
    completo): ya se guardó en recibidos/ (MF-04), duplicarlo acá no suma
    nada y solo agranda el objeto en OCI.
    """
    return {
        clave: _serializar_valor_estado(clave, valor)
        for clave, valor in resultado.items()
    }


def determinar_estado(
    validacion_ok: bool,
    hubo_excepcion: bool,
    destino_principal: str | None = None,
    fallos_tecnicos: list | None = None,
) -> str:
    """
    Determina bajo cuál estado (ver ESTADOS_A_PREFIJO en
    oci_storage_service.py) se persiste el resultado del flujo.

    1. Si el grafo lanzó una excepción técnica real (proveedor/modelo, un
       nodo que falla) -> error_tecnico.
    2. Si el estado trae `fallos_tecnicos` (campo que agrega MF-19) con al
       menos un elemento -> error_tecnico también, aunque no haya habido
       excepción: el grafo pudo capturar el fallo dentro de un nodo y seguir
       corriendo, pero sigue siendo un fallo técnico real que no debe
       enrutarse como si el documento se hubiese procesado bien. Tiene la
       misma prioridad que una excepción real: manda por encima de
       `destino_principal`.
    3. Si el estado trae un `destino_principal` válido (contrato de MF-11:
       "estandar", "urgente" o "revision_humana") -> se usa tal cual.
    4. Si trae un `destino_principal` que no es exactamente uno de esos 3
       valores (mayúsculas, acentos, espacios, otro texto) -> revision_humana,
       con una advertencia en el log: ante la duda, un documento que podría
       ser urgente no debe terminar en estandar.
    5. Si no trae `destino_principal` (MF-11 todavía no está integrado) ->
       fallback con la única señal disponible: validacion_ok False va a
       revision_humana, el resto a estandar.
    """
    if hubo_excepcion or fallos_tecnicos:
        return ESTADO_ERROR_TECNICO
    if destino_principal in DESTINOS_PRINCIPALES:
        return destino_principal
    if destino_principal is not None:
        logger.warning(
            "destino_principal desconocido %r; se deriva a revision_humana",
            destino_principal,
        )
        return "revision_humana"
    if not validacion_ok:
        return "revision_humana"
    return "estandar"


@router.post("/documentos")
async def recibir_documento(
    documento_id: str = Form(...),
    canal_origen: str = Form(...),
    archivo: UploadFile = File(...)
):
    # 1. Leer el archivo recibido
    contenido = await archivo.read()

    # 2. Preparar contenido según el tipo de archivo. Un tipo no soportado es
    #    un error del cliente (415), no un fallo técnico del flujo: se valida
    #    ANTES de tocar OCI o el grafo, y no se persiste nada en OCI.
    mime_type = archivo.content_type or "application/octet-stream"

    if mime_type.startswith("text/"):
        tipo_archivo = "JSON"  # Temporal hasta ajustar el contrato de MF-02.
        texto_documento = contenido.decode("utf-8")

    elif mime_type == "application/pdf":
        tipo_archivo = "PDF"
        texto_documento = None

    elif mime_type.startswith("image/"):
        tipo_archivo = "Imagen"
        texto_documento = None

    else:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo de archivo no soportado: {mime_type}",
        )

    # 3. Guardar documento original en OCI. Si esto falla, es una caída de
    #    infraestructura, no un fallo del flujo: no tiene sentido correr el
    #    grafo (ni gastar una llamada al LLM) si ni siquiera se pudo
    #    guardar el documento que se va a procesar, y reintentar la
    #    persistencia de un registro de error contra el mismo OCI que
    #    acaba de fallar tampoco sirve. Se responde 503 directo, sin
    #    ejecutar el grafo ni intentar persistir nada más.
    storage = OCIStorageService()

    try:
        object_name = storage.upload_document(
            document_id=documento_id,
            content=contenido,
            filename=archivo.filename,
        )
    except Exception as exc:
        logger.error(
            "No se pudo guardar el documento original de documento_id=%s en OCI: %s",
            documento_id, exc,
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "documento_id": documento_id,
                "mensaje": "No se pudo guardar el documento original en OCI Object Storage.",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    # 4. Construir el contrato común de entrada de MediFlow
    documento = DocumentoEntrada(
        documento_id=documento_id,
        tipo_archivo=tipo_archivo,
        canal_origen=canal_origen,
        nombre_archivo=archivo.filename,
        mime_type=mime_type,
        contenido_bytes=contenido,
        documento_texto=texto_documento,
    )

    # 5. Ejecutar el flujo de MediFlow mediante LangGraph. Cualquier
    #    excepción acá es un fallo técnico real del flujo (nodo que
    #    crashea, proveedor/modelo) -> estado error_tecnico.
    resultado = None
    error_tecnico = None
    try:
        resultado = grafo_mediflow.invoke({"documento": documento})
    except Exception as exc:
        logger.exception(
            "Fallo técnico procesando documento_id=%s", documento_id
        )
        error_tecnico = f"{type(exc).__name__}: {exc}"

    hubo_excepcion = error_tecnico is not None
    validacion_ok = bool(resultado) and resultado.get("validacion_ok", False)
    destino_principal = resultado.get("destino_principal") if resultado else None
    # `fallos_tecnicos` es un campo que agrega MF-19: el grafo puede
    # capturar un fallo técnico dentro de un nodo y seguir corriendo, sin
    # que eso dispare una excepción acá. No hay MediFlowState todavía con
    # esta clave (ver app/schemas/state.py), así que se lee con .get() como
    # el resto de los campos que MF-09/MF-10/MF-11 todavía no integran.
    fallos_tecnicos = resultado.get("fallos_tecnicos") if resultado else None
    estado = determinar_estado(
        validacion_ok=validacion_ok,
        hubo_excepcion=hubo_excepcion,
        destino_principal=destino_principal,
        fallos_tecnicos=fallos_tecnicos,
    )
    # La respuesta HTTP (status/mensaje/código) sigue el mismo camino que ya
    # usábamos para error_tecnico, tanto si vino de una excepción real como
    # si vino de fallos_tecnicos (MF-19) sin excepción.
    es_error_tecnico = estado == ESTADO_ERROR_TECNICO

    # 6. Serializar el estado COMPLETO que devolvió el grafo (para
    #    persistirlo tal cual, ver _serializar_estado_grafo) y armar el
    #    cuerpo de la respuesta HTTP, que mantiene su forma previa
    #    (clasificacion/extraccion/validacion en el nivel superior) por
    #    compatibilidad con quien ya consume la API. La validación
    #    Pydantic puede fallar precisamente porque el clasificador o el
    #    extractor no llegaron a producir resultado, así que acá no se
    #    puede asumir que ninguno de los dos exista.
    estado_completo = _serializar_estado_grafo(resultado) if resultado is not None else None

    if estado_completo is not None:
        extraccion = estado_completo.get("extraccion")
        cuerpo_resultado = {
            "clasificacion": estado_completo.get("clasificacion"),
            "extraccion": extraccion,
            "validacion": {
                "validacion_ok": estado_completo.get("validacion_ok"),
                "errores_validacion": estado_completo.get("errores_validacion"),
            },
        }
        nivel_urgencia = extraccion.get("nivel_urgencia") if extraccion else None
    else:
        cuerpo_resultado = {}
        nivel_urgencia = None

    # 7. Persistir en OCI el estado COMPLETO que llegó del flujo (no solo
    #    los campos que hoy conocemos), para no tener que tocar esto cuando
    #    MF-09/MF-10/MF-11/MF-19 agreguen campos nuevos. Reprocesar el mismo
    #    documento_id sobrescribe el resultado anterior (sin versionado
    #    todavía; ver docs/persistencia-resultados.md).
    #
    #    `error` queda en None cuando el error_tecnico viene de
    #    `fallos_tecnicos` (MF-19) sin excepción real: acá se copia ese
    #    detalle también, para que alguien que filtre resultados por el
    #    campo `error` (en vez de bucear en `resultado.fallos_tecnicos`)
    #    igual vea por qué el documento terminó en errores_tecnicos/.
    error_persistido = error_tecnico
    if error_persistido is None and fallos_tecnicos:
        # str(...) por elemento: `fallos_tecnicos` no tiene todavía un
        # contrato cerrado (MF-19 hoy pone strings, pero nada impide que
        # más adelante lleven una estructura más rica, p.ej. un dict por
        # nodo), así que no se puede asumir que cada elemento ya sea str.
        error_persistido = "; ".join(str(fallo) for fallo in fallos_tecnicos)

    # Un único timestamp para todo lo que se persiste de esta corrida: el
    # campo `timestamp` del envelope y el nombre de archivo del evento de
    # historial (MF-15, paso 7b) tienen que referirse al mismo instante.
    momento = datetime.now(timezone.utc)

    envelope = {
        "documento_id": documento_id,
        "estado": estado,
        "timestamp": momento.isoformat(),
        "oci_object_name_original": object_name,
        "nivel_urgencia": nivel_urgencia,
        "resultado": estado_completo,
        "error": error_persistido,
    }
    # `urgente` (contrato de MF-11) se copia a nivel superior solo cuando el
    # estado lo trae, igual que nivel_urgencia, para filtrar sin desanidar.
    if estado_completo is not None and "urgente" in estado_completo:
        envelope["urgente"] = estado_completo["urgente"]

    try:
        oci_object_name_resultado = storage.upload_resultado(
            documento_id, estado, envelope
        )
        persistencia_ok = True
    except PersistenciaOCIError as exc:
        # Un fallo al guardar el RESULTADO no debe tirar abajo una respuesta
        # cuyo procesamiento sí fue exitoso.
        logger.error(
            "No se pudo persistir el resultado de documento_id=%s: %s",
            documento_id, exc,
        )
        oci_object_name_resultado = None
        persistencia_ok = False

    # 7b. Historial de triaje (MF-15): a diferencia de `procesados/*`, que
    #     guarda solo el ÚLTIMO resultado conocido, acá cada corrida queda
    #     como un evento nuevo bajo `historial/{documento_id}/`, sin pisar
    #     las anteriores (ver docs/historial-triaje.md).
    agentes_ejecutados: list[str] = []
    if estado_completo is not None:
        agentes_ejecutados.append("clasificador")
        # MF-19: el nodo extractor corta ANTES de llamar a ningún LLM si
        # el clasificador ya agotó Gemini y el fallback (no tiene sentido
        # gastar cuota del Extractor sin una clasificación válida) -- ver
        # app/graph/graph.py::nodo_extractor. Cuando eso pasa, el estado
        # nunca llega a tener la clave "extraccion". Si el extractor SÍ
        # corrió (con éxito o degradado por su propio fallo técnico),
        # "extraccion" está presente sin importar fallos_tecnicos.
        extractor_omitido = bool(fallos_tecnicos) and "extraccion" not in estado_completo
        if not extractor_omitido:
            agentes_ejecutados.append("extractor")
        agentes_ejecutados.append("validacion_pydantic")

    clasificacion_persistida = estado_completo.get("clasificacion") if estado_completo else None
    resumen = {
        # Autoevaluación cruda del modelo (MF-05/MF-06), un solo número de
        # Gemini -- se mantiene aparte de score_confianza_final (MF-10):
        # responde una pregunta distinta ("qué pensó el modelo" vs. "en
        # qué confiamos al final", ya combinado con reglas de completitud).
        "score_confianza_clasificacion": (
            clasificacion_persistida.get("score_confianza_clasificacion")
            if clasificacion_persistida
            else None
        ),
        # MF-10: score combinado (autoevaluación + completitud/consistencia)
        # y su categoría ("Alta"/"Media"/"Baja") -- es la señal que
        # nodo_routing_condicional (MF-11) usa para decidir destino_principal.
        # Mismo criterio que destino_principal: solo si el estado las trae,
        # sin inventar un valor cuando MF-10 todavía no está integrado.
        "score_confianza_final": (
            estado_completo.get("score_confianza_final") if estado_completo else None
        ),
        "categoria_confianza": (
            estado_completo.get("categoria_confianza") if estado_completo else None
        ),
        "destino_principal": destino_principal,
        "requiere_auditoria_humana": (
            estado_completo.get("requiere_auditoria_humana") if estado_completo else None
        ),
        "validacion_ok": validacion_ok,
    }

    # `proveedor_modelo`: MF-19 (todavía no integrado en develop) agrega al
    # estado `metadata_clasificacion`/`metadata_extraccion`, cada uno con
    # {proveedor_usado, modelo_usado, fallback_utilizado, intentos_principal,
    # intentos_fallback} -- ver docs/historial-triaje.md. Se copian tal
    # cual, por agente, mismo criterio que destino_principal: nunca se
    # inventan. Si el estado no las trae (MF-19 sin integrar) o el
    # Extractor se omitió (fallo total del Clasificador: nunca llega a
    # correr, así que nunca genera metadata_extraccion), queda el mismo
    # placeholder de siempre.
    _METADATA_NO_DISPONIBLE = "no_disponible (pendiente de que MF-19 lo exponga en el estado)"
    metadata_clasificacion = estado_completo.get("metadata_clasificacion") if estado_completo else None
    metadata_extraccion = estado_completo.get("metadata_extraccion") if estado_completo else None

    recorrido = {
        "agentes_ejecutados": agentes_ejecutados,
        "proveedor_modelo": {
            "clasificador": metadata_clasificacion if metadata_clasificacion is not None else _METADATA_NO_DISPONIBLE,
            "extractor": metadata_extraccion if metadata_extraccion is not None else _METADATA_NO_DISPONIBLE,
        },
        "fallos_tecnicos": fallos_tecnicos,
    }

    evento_historial = {**envelope, "resumen": resumen, "recorrido": recorrido}

    try:
        oci_object_name_historial = storage.upload_historial(
            documento_id, momento, evento_historial
        )
        historial_ok = True
    except PersistenciaOCIError as exc:
        # Igual que con upload_resultado: un fallo acá no debe tirar abajo
        # una respuesta cuyo procesamiento (y persistencia en procesados/)
        # sí fue exitoso.
        logger.error(
            "No se pudo guardar el historial de triaje de documento_id=%s: %s",
            documento_id, exc,
        )
        oci_object_name_historial = None
        historial_ok = False

    # 8. Construir la respuesta del flujo integrado
    respuesta = {
        "status": "error" if es_error_tecnico else "procesado",
        "documento_id": documento_id,
        "canal_origen": canal_origen,
        "nombre_archivo": archivo.filename,
        "tipo_contenido": archivo.content_type,
        "oci_object_name": object_name,
        "estado": estado,
        "persistencia_ok": persistencia_ok,
        "oci_object_name_resultado": oci_object_name_resultado,
        "historial_ok": historial_ok,
        "oci_object_name_historial": oci_object_name_historial,
        **cuerpo_resultado,
        "mensaje": (
            "Fallo técnico al procesar el documento"
            if es_error_tecnico
            else "Documento procesado correctamente por MediFlow"
        ),
    }

    if es_error_tecnico:
        return JSONResponse(status_code=500, content=respuesta)

    return respuesta