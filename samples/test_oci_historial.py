"""Prueba manual del historial de triaje (MF-15) contra OCI Object Storage real.

A diferencia de samples/test_oci_resultado.py (que sube un resultado de
ejemplo inventado a mano), este script corre el flujo HTTP completo
(POST /documentos) con los 8 archivos reales de samples/entradas/, para
demostrar contra el bucket de verdad que:

  1. reprocesar el mismo documento_id NO pisa el historial anterior
     (a diferencia de procesados/, que sigue pisando);
  2. el recorrido (agentes_ejecutados) refleja correctamente el caso en
     que el clasificador falla del todo y el extractor se omite.

Gemini y Groq están SIMULADOS acá (no se llama a ningún proveedor real
ni se necesita ninguna API key de modelos) -- únicamente OCI Object
Storage es real, para guardar y para recuperar (usa las credenciales del
.env del usuario, igual que samples/test_oci_resultado.py).

Ejecutar desde la raíz del repo:

    python samples/test_oci_historial.py
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.graph import graph
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import Diagnostico, ExtraccionClinica, NivelUrgencia, Paciente, Profesional
from app.services.oci_storage_service import OCIStorageService

SAMPLES_DIR = Path(__file__).resolve().parent / "entradas"
MIME_POR_EXTENSION = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}

RUN_ID = uuid.uuid4().hex[:6].upper()

# Estado mutable que controla el comportamiento de los proveedores
# SIMULADOS entre escenarios (no hay llamadas de red reales acá).
MODO = {"gemini_ok": True, "groq_ok": True}


def _tipo_por_nombre(nombre_archivo: str) -> DocumentType:
    nombre = nombre_archivo.lower()
    if "receta" in nombre:
        return DocumentType.RECETA_MEDICA
    if "informe" in nombre:
        return DocumentType.INFORME_ESTUDIO_DIAGNOSTICO
    if "orden" in nombre:
        return DocumentType.ORDEN_SOLICITUD_PROCEDIMIENTO
    if "epicrisis" in nombre:
        return DocumentType.EPICRISIS_INFORME_ALTA
    if "certificado" in nombre:
        return DocumentType.CERTIFICADO_MEDICO
    return DocumentType.NO_CLASIFICADO


def _fake_clasificar_documento(documento) -> Classification:
    """Reemplaza a app.agents.classifier.clasificar_documento. Simula
    Gemini como proveedor principal y un 'Groq' de fallback, según MODO."""
    if MODO["gemini_ok"]:
        return Classification(
            tipo_documento=_tipo_por_nombre(documento.nombre_archivo),
            especialidad="Medicina General",
            nivel_prioridad="Rutina",
            score_confianza_clasificacion=0.93,
            justificacion="[SIMULADO] Gemini respondió correctamente.",
        )
    if MODO["groq_ok"]:
        return Classification(
            tipo_documento=_tipo_por_nombre(documento.nombre_archivo),
            especialidad="Medicina General",
            nivel_prioridad="Rutina",
            score_confianza_clasificacion=0.80,
            justificacion="[SIMULADO] Gemini falló (503 simulado); respondió el fallback Groq.",
        )
    raise RuntimeError(
        "[SIMULADO] Fallo técnico total del Clasificador: "
        "Gemini (503 simulado) y Groq (429 simulado) fallaron."
    )


def _fake_extraer_datos_clinicos(documento, clasificacion, proveedor=None, **_kwargs) -> ExtraccionClinica:
    """Reemplaza a app.agents.extractor.extraer_datos_clinicos. Mismo
    criterio de simulación que el clasificador."""
    if MODO["gemini_ok"]:
        origen = "Gemini"
    elif MODO["groq_ok"]:
        origen = "Groq (fallback)"
    else:
        raise RuntimeError(
            "[SIMULADO] Fallo técnico total del Extractor: "
            "Gemini (503 simulado) y Groq (429 simulado) fallaron."
        )
    return ExtraccionClinica(
        paciente=Paciente(nombre_completo="Paciente de Prueba MF-15", numero_documento="00000000"),
        profesional=Profesional(
            nombre_completo="Dr. Prueba", registro_profesional="MP-0000", especialidad="Medicina General"
        ),
        diagnosticos=[Diagnostico(descripcion="Diagnóstico simulado")],
        nivel_urgencia=NivelUrgencia.NO_URGENTE,
        observaciones=f"[SIMULADO] Datos extraídos por {origen}.",
    )


class _ProveedorGeminiFalso:
    """Reemplaza a app.services.gemini_provider.ProveedorGemini: no exige
    ninguna API key (nodo_extractor lo instancia siempre, aunque
    extraer_datos_clinicos esté mockeado)."""

    def __init__(self, *args, **kwargs):
        pass


graph.clasificar_documento = _fake_clasificar_documento
graph.extraer_datos_clinicos = _fake_extraer_datos_clinicos
graph.ProveedorGemini = _ProveedorGeminiFalso

app = FastAPI()
app.include_router(routes.router)
client = TestClient(app, raise_server_exceptions=False)

# OCIStorageService REAL: guarda y recupera contra el bucket de verdad
# (usa el .env del usuario, igual que samples/test_oci_resultado.py).
storage = OCIStorageService()


def _enviar(documento_id: str, filename: str) -> dict:
    contenido = (SAMPLES_DIR / filename).read_bytes()
    content_type = MIME_POR_EXTENSION[Path(filename).suffix]
    respuesta = client.post(
        "/documentos",
        data={"documento_id": documento_id, "canal_origen": "simulacion-mf15"},
        files={"archivo": (filename, contenido, content_type)},
    )
    return respuesta.json()


def probar_reproceso_sin_pisar(filename: str) -> None:
    """Escenario 1 (flujo normal, simulado): procesa el mismo
    documento_id DOS veces y confirma -contra OCI real- que quedan DOS
    eventos de historial distintos, mientras que procesados/ sigue
    pisando (eso ya lo prueba MF-13)."""
    MODO["gemini_ok"], MODO["groq_ok"] = True, True
    documento_id = f"MF15-SIM-{RUN_ID}-{Path(filename).stem}"

    print(f"\n--- {filename} (documento_id={documento_id}) ---")
    body_1 = _enviar(documento_id, filename)
    body_2 = _enviar(documento_id, filename)

    assert body_1["historial_ok"] is True and body_2["historial_ok"] is True
    obj_1 = body_1["oci_object_name_historial"]
    obj_2 = body_2["oci_object_name_historial"]
    assert obj_1 != obj_2, "Dos corridas seguidas generaron el MISMO objeto de historial"
    print(f"  [1/2] primer evento:  {obj_1}")
    print(f"  [2/2] segundo evento: {obj_2}")

    evento_1 = storage.get_historial(obj_1)
    evento_2 = storage.get_historial(obj_2)
    assert evento_1["timestamp"] != evento_2["timestamp"]
    assert evento_1["recorrido"]["agentes_ejecutados"] == [
        "clasificador", "extractor", "validacion_pydantic",
    ]
    print(f"      OK -> dos eventos recuperados de OCI, con timestamps distintos")
    print(f"      procesados/: sigue en un solo objeto -> {body_2['oci_object_name_resultado']}")


def probar_escenario_fallback() -> None:
    """Escenario 2 (simulado): Gemini falla, el fallback 'Groq' responde
    bien. El documento sigue llegando a estandar/, y el historial queda
    con el detalle en clasificacion.justificacion / extraccion.observaciones
    (MF-19 todavía no expone proveedor_modelo de forma estructurada, ver
    docs/historial-triaje.md)."""
    MODO["gemini_ok"], MODO["groq_ok"] = False, True
    documento_id = f"MF15-SIM-{RUN_ID}-fallback-groq"

    print(f"\n--- Escenario: Gemini falla, fallback Groq responde (documento_id={documento_id}) ---")
    body = _enviar(documento_id, "01_receta_medica.txt")
    assert body["estado"] == "estandar", body
    obj = body["oci_object_name_historial"]
    evento = storage.get_historial(obj)
    print(f"  evento: {obj}")
    print(f"  agentes_ejecutados: {evento['recorrido']['agentes_ejecutados']}")
    print(f"  justificación clasificación: {evento['resultado']['clasificacion']['justificacion']}")


def probar_escenario_fallo_total() -> None:
    """Escenario 3 (simulado): Gemini y Groq fallan los dos. El grafo
    lanza una excepción real (así se comporta hoy, sin MF-19 mergeado en
    esta rama) -> error_tecnico por excepción, y el historial debe
    reflejar agentes_ejecutados vacío (no se puede saber en qué nodo
    estaba cuando crasheó)."""
    MODO["gemini_ok"], MODO["groq_ok"] = False, False
    documento_id = f"MF15-SIM-{RUN_ID}-fallo-total"

    print(f"\n--- Escenario: Gemini y Groq fallan los dos (documento_id={documento_id}) ---")
    body = _enviar(documento_id, "01_receta_medica.txt")
    assert body["estado"] == "error_tecnico", body
    obj = body["oci_object_name_historial"]
    evento = storage.get_historial(obj)
    print(f"  evento: {obj}")
    print(f"  agentes_ejecutados: {evento['recorrido']['agentes_ejecutados']}")
    print(f"  error: {evento['error']}")
    assert evento["recorrido"]["agentes_ejecutados"] == []


def main():
    print(f"=== MF-15: historial de triaje -- prueba manual (run {RUN_ID}) ===")
    print("Gemini y Groq: SIMULADOS (sin claves reales de modelos).")
    print("OCI Object Storage: REAL (credenciales de tu .env).")

    for archivo in sorted(SAMPLES_DIR.iterdir()):
        if archivo.suffix in MIME_POR_EXTENSION:
            probar_reproceso_sin_pisar(archivo.name)

    probar_escenario_fallback()
    probar_escenario_fallo_total()

    print("\nPrueba manual de historial de triaje (MF-15): OK")
    print(
        f"Los objetos de esta corrida quedaron en el bucket bajo el prefijo "
        f"historial/MF15-SIM-{RUN_ID}-*/ (no se borran automáticamente)."
    )


if __name__ == "__main__":
    main()
