from fastapi import APIRouter, File, Form, UploadFile

from app.services.oci_storage_service import OCIStorageService
from app.graph.graph import grafo_mediflow
from app.schemas.documento import DocumentoEntrada


router = APIRouter()


@router.post("/documentos")
async def recibir_documento(
    documento_id: str = Form(...),
    canal_origen: str = Form(...),
    archivo: UploadFile = File(...)
):
    # 1. Leer el archivo recibido
    contenido = await archivo.read()

    # 2. Guardar documento original en OCI
    storage = OCIStorageService()

    object_name = storage.upload_document(
        document_id=documento_id,
        content=contenido,
        filename=archivo.filename,
    )

    # 3. Preparar contenido según el tipo de archivo
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
        raise ValueError(f"Tipo de archivo no soportado: {mime_type}")

    # 4. Construir el contrato común de entrada de MediFlow
    documento = DocumentoEntrada(
        documento_id=documento_id,
        tipo_archivo=tipo_archivo,,
        canal_origen=canal_origen,
        nombre_archivo=archivo.filename,
        mime_type=mime_type,
        contenido_bytes=contenido,
        documento_texto=texto_documento,
    )

    # 5. Ejecutar el flujo de MediFlow mediante LangGraph
    resultado = grafo_mediflow.invoke({
        "documento": documento
    })

    # 6. Construir la respuesta del flujo integrado
    return {
        "status": "procesado",
        "documento_id": documento_id,
        "canal_origen": canal_origen,
        "nombre_archivo": archivo.filename,
        "tipo_contenido": archivo.content_type,
        "oci_object_name": object_name,

        "clasificacion": resultado["clasificacion"].model_dump(),

        "extraccion": resultado["extraccion"].model_dump(),

        "validacion": {
            "validacion_ok": resultado["validacion_ok"],
            "errores_validacion": resultado["errores_validacion"],
        },

        "mensaje": "Documento procesado correctamente por MediFlow",
    }