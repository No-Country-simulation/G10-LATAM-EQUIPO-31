"""MF-12: endpoints HTTP de la bandeja HITL (almacén en memoria, sin OCI ni LLM)."""
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import rutas_auditoria
from tests.test_auditoria_eventos import T0, AlmacenMemoria, procesar


@pytest.fixture
def cliente():
    almacen = AlmacenMemoria()
    procesar(almacen, "D1", "revision_humana", T0, urgente=True)
    app = FastAPI()
    app.include_router(rutas_auditoria.router)
    app.dependency_overrides[rutas_auditoria.obtener_almacen] = lambda: almacen
    return TestClient(app)


def test_flujo_aprobar(cliente):
    assert cliente.get("/auditoria/bandeja").json()["total_pendientes"] == 1
    r = cliente.post("/auditoria/D1/decision", json={"decision": "APROBADO", "auditor": "kim"})
    assert r.status_code == 201 and r.json()["tipo_evento"] == "decision_humana" and r.json()["auditor"] == "kim"
    b = cliente.get("/auditoria/bandeja").json()
    assert b["pendientes"] == [] and [e["documento_id"] for e in b["resueltos"]] == ["D1"]
    eventos = cliente.get("/documentos/D1/historial").json()["eventos"]
    assert [e.get("tipo_evento", "procesamiento") for e in eventos] == ["procesamiento", "decision_humana"]


def test_flujo_rechazar_con_motivo(cliente):
    cuerpo = {"decision": "RECHAZADO", "auditor": "ana", "notas": "dosis ilegible", "motivo": "ILEGIBLE"}
    r = cliente.post("/auditoria/D1/decision", json=cuerpo)
    assert r.status_code == 201 and (r.json()["motivo"], r.json()["notas"]) == ("ILEGIBLE", "dosis ilegible")
    ultimo = cliente.get("/documentos/D1/historial").json()["eventos"][-1]
    assert (ultimo["decision"], ultimo["motivo"], ultimo["auditor"]) == ("RECHAZADO", "ILEGIBLE", "ana")


def test_codigos_de_error(cliente):
    ok = {"decision": "APROBADO", "auditor": "kim"}
    assert cliente.post("/auditoria/NOPE/decision", json=ok).status_code == 404
    assert cliente.get("/documentos/NOPE/historial").status_code == 404
    assert cliente.post("/auditoria/D1/decision", json={"decision": "TALVEZ", "auditor": "k"}).status_code == 422
    assert cliente.post("/auditoria/D1/decision", json={"decision": "CORREGIDO", "auditor": "k", "notas": "n"}).status_code == 422
    assert cliente.post("/auditoria/D1/decision", json={"decision": "RECHAZADO", "auditor": "k"}).status_code == 422
    assert cliente.post("/auditoria/D1/decision", json={"decision": "RECHAZADO", "auditor": "k", "notas": "n"}).status_code == 422
    assert cliente.post("/auditoria/D1/decision", json={"decision": "APROBADO", "auditor": ""}).status_code == 422
    cliente.post("/auditoria/D1/decision", json=ok)
    assert cliente.post("/auditoria/D1/decision", json=ok).status_code == 409


def test_el_contrato_no_acepta_correccion_de_datos_clinicos(cliente):
    cuerpo = {"decision": "APROBADO", "auditor": "kim", "extraccion_corregida": {"paciente": {"nombre_completo": "Ana"}}}
    r = cliente.post("/auditoria/D1/decision", json=cuerpo)     # campo desconocido: se ignora, jamás se guarda
    assert r.status_code == 201 and "extraccion_corregida" not in r.json()
    assert "extraccion_corregida" not in str(cliente.get("/documentos/D1/historial").json())


def test_cada_decision_deja_log_sin_el_texto_de_las_notas(cliente, caplog):
    with caplog.at_level(logging.INFO, logger="mediflow.app.api.rutas_auditoria"):
        cliente.post("/auditoria/D1/decision", json={"decision": "RECHAZADO", "auditor": "ana", "notas": "SECRETO-CLINICO", "motivo": "OTRO"})
        cliente.post("/auditoria/D1/decision", json={"decision": "APROBADO", "auditor": "ana"})     # 409: ya decidido
    texto = caplog.text
    assert "Decisión HITL registrada" in texto and "decision=RECHAZADO" in texto and "auditor='ana'" in texto
    assert "Decisión HITL no registrada" in texto and "DocumentoNoPendiente" in texto
    assert "SECRETO-CLINICO" not in texto
