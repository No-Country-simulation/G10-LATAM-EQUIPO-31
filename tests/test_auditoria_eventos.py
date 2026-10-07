"""MF-12: lógica de la bandeja HITL sobre historial/ (almacén en memoria, sin OCI ni LLM)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services import auditoria_eventos as ev

T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


class AlmacenMemoria:
    def __init__(self):
        self.objetos: dict[str, bytes] = {}
        self.fechas: dict[str, datetime] = {}

    def poner(self, nombre, contenido, fecha):
        self.objetos[nombre] = json.dumps(contenido).encode()
        self.fechas[nombre] = fecha

    def listar(self, prefijo):
        return [(n, self.fechas[n]) for n in self.objetos if n.startswith(prefijo)]

    def leer_json(self, nombre):
        return json.loads(self.objetos[nombre])

    def escribir_json_nuevo(self, nombre, contenido):
        if nombre in self.objetos:
            raise FileExistsError(nombre)
        self.poner(nombre, contenido, datetime.now(timezone.utc))


def procesar(a, doc_id, estado, momento, urgente=False, tipo="Receta Medica", huella=None, historial=True):
    """Simula lo que escribe POST /documentos: resultado (se sobrescribe) + evento de historial (se agrega)."""
    clave = ev.sanitizar_clave(doc_id)
    evento = {
        "documento_id": doc_id, "estado": estado, "timestamp": momento.isoformat(),
        "nivel_urgencia": "urgente" if urgente else "no_urgente", "urgente": urgente,
        "resultado": {"clasificacion": {"tipo_documento": tipo}, "categoria_confianza": "Media"},
    }
    if huella:
        evento[ev.CAMPO_HUELLA] = huella
    a.poner(f"{ev.CARPETAS_ESTADO[estado]}{clave}.json", evento, momento)
    if historial:
        a.poner(f"historial/{clave}/{momento.strftime('%Y%m%dT%H%M%S%f')}.json", evento, momento)


def test_bandeja_solo_lista_revision_humana_y_ordena_por_fecha():
    a = AlmacenMemoria()
    procesar(a, "A", "revision_humana", T0)
    procesar(a, "B", "revision_humana", T0 + timedelta(hours=1), urgente=True)
    procesar(a, "C", "estandar", T0 + timedelta(hours=2))
    procesar(a, "D", "urgente", T0 + timedelta(hours=3))
    procesar(a, "E", "error_tecnico", T0 + timedelta(hours=4))
    b = ev.construir_bandeja(a)
    assert [e["documento_id"] for e in b["pendientes"]] == ["B", "A"] and b["total_pendientes"] == 2
    assert b["resueltos"] == [] and b["avisos"] == []


def test_aprobar_resuelve_y_queda_en_la_linea_de_tiempo():
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0, urgente=True)
    r = ev.registrar_decision(a, "D1", "APROBADO", " kim ", ahora=T0 + timedelta(minutes=5))
    assert r["tipo_evento"] == ev.TIPO_DECISION and r["decision"] == "APROBADO" and r["auditor"] == "kim"
    assert "motivo" not in r and r["urgente"] is True and r["tipo_documento"] == "Receta Medica"
    b = ev.construir_bandeja(a)
    assert b["pendientes"] == [] and [e["documento_id"] for e in b["resueltos"]] == ["D1"]
    linea = ev.historial_de(a, "D1")
    assert [ev.tipo_evento(e) for e in linea] == [ev.TIPO_PROCESAMIENTO, ev.TIPO_DECISION]
    assert linea[1]["evento_referencia"].endswith(linea[0]["evento_id"])   # apunta al procesamiento sobre el que se decidió


def test_rechazar_guarda_motivo_notas_y_auditor_sin_tocar_archivos_existentes():
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0)
    antes = dict(a.objetos)
    r = ev.registrar_decision(a, "D1", "RECHAZADO", "ana", "no se lee la dosis", motivo="ILEGIBLE", ahora=T0 + timedelta(minutes=1))
    assert (r["decision"], r["motivo"], r["notas"], r["auditor"]) == ("RECHAZADO", "ILEGIBLE", "no se lee la dosis", "ana")
    nuevos = set(a.objetos) - set(antes)
    assert len(nuevos) == 1 and next(iter(nuevos)).endswith("_decision.json")
    assert all(a.objetos[n] == antes[n] for n in antes), "las decisiones no modifican ningún objeto existente"
    assert ev.construir_bandeja(a)["pendientes"] == []


def test_reproceso_en_la_misma_carpeta_vuelve_a_pendiente():
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0)
    ev.registrar_decision(a, "D1", "APROBADO", "kim", ahora=T0 + timedelta(minutes=1))
    procesar(a, "D1", "revision_humana", T0 + timedelta(hours=1))
    assert [e["documento_id"] for e in ev.construir_bandeja(a)["pendientes"]] == ["D1"]
    assert ev.construir_bandeja(a)["resueltos"] == []


def test_reproceso_a_otra_carpeta_no_deja_pendiente_la_copia_vieja():
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0)
    procesar(a, "D1", "estandar", T0 + timedelta(hours=1))
    assert ev.construir_bandeja(a)["pendientes"] == []
    with pytest.raises(ev.DocumentoNoPendiente):
        ev.registrar_decision(a, "D1", "APROBADO", "kim")


def test_solo_se_decide_sobre_pendientes():
    a = AlmacenMemoria()
    procesar(a, "OK", "estandar", T0)
    procesar(a, "P", "revision_humana", T0)
    with pytest.raises(ev.DocumentoNoEncontrado):
        ev.registrar_decision(a, "NOPE", "APROBADO", "kim")
    with pytest.raises(ev.DocumentoNoPendiente):
        ev.registrar_decision(a, "OK", "APROBADO", "kim")
    ev.registrar_decision(a, "P", "APROBADO", "kim")
    with pytest.raises(ev.DocumentoNoPendiente):   # una decisión no se cambia ni se repite
        ev.registrar_decision(a, "P", "RECHAZADO", "otro", "x", motivo="OTRO")


@pytest.mark.parametrize("args,kw", [
    (("TALVEZ", "kim"), {}),                                   # solo APROBADO o RECHAZADO
    (("CORREGIDO", "kim", "n"), {}),                           # NO existe corrección manual
    (("APROBADO", "  "), {}),                                  # auditor obligatorio
    (("APROBADO", "kim"), {"motivo": "OTRO"}),                 # el motivo solo va al rechazar
    (("RECHAZADO", "kim", "n"), {}),                           # rechazo sin motivo
    (("RECHAZADO", "kim", "n"), {"motivo": "INVENTADO"}),      # motivo fuera del catálogo
    (("RECHAZADO", "kim", "  "), {"motivo": "OTRO"}),          # rechazo sin notas
])
def test_validaciones_de_decision(args, kw):
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0)
    n_objetos = len(a.objetos)
    with pytest.raises(ev.DecisionInvalida):
        ev.registrar_decision(a, "D1", *args, **kw)
    assert len(a.objetos) == n_objetos and len(ev.construir_bandeja(a)["pendientes"]) == 1


def test_decision_con_reloj_atrasado_igual_queda_despues_del_ultimo_evento():
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0)
    ev.registrar_decision(a, "D1", "APROBADO", "kim", ahora=T0 - timedelta(hours=3))
    assert ev.construir_bandeja(a)["pendientes"] == []
    assert ev.tipo_evento(ev.historial_de(a, "D1")[-1]) == ev.TIPO_DECISION


def test_pendiente_sin_historial_usa_el_resultado_de_procesados():
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0, historial=False)
    assert [e["documento_id"] for e in ev.construir_bandeja(a)["pendientes"]] == ["D1"]
    ev.registrar_decision(a, "D1", "APROBADO", "kim", ahora=T0 + timedelta(minutes=1))
    assert ev.construir_bandeja(a)["pendientes"] == []


def test_id_con_caracteres_raros_usa_la_clave_sanitizada():
    a = AlmacenMemoria()
    doc = "DOC 1:ñ"
    assert ev.sanitizar_clave(doc) == "DOC_1__"
    procesar(a, doc, "revision_humana", T0)
    r = ev.registrar_decision(a, doc, "APROBADO", "kim", ahora=T0 + timedelta(minutes=1))
    assert r["documento_id"] == doc
    assert any(n.startswith("historial/DOC_1__/") and n.endswith("_decision.json") for n in a.objetos)


class AlmacenConCarrera(AlmacenMemoria):
    """Otro auditor ya escribió su decisión, pero esta instancia todavía no la ve al listar (carrera)."""

    def listar(self, prefijo):
        return [x for x in super().listar(prefijo) if not x[0].endswith("_decision.json")]


def test_la_decision_no_se_sobrescribe_si_otro_auditor_escribio_al_mismo_tiempo():
    a = AlmacenConCarrera()
    procesar(a, "D1", "revision_humana", T0)
    ahora = T0 + timedelta(minutes=1)
    nombre = ev.nombre_decision("D1", ahora)
    a.poner(nombre, {"decision": "APROBADO", "auditor": "kim"}, ahora)       # la del otro auditor
    with pytest.raises(ev.DocumentoNoPendiente):
        ev.registrar_decision(a, "D1", "RECHAZADO", "ana", "n", motivo="OTRO", ahora=ahora)
    assert json.loads(a.objetos[nombre]) == {"decision": "APROBADO", "auditor": "kim"}   # la primera se conserva


def test_la_huella_del_evento_base_se_copia_a_la_decision_si_existe():
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0, huella="  ABC123  ")
    r = ev.registrar_decision(a, "D1", "APROBADO", "kim", ahora=T0 + timedelta(minutes=1))
    assert r[ev.CAMPO_HUELLA] == "abc123"


def test_sin_huella_la_decision_se_guarda_igual_y_sin_el_campo():
    a = AlmacenMemoria()
    procesar(a, "D1", "revision_humana", T0)          # develop todavía no escribe huella (MF-22)
    r = ev.registrar_decision(a, "D1", "RECHAZADO", "kim", "n", motivo="OTRO", ahora=T0 + timedelta(minutes=1))
    assert ev.CAMPO_HUELLA not in r


def test_un_objeto_corrupto_no_tumba_la_bandeja_y_el_limite_avisa():
    a = AlmacenMemoria()
    procesar(a, "OK", "revision_humana", T0)
    procesar(a, "MAL", "revision_humana", T0 + timedelta(hours=1))
    clave_mal = [n for n in a.objetos if n.startswith("historial/MAL/")][0]
    a.objetos[clave_mal] = b"{no es json"
    b = ev.construir_bandeja(a)
    assert [e["documento_id"] for e in b["pendientes"]] == ["OK"] and any("No se pudo leer" in x for x in b["avisos"])
    b2 = ev.construir_bandeja(a, limite=1)
    assert b2["total_pendientes"] == 2 and any("Se muestran los 1" in x for x in b2["avisos"])
