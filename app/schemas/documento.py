from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DocumentoEntrada(BaseModel):
    """
    Contrato de entrada de documentos para MediFlow.

    Contiene la información general del documento y permite procesar
    tanto documentos con texto disponible como archivos binarios
    (PDF o imágenes) que serán enviados directamente a los agentes.
    """

    # Identificador único utilizado para trazabilidad durante todo el flujo.
    documento_id: str

    # Tipo de archivo recibido por MediFlow.
    tipo_archivo: Literal["PDF", "Imagen", "JSON"]

    # Canal desde el cual se recibió el documento.
    canal_origen: str

    # Metadatos del archivo necesarios para procesamiento multimodal.
    nombre_archivo: str | None = None
    mime_type: str | None = None

    # El documento puede llegar como contenido binario (PDF/imagen)
    # o como texto previamente disponible.
    contenido_bytes: bytes | None = None
    documento_texto: str | None = None

    @model_validator(mode="after")
    def validar_contenido(self) -> "DocumentoEntrada":
        """
        Garantiza que exista contenido procesable.
        El documento debe contener bytes o texto.
        """
        if self.contenido_bytes is None and not self.documento_texto:
            raise ValueError(
                "DocumentoEntrada requiere contenido_bytes o documento_texto"
            )

        return self