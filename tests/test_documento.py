from app.schemas.documento import DocumentoEntrada
import pytest
from pydantic import ValidationError


def test_documento_entrada_valido():
    documento = DocumentoEntrada(
        documento_id="DOC-001",
        tipo_archivo="PDF",
        canal_origen="Prueba",
        nombre_archivo="documento.pdf",
        mime_type="application/pdf",
        contenido_bytes=b"contenido-prueba",
    )

    assert documento.documento_id == "DOC-001"
    assert documento.tipo_archivo == "PDF"
    assert documento.contenido_bytes is not None

def test_documento_requiere_contenido():
    with pytest.raises(ValidationError):
        DocumentoEntrada(
            documento_id="DOC-002",
            tipo_archivo="PDF",
            canal_origen="Prueba",
        )