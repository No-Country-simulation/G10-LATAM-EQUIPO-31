"""Esquema provisional de entrada para los agentes de MediFlow.

Draft mientras Manuel (MF-02) define el contrato definitivo de schemas
Pydantic del proyecto. Una vez esten disponibles, este modulo debe
alinearse con ellos (o eliminarse en favor de los suyos).
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class DocumentoEntrada(BaseModel):
    """Documento clinico crudo antes de clasificar."""

    nombre_archivo: str = Field(..., description="Nombre original del archivo, ej. informe_123.pdf")
    mime_type: str = Field(..., description="Tipo MIME, ej. application/pdf, image/png, text/plain")
    contenido_bytes: bytes | None = Field(
        default=None, description="Bytes crudos del documento (PDF o imagen)"
    )
    texto: str | None = Field(
        default=None, description="Texto plano del documento, si ya viene extraido"
    )

    @model_validator(mode="after")
    def _validar_contenido(self) -> "DocumentoEntrada":
        if self.contenido_bytes is None and not self.texto:
            raise ValueError("DocumentoEntrada requiere contenido_bytes o texto")
        return self
