import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.services.oci_storage_service import OCIStorageService, PersistenciaOCIError
from app.graph.graph import grafo_mediflow
from app.schemas.documento import DocumentoEntrada

logger = logging.getLogger("mediflow.app.api.routes")

router = APIRouter()


def determinar_estado(validacion_ok: bool, hubo_excepcion: bool) -> str:
    """
    Determina bajo cuál de los 3 estados (ver ESTADOS_A_PREFIJO en
    oci_storage_service.py) se persiste el resultado del flujo.

    Hoy es la única señal disponible: si el grafo lanzó una excepción
    técnica real (proveedor/modelo, un nodo que falla) el resultado es
    error_tecnico; si corrió pero la validación estructural no pasó, es
    auditoria_humana; si todo salió bien, procesado_exitoso. Cuando
    MF-09/MF-10/MF-11 aporten la lógica real de consistencia, confianza y
    enrutamiento a revisión humana, esta es la única función que hay que
    actualizar.
    """
    if hubo_excepcion:
        return "error_tecnico"
    if not validacion_ok:
        return "auditoria_humana"
    return "procesado_exitoso"


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

    # 3. Guardar documento original en OCI
    storage = OCIStorageService()

    object_name = storage.upload_document(
        document_id=documento_id,
        content=contenido,
        filename=archivo.filename,
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
    estado = determinar_estado(
        validacion_ok=validacion_ok, hubo_excepcion=hubo_excepcion
    )

    # 6. Construir el resultado del flujo integrado (si corrió). La
    #    validación Pydantic puede fallar precisamente porque el
    #    clasificador o el extractor no llegaron a producir resultado, así
    #    que acá no se puede asumir que ninguno de los dos exista.
    if resultado is not None:
        clasificacion = resultado.get("clasificacion")
        extraccion = resultado.get("extraccion")
        cuerpo_resultado = {
            "clasificacion": clasificacion.model_dump() if clasificacion else None,
            "extraccion": extraccion.model_dump() if extraccion else None,
            "validacion": {
                "validacion_ok": resultado["validacion_ok"],
                "errores_validacion": resultado["errores_validacion"],
            },
        }
        nivel_urgencia = (
            cuerpo_resultado["extraccion"].get("nivel_urgencia")
            if cuerpo_resultado["extraccion"]
            else None
        )
    else:
        cuerpo_resultado = {}
        nivel_urgencia = None

    # 7. Persistir en OCI el estado COMPLETO que llegó del flujo (no solo
    #    los campos que hoy conocemos), para no tener que tocar esto cuando
    #    MF-09/MF-10/MF-11/MF-19 agreguen campos nuevos. Reprocesar el mismo
    #    documento_id sobrescribe el resultado anterior (sin versionado
    #    todavía; ver docs/persistencia-resultados.md).
    envelope = {
        "documento_id": documento_id,
        "estado": estado,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "oci_object_name_original": object_name,
        "nivel_urgencia": nivel_urgencia,
        "resultado": cuerpo_resultado or None,
        "error": error_tecnico,
    }

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

    # 8. Construir la respuesta del flujo integrado
    respuesta = {
        "status": "error" if hubo_excepcion else "procesado",
        "documento_id": documento_id,
        "canal_origen": canal_origen,
        "nombre_archivo": archivo.filename,
        "tipo_contenido": archivo.content_type,
        "oci_object_name": object_name,
        "estado": estado,
        "persistencia_ok": persistencia_ok,
        "oci_object_name_resultado": oci_object_name_resultado,
        **cuerpo_resultado,
        "mensaje": (
            "Fallo técnico al procesar el documento"
            if hubo_excepcion
            else "Documento procesado correctamente por MediFlow"
        ),
    }

    if hubo_excepcion:
        return JSONResponse(status_code=500, content=respuesta)

    return respuesta