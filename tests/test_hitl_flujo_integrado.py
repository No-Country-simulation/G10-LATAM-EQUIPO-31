"""
MF-12: flujo HITL de punta a punta sobre el código REAL de develop.

POST /documentos real (routes.py + nodos reales de validación, confianza y routing + huella MF-22) y el
OCIStorageService REAL (incluidos listar / leer_json / escribir_json_nuevo del PR #47) sobre un cliente
de OCI simulado que, como el real, fecha cada objeto al escribirlo. Los agentes LLM están simulados.
Se comprueba que:
  * un documento de confianza no alta se deriva a revision_humana y aparece en la bandeja,
  * APROBAR y RECHAZAR (con motivo) quedan persistidos en historial/ y asociados al documento,
    y la decisión hereda el SHA-256 real del contenido,
  * las rutas estándar y urgente siguen funcionando igual y no entran a la bandeja.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from app.api import routes, rutas_auditoria
from app.graph import graph
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import Diagnostico, ExtraccionClinica, Medicamento, NivelUrgencia, Paciente, Profesional
from app.services import auditoria_eventos as ev
from app.services import oci_storage_service as oci
from tests.test_oci_storage_service import ENV_VARS, ObjectStorageClientFalso

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "entradas"


class ClienteOCIConFechas(ObjectStorageClientFalso):
    """El cliente falso de develop deja las fechas en None; el OCI real fecha cada objeto al escribirlo."""

    def put_object(self, namespace_name, bucket_name, object_name, put_object_body, if_none_match=None, content_type=None):
        super().put_object(namespace_name, bucket_name, object_name, put_object_body, if_none_match, content_type)
        ahora = datetime.now(timezone.utc)
        self.fijar_fechas(namespace_name, bucket_name, object_name, time_created=ahora, time_modified=ahora)


class Bucket:
    """Vista de lectura del bucket simulado, para las aserciones."""

    def __init__(self, servicio):
        self.servicio = servicio

    @property
    def objetos(self) -> dict[str, bytes]:
        return {nombre: valor for (_, _, nombre), valor in self.servicio._client._objetos.items()}

    def leer_json(self, nombre):
        return self.servicio.leer_json(nombre)


def _clasificacion(score):
    return Classification(
        tipo_documento=DocumentType.RECETA_MEDICA, especialidad="Medicina General", nivel_prioridad="Rutina",
        score_confianza_clasificacion=score, justificacion="Receta médica.",
    )


def _extraccion(urgencia=NivelUrgencia.NO_URGENTE):
    return ExtraccionClinica(
        paciente=Paciente(nombre_completo="Laura Martínez Gómez", edad=45),
        profesional=Profesional(
            nombre_completo="Dr. Andrés Ramírez",
            registro_profesional="MP-45821",
        ),
        diagnosticos=[
            Diagnostico(
                descripcion="Hipertensión arterial esencial",
                codigo_cie10="I10",
            )
        ],
        medicamentos=[
            Medicamento(nombre="Enalapril", dosis="10mg")
        ],
        nivel_urgencia=urgencia,
    )


@pytest.fixture
def entorno(monkeypatch):
    for clave, valor in ENV_VARS.items():
        monkeypatch.setenv(clave, valor)
    monkeypatch.setattr(oci.oci.config, "validate_config", lambda config: None)
    monkeypatch.setattr(oci.oci.object_storage, "ObjectStorageClient", ClienteOCIConFechas)
    servicio = oci.OCIStorageService()
    monkeypatch.setattr(routes, "OCIStorageService", lambda: servicio)             # POST /documentos
    monkeypatch.setattr(rutas_auditoria, "OCIStorageService", lambda: servicio)    # bandeja y decisión (obtener_almacen real)
    monkeypatch.setattr(graph, "ProveedorGemini", lambda: object())
    bucket = Bucket(servicio)

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


def test_la_decision_hereda_el_sha256_real_del_contenido(entorno):
    """MF-22 ya está en develop: el procesamiento guarda `huella_sha256` y la decisión la copia (solo trazabilidad)."""
    client, bucket, procesar = entorno
    procesar("HITL-4", score=0.40)
    esperada = hashlib.sha256((SAMPLES / "01_receta_medica.txt").read_bytes()).hexdigest()
    evento = next(bucket.leer_json(n) for n in bucket.objetos if n.startswith("historial/HITL-4/"))
    assert evento[ev.CAMPO_HUELLA] == esperada
    r = client.post("/auditoria/HITL-4/decision", json={"decision": "APROBADO", "auditor": "kim"})
    assert r.status_code == 201 and r.json()[ev.CAMPO_HUELLA] == esperada
    guardado = bucket.leer_json(next(n for n in bucket.objetos if n.endswith("_decision.json")))
    assert guardado[ev.CAMPO_HUELLA] == esperada


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
