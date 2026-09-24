from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel


router = APIRouter()


class DocumentoEntradaTemporal(BaseModel):
    """
    Contrato temporal utilizado por MF-03 para validar la recepción.

    Será reemplazado por el contrato común de MF-02 durante
    la integración del flujo.
    """

    documento_id: str
    canal_origen: str
    nombre_archivo: str
    mime_type: str
    documento_texto: str


@router.post("/documentos")
async def recibir_documento(
    documento_id: str = Form(...),
    canal_origen: str = Form(...),
    archivo: UploadFile = File(...),
):
    """
    Recibe un documento clínico y valida inicialmente
    la solicitud antes de enviarla al workflow de MediFlow.
    """

    contenido = await archivo.read()

    # Alcance inicial de MF-03: pruebas con documentos de texto.
    texto_documento = contenido.decode("utf-8")

    documento = DocumentoEntradaTemporal(
        documento_id=documento_id,
        canal_origen=canal_origen,
        nombre_archivo=archivo.filename,
        mime_type=archivo.content_type or "text/plain",
        documento_texto=texto_documento,
    )

    return {
        "status": "recibido",
        "documento": documento.model_dump(),
        "mensaje": "Documento recibido y validado correctamente",
    }