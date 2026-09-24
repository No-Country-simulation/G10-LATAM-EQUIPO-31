"""Prueba manual de conexion con OCI Object Storage (MF-04).

Sube un documento de prueba a recibidos/, lo recupera y verifica
que el contenido coincida. Ejecutar desde la raiz del repo:

    python samples/test_oci_connection.py
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.oci_storage_service import OCIStorageService


def generate_document_id() -> str:
    year = datetime.now(timezone.utc).year
    suffix = uuid.uuid4().hex[:8].upper()
    return f"DOC-{year}-{suffix}"


def main():
    service = OCIStorageService()

    document_id = generate_document_id()
    filename = "documento_prueba.txt"
    content = f"Documento de prueba MF-04 - id {document_id}".encode("utf-8")

    print(f"[1/3] Subiendo documento de prueba con id: {document_id}")
    object_name = service.upload_document(document_id, content, filename)
    print(f"      OK -> subido como: {object_name}")

    print("[2/3] Recuperando el documento subido...")
    retrieved = service.get_document(object_name)
    print(f"      OK -> recuperados {len(retrieved)} bytes")

    assert retrieved == content, "El contenido recuperado no coincide con el original"
    print("[3/3] Contenido verificado: coincide con el original")

    print("\nPrueba de conexion con OCI Object Storage: OK")


if __name__ == "__main__":
    main()
