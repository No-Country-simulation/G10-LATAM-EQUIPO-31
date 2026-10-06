"""
MF-12: flujo HITL de punta a punta sobre el código REAL de develop.

POST /documentos real (routes.py + nodos reales de validación, confianza y routing) con los agentes LLM
simulados y un bucket de OCI en memoria. Se comprueba que:
  * un documento de confianza no alta se deriva a revision_humana y aparece en la bandeja,
  * APROBAR y RECHAZAR (con motivo) quedan persistidos en historial/ y asociados al documento,
  * las rutas estándar y urgente siguen funcionando igual y no entran a la bandeja.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from app.api import routes, rutas_auditoria
from app.graph import graph
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import Diagnostico, ExtraccionClinica, NivelUrgencia, Paciente, Profesional
from app.services import auditoria_eventos as ev
from app.services import oci_storage_service as oci

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "entradas"


class BucketMemoria:
    """Un único bucket en memoria que usa los MISMOS nombres de objeto que OCIStorageService real
    y expone, además, la interfaz mínima `Almacen` de la bandeja HITL."""

    def __init__(self):
        self.objetos: dict[str, bytes] = {}
        self.fechas: dict[str, datetime] = {}

    # --- lo que usa routes.py (OCIStorageService) ---
    def upload_document(self, document_id, content, filename):
        nombre = f"recibidos/{oci._sanitizar_nombre_archivo(document_id)}_{oci._sanitizar_nombre_archivo(filename)}"
        self._poner(nombre, content)
        return nombre

    def upload_resultado(self, documento_id, estado, resultado):
        nombre = oci._object_name_resultado(documento_id, estado)
        self._poner(nombre, json.dumps(resultado, ensure_ascii=False, default=str).encode())
        return nombre

    def upload_historial(self, documento_id, momento, evento):
        nombre = oci._object_name_historial(documento_id, oci._id_temporal(momento))
        self._poner(nombre, json.dumps(evento, ensure_ascii=False, default=str).encode())
        return nombre

    # --- lo que usa la bandeja HITL (Almacen) ---
    def _poner(self, nombre, contenido):
        self.objetos[nombre] = contenido
        self.fechas[nombre] = datetime.now(timezone.utc)

    def listar(self, prefijo):
        return [(n, self.fechas[n]) for n in self.objetos if n.startswith(prefijo)]

    def leer_json(self, nombre):
        return json.loads(self.objetos[nombre])

    def escribir_json_nuevo(self, nombre, contenido):
        if nombre in self.objetos:
            raise FileExistsError(nombre)
        self._poner(nombre, json.dumps(contenido, ensure_ascii=False).encode())


def _clasificacion(score):
    return Classification(
        tipo_documento=DocumentType.RECETA_MEDICA, especialidad="Medicina General", nivel_prioridad="Rutina",
        score_confianza_clasificacion=score, justificacion="Receta médica.",
    )


def _extraccion(urgencia=NivelUrgencia.NO_URGENTE):
    return ExtraccionClinica(
        paciente=Paciente(nombre_completo="Laura Martínez Gómez", edad=45),
        profesional=Profesional(nombre_completo="Dr. Andrés Ramírez", registro_profesional="MP-45821"),
        diagnosticos=[Diagnostico(descripcion="Hipertensión arterial esencial", codigo_cie10="I10")],
        nivel_urgencia=urgencia,
    )


@pytest.fixture
def entorno(monkeypatch):
    bucket = BucketMemoria()
    monkeypatch.setattr(routes, "OCIStorageService", lambda: bucket)
    monkeypatch.setattr(graph, "ProveedorGemini", lambda: object())
    main.app.dependency_overrides[rutas_auditoria.obtener_almacen] = lambda: bucket

    def procesar(doc_id, score, urgencia=NivelUrgencia.NO_URGENTE):
        monkeypatch.setattr(graph, "clasificar_documento", lambda _d, **_k: _clasificacion(score))
        monkeypatch.setattr(graph, "extraer_datos_clinicos", lambda **_k: _extraccion(urgencia))
        archivo = "01_receta_medica.txt"
        return client.post(
            "/documentos", data={"documento_id": doc_id, "canal_origen": "test"},
            files={"archivo": (archivo, (SAMPLES / archivo).read_bytes(), "text/plain")},
        )

    client = TestClient(main.app)
    yield client, bucket, procesar
    main.app.dependency_overrides.clear()


def test_caso_derivado_a_revision_humana_aparece_en_la_bandeja(entorno):
    client, bucket, procesar = entorno
    r = procesar("HITL-1", score=0.40)
    assert r.status_code == 200 and r.json()["estado"] == "revision_humana"
    assert "procesados/revision_humana/HITL-1.json" in bucket.objetos
    b = client.get("/auditoria/bandeja").json()
    assert [e["documento_id"] for e in b["pendientes"]] == ["HITL-1"]
    item = b["pendientes"][0]
    # lo necesario para revisar: extracción, confianza y motivos tal como los dejó el pipeline
    assert item["resultado"]["extraccion"]["paciente"]["nombre_completo"] == "Laura Martínez Gómez"
    assert item["resultado"]["categoria_confianza"] in ("Media", "Baja")
    assert isinstance(item["resultado"]["motivos_confianza"], list) and item["resultado"]["motivos_confianza"]
    assert item["resultado"]["requiere_auditoria_humana"] is True


def test_aprobar_queda_persistido_y_trazable(entorno):
    client, bucket, procesar = entorno
    procesar("HITL-2", score=0.40)
    resultado_antes = bucket.objetos["procesados/revision_humana/HITL-2.json"]
    r = client.post("/auditoria/HITL-2/decision", json={"decision": "APROBADO", "auditor": "kimberlyn.r"})
    assert r.status_code == 201
    decisiones = [n for n in bucket.objetos if n.startswith("historial/HITL-2/") and n.endswith("_decision.json")]
    assert len(decisiones) == 1
    guardado = bucket.leer_json(decisiones[0])
    assert (guardado["tipo_evento"], guardado["decision"], guardado["auditor"]) == ("decision_humana", "APROBADO", "kimberlyn.r")
    assert guardado["documento_id"] == "HITL-2" and "motivo" not in guardado
    linea = client.get("/documentos/HITL-2/historial").json()["eventos"]
    assert [ev.tipo_evento(e) for e in linea] == ["procesamiento", "decision_humana"]
    assert guardado["evento_referencia"].endswith(linea[0]["evento_id"])
    assert bucket.objetos["procesados/revision_humana/HITL-2.json"] == resultado_antes   # nada se mueve ni se pisa
    b = client.get("/auditoria/bandeja").json()
    assert b["pendientes"] == [] and [e["documento_id"] for e in b["resueltos"]] == ["HITL-2"]


def test_rechazar_con_motivo_queda_persistido_y_trazable(entorno):
    client, bucket, procesar = entorno
    procesar("HITL-3", score=0.40)
    sin_motivo = client.post("/auditoria/HITL-3/decision", json={"decision": "RECHAZADO", "auditor": "ana", "notas": "x"})
    assert sin_motivo.status_code == 422 and not [n for n in bucket.objetos if n.endswith("_decision.json")]
    r = client.post("/auditoria/HITL-3/decision", json={
        "decision": "RECHAZADO", "auditor": "ana", "motivo": "INCONSISTENTE", "notas": "Dosis incompatible con el diagnóstico"})
    assert r.status_code == 201
    guardado = bucket.leer_json(next(n for n in bucket.objetos if n.endswith("_decision.json")))
    assert (guardado["decision"], guardado["motivo"], guardado["notas"], guardado["auditor"]) == (
        "RECHAZADO", "INCONSISTENTE", "Dosis incompatible con el diagnóstico", "ana")
    assert client.post("/auditoria/HITL-3/decision", json={"decision": "APROBADO", "auditor": "kim"}).status_code == 409
    assert client.get("/auditoria/bandeja").json()["pendientes"] == []


def test_la_decision_queda_con_huella_cuando_el_procesamiento_ya_la_trae(entorno):
    """MF-22 aún no está en develop: se simula un evento que ya trae `huella_sha256` y se comprueba que se copia."""
    client, bucket, procesar = entorno
    procesar("HITL-4", score=0.40)
    nombre = next(n for n in bucket.objetos if n.startswith("historial/HITL-4/"))
    evento = bucket.leer_json(nombre)
    evento[ev.CAMPO_HUELLA] = "A" * 64
    bucket.objetos[nombre] = json.dumps(evento).encode()
    r = client.post("/auditoria/HITL-4/decision", json={"decision": "APROBADO", "auditor": "kim"})
    assert r.json()[ev.CAMPO_HUELLA] == "a" * 64


def test_rutas_estandar_y_urgente_siguen_funcionando_y_no_entran_a_la_bandeja(entorno):
    client, bucket, procesar = entorno
    estandar = procesar("STD-1", score=0.95)
    urgente = procesar("URG-1", score=0.95, urgencia=NivelUrgencia.URGENTE)
    assert (estandar.status_code, estandar.json()["estado"]) == (200, "estandar")
    assert (urgente.status_code, urgente.json()["estado"]) == (200, "urgente")
    assert "procesados/estandar/STD-1.json" in bucket.objetos and "procesados/urgente/URG-1.json" in bucket.objetos
    assert client.get("/auditoria/bandeja").json()["total_pendientes"] == 0
    for doc in ("STD-1", "URG-1"):    # no se puede auditar lo que no fue derivado a revisión humana
        assert client.post(f"/auditoria/{doc}/decision", json={"decision": "APROBADO", "auditor": "kim"}).status_code == 409
    assert not [n for n in bucket.objetos if n.endswith("_decision.json")]


def test_un_urgente_de_baja_confianza_va_a_revision_humana_conservando_la_urgencia(entorno):
    """Caso 'gris' con MF-14: urgente=True y destino revision_humana. HITL no envía alertas; solo lo muestra."""
    client, bucket, procesar = entorno
    r = procesar("URG-BAJA", score=0.40, urgencia=NivelUrgencia.URGENTE)
    assert r.json()["estado"] == "revision_humana"
    item = client.get("/auditoria/bandeja").json()["pendientes"][0]
    assert item["urgente"] is True
