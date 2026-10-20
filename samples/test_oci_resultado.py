"""Prueba manual de persistencia de RESULTADOS en OCI Object Storage (MF-13).

A diferencia de samples/test_oci_connection.py (que prueba recibidos/), este
script sube y recupera un resultado de ejemplo para cada uno de los estados
soportados (procesados/estandar/, procesados/urgente/,
procesados/revision_humana/ y errores_tecnicos/), contra el bucket real,
usando las credenciales del .env del usuario.

Ejecutar desde la raiz del repo:

    python samples/test_oci_resultado.py
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.oci_storage_service import (
    ESTADO_ERROR_TECNICO,
    ESTADOS_A_PREFIJO,
    OCIStorageService,
)


def generate_document_id() -> str:
    year = datetime.now(timezone.utc).year
    suffix = uuid.uuid4().hex[:8].upper()
    return f"DOC-{year}-{suffix}"


def probar_estado(service: OCIStorageService, estado: str) -> None:
    document_id = generate_document_id()

    es_error = estado == ESTADO_ERROR_TECNICO
    urgente = estado == "urgente"
    nivel_urgencia = "urgente" if urgente else "no_urgente"

    # Misma forma que el envelope que arma POST /documentos: estado completo
    # plano en `resultado` (con los campos del contrato de MF-11) y `urgente`
    # copiado a nivel superior. Un error técnico no tiene resultado.
    envelope = {
        "documento_id": document_id,
        "estado": estado,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "oci_object_name_original": f"recibidos/{document_id}_documento_prueba.txt",
        "nivel_urgencia": None if es_error else nivel_urgencia,
        "resultado": None if es_error else {
            "clasificacion": {"tipo_documento": "Receta Medica"},
            "extraccion": {"nivel_urgencia": nivel_urgencia},
            "validacion_ok": estado != "revision_humana",
            "errores_validacion": [],
            "destino_principal": estado,
            "urgente": urgente,
            "requiere_auditoria_humana": estado == "revision_humana",
        },
        "error": "RuntimeError: fallo técnico simulado" if es_error else None,
    }
    if not es_error:
        envelope["urgente"] = urgente

    print(f"\n--- estado: {estado} (prefijo {ESTADOS_A_PREFIJO[estado]}) ---")
    print(f"[1/2] Subiendo resultado de prueba con documento_id: {document_id}")
    object_name = service.upload_resultado(document_id, estado, envelope)
    print(f"      OK -> subido y verificado como: {object_name}")

    print("[2/2] Recuperando el resultado subido...")
    recuperado = service.get_resultado(document_id, estado)
    assert recuperado == envelope, "El resultado recuperado no coincide con el original"
    print("      OK -> contenido recuperado coincide con el original")


def main():
    service = OCIStorageService()

    for estado in ESTADOS_A_PREFIJO:
        probar_estado(service, estado)

    print("\nPrueba de persistencia de resultados en OCI Object Storage: OK")


if __name__ == "__main__":
    main()
