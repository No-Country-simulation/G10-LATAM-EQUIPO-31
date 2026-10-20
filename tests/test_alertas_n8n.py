"""
tests/test_alertas_n8n.py

Pruebas de MF-14 (alertas de casos urgentes vía n8n): el servicio
app/services/alertas_n8n.py y su integración en POST /documentos.

Nada sale a la red: httpx.post se reemplaza por un doble de prueba, y el
almacenamiento OCI por uno en memoria. El envío real a Slack y correo se
prueba contra el workflow de n8n con samples/probar_alerta_n8n.py (ver
docs/MF-14-alertas-n8n.md).
"""
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.extraccion import ExtraccionClinica, NivelUrgencia, Paciente
from app.services import alertas_n8n

URL_WEBHOOK = "https://n8n.ejemplo.test/webhook/mediflow-urgente"
SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples" / "entradas"
NOMBRE_PACIENTE = "Laura Martínez Gómez"

CLASIFICACION = Classification(
    tipo_documento=DocumentType.INFORME_ESTUDIO_DIAGNOSTICO,
    especialidad="Radiología / Neumología",
    nivel_prioridad="Urgente",
    score_confianza_clasificacion=0.99,
    justificacion="Informe de tomografía con hallazgo crítico.",
)

EXTRACCION = ExtraccionClinica(
    paciente=Paciente(nombre_completo=NOMBRE_PACIENTE, numero_documento="12345678", edad=45),
    nivel_urgencia=NivelUrgencia.URGENTE,
    senales_gravedad=[
        "hallazgo compatible con TEP agudo",
        "defecto de llenado en arteria pulmonar",
        "sobrecarga de cavidades derechas",
        "cuarta señal que no debe enviarse",
    ],
)


class FakePost:
    """Doble de httpx.post: registra las llamadas y puede fallar a pedido."""

    def __init__(self, eventos=None, error=None, status=200):
        self.llamadas = []
        self._eventos = eventos if eventos is not None else []
        self._error = error
        self._status = status

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.llamadas.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        self._eventos.append("alerta")
        if self._error is not None:
            raise self._error
        return httpx.Response(self._status, request=httpx.Request("POST", url))


@pytest.fixture
def webhook_configurado(monkeypatch):
    monkeypatch.setenv(alertas_n8n.ENV_WEBHOOK_URL, URL_WEBHOOK)
    monkeypatch.delenv(alertas_n8n.ENV_WEBHOOK_TOKEN, raising=False)


def _envelope(urgente=True, estado="urgente", **extra):
    return {
        "documento_id": "DOC-ALERTA-001",
        "estado": estado,
        "timestamp": "2026-10-06T12:00:00+00:00",
        "nivel_urgencia": NivelUrgencia.URGENTE,
        "urgente": urgente,
        **extra,
    }


ESTADO_COMPLETO = {
    "clasificacion": CLASIFICACION.model_dump(),
    "extraccion": EXTRACCION.model_dump(),
    "categoria_confianza": "Alta",
    "score_confianza_final": 0.97,
    "requiere_auditoria_humana": False,
    "justificacion_enrutamiento": "Confianza Alta y urgencia detectada.",
}


# ---------------------------------------------------------------- condición

@pytest.mark.parametrize(
    "envelope,esperado",
    [
        ({"urgente": True, "estado": "urgente"}, True),
        # Confianza Media/Baja: va a revisión humana pero sigue siendo urgente.
        ({"urgente": True, "estado": "revision_humana"}, True),
        ({"urgente": False, "estado": "estandar"}, False),
        ({"urgente": False, "estado": "revision_humana"}, False),
        # Sin la señal (p. ej. error técnico antes del routing): no se alerta.
        ({"estado": "error_tecnico"}, False),
        ({"urgente": None}, False),
        ({"urgente": "true"}, False),
    ],
)
def test_debe_alertar(envelope, esperado):
    assert alertas_n8n.debe_alertar(envelope) is esperado


# ------------------------------------------------------------------- evento

def test_evento_no_incluye_datos_del_paciente():
    evento = alertas_n8n.construir_evento_alerta(_envelope(), ESTADO_COMPLETO)
    serializado = json.dumps(evento, ensure_ascii=False)

    assert NOMBRE_PACIENTE not in serializado
    assert "12345678" not in serializado
    assert "paciente" not in evento
    assert evento["documento_id"] == "DOC-ALERTA-001"
    assert evento["estado"] == "urgente"
    assert evento["urgente"] is True
    assert evento["tipo_documento"] == DocumentType.INFORME_ESTUDIO_DIAGNOSTICO.value
    assert evento["nivel_urgencia"] == "urgente"
    assert evento["categoria_confianza"] == "Alta"


def test_evento_limita_senales_de_gravedad():
    evento = alertas_n8n.construir_evento_alerta(_envelope(), ESTADO_COMPLETO)
    assert len(evento["senales_gravedad"]) == alertas_n8n.MAX_SENALES_GRAVEDAD
    assert "cuarta señal que no debe enviarse" not in evento["senales_gravedad"]


def test_evento_tolera_estado_completo_ausente():
    evento = alertas_n8n.construir_evento_alerta(_envelope(), None)
    assert evento["documento_id"] == "DOC-ALERTA-001"
    assert evento["senales_gravedad"] == []
    assert evento["tipo_documento"] is None


# ------------------------------------------------------------------- envío

def test_notificar_sin_url_configurada_no_llama_a_la_red(monkeypatch):
    monkeypatch.delenv(alertas_n8n.ENV_WEBHOOK_URL, raising=False)
    post = FakePost()
    monkeypatch.setattr(alertas_n8n.httpx, "post", post)

    assert alertas_n8n.notificar_caso_urgente({"documento_id": "X"}) is False
    assert post.llamadas == []


def test_notificar_exitoso_envia_json_token_y_timeout(monkeypatch, webhook_configurado):
    monkeypatch.setenv(alertas_n8n.ENV_WEBHOOK_TOKEN, "token-de-prueba")
    post = FakePost()
    monkeypatch.setattr(alertas_n8n.httpx, "post", post)

    assert alertas_n8n.notificar_caso_urgente({"documento_id": "DOC-1"}) is True

    (llamada,) = post.llamadas
    assert llamada["url"] == URL_WEBHOOK
    assert llamada["json"] == {"documento_id": "DOC-1"}
    assert llamada["headers"] == {alertas_n8n.HEADER_TOKEN: "token-de-prueba"}
    assert llamada["timeout"] == alertas_n8n.TIMEOUT_SEGUNDOS


def test_notificar_sin_token_no_envia_header_de_autenticacion(monkeypatch, webhook_configurado):
    post = FakePost()
    monkeypatch.setattr(alertas_n8n.httpx, "post", post)

    alertas_n8n.notificar_caso_urgente({"documento_id": "DOC-1"})

    assert post.llamadas[0]["headers"] == {}


@pytest.mark.parametrize(
    "post",
    [
        FakePost(error=httpx.ConnectError("n8n caído")),
        FakePost(error=httpx.ReadTimeout("n8n no responde")),
        FakePost(status=500),
        FakePost(status=404),
        FakePost(error=RuntimeError("error inesperado")),
    ],
    ids=["conexion", "timeout", "http-500", "http-404", "inesperado"],
)
def test_notificar_nunca_propaga_excepciones(monkeypatch, webhook_configurado, post, caplog):
    monkeypatch.setattr(alertas_n8n.httpx, "post", post)

    with caplog.at_level("WARNING", logger=alertas_n8n.logger.name):
        resultado = alertas_n8n.notificar_caso_urgente({"documento_id": "DOC-FALLA"})

    assert resultado is False
    assert "DOC-FALLA" in caplog.text
    # La URL del webhook puede contener un identificador secreto: no se loguea.
    assert URL_WEBHOOK not in caplog.text


def test_emitir_no_alerta_si_no_es_urgente(monkeypatch, webhook_configurado):
    post = FakePost()
    monkeypatch.setattr(alertas_n8n.httpx, "post", post)

    assert alertas_n8n.emitir_alerta_si_corresponde(_envelope(urgente=False), ESTADO_COMPLETO) is False
    assert post.llamadas == []


def test_emitir_absorbe_fallos_inesperados(monkeypatch, webhook_configurado):
    def explota(_envelope, _estado):
        raise ValueError("bug al armar el evento")

    monkeypatch.setattr(alertas_n8n, "construir_evento_alerta", explota)

    assert alertas_n8n.emitir_alerta_si_corresponde(_envelope(), ESTADO_COMPLETO) is False


# ---------------------------------------------- integración con POST /documentos

class FakeOCIStorageService:
    def __init__(self, eventos):
        self._eventos = eventos
        self.resultados_subidos = []
        self.historial_subido = []

    def upload_document(self, document_id, content, filename):
        return f"recibidos/{document_id}_{filename}"

    def upload_resultado(self, documento_id, estado, resultado):
        self._eventos.append("resultado")
        self.resultados_subidos.append((documento_id, estado, resultado))
        return f"procesados/{estado}/{documento_id}.json"

    def upload_historial(self, documento_id, momento, evento):
        self._eventos.append("historial")
        self.historial_subido.append((documento_id, momento, evento))
        return f"historial/{documento_id}/{momento.isoformat()}.json"


class GrafoFalso:
    def __init__(self, campos_extra):
        self._campos_extra = campos_extra

    def invoke(self, estado_inicial):
        return {
            **estado_inicial,
            "clasificacion": CLASIFICACION,
            "extraccion": EXTRACCION,
            "validacion_ok": True,
            "errores_validacion": [],
            **self._campos_extra,
        }


def _enviar_documento(monkeypatch, grafo, eventos, post):
    monkeypatch.setattr(routes, "grafo_mediflow", grafo)
    storage = FakeOCIStorageService(eventos)
    monkeypatch.setattr(routes, "OCIStorageService", lambda: storage)
    monkeypatch.setattr(alertas_n8n.httpx, "post", post)

    app = FastAPI()
    app.include_router(routes.router)
    contenido = (SAMPLES_DIR / "01_receta_medica.txt").read_bytes()
    respuesta = TestClient(app).post(
        "/documentos",
        data={"documento_id": "DOC-RUTA-001", "canal_origen": "test"},
        files={"archivo": ("01_receta_medica.txt", contenido, "text/plain")},
    )
    return respuesta, storage


def test_ruta_urgente_envia_alerta_despues_de_persistir(monkeypatch, webhook_configurado):
    eventos = []
    post = FakePost(eventos)
    grafo = GrafoFalso({
        "destino_principal": "urgente",
        "urgente": True,
        "requiere_auditoria_humana": False,
        "categoria_confianza": "Alta",
    })

    respuesta, storage = _enviar_documento(monkeypatch, grafo, eventos, post)

    assert respuesta.status_code == 200
    assert len(post.llamadas) == 1
    evento = post.llamadas[0]["json"]
    assert evento["documento_id"] == "DOC-RUTA-001"
    assert evento["estado"] == "urgente"
    assert NOMBRE_PACIENTE not in json.dumps(evento, ensure_ascii=False)
    # La alerta es lo último: resultado e historial ya estaban persistidos.
    assert eventos == ["resultado", "historial", "alerta"]


def test_ruta_urgente_con_revision_humana_tambien_alerta(monkeypatch, webhook_configurado):
    eventos = []
    post = FakePost(eventos)
    grafo = GrafoFalso({
        "destino_principal": "revision_humana",
        "urgente": True,
        "requiere_auditoria_humana": True,
        "categoria_confianza": "Media",
    })

    respuesta, _ = _enviar_documento(monkeypatch, grafo, eventos, post)

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "revision_humana"
    assert len(post.llamadas) == 1
    assert post.llamadas[0]["json"]["estado"] == "revision_humana"
    assert post.llamadas[0]["json"]["requiere_auditoria_humana"] is True


@pytest.mark.parametrize(
    "destino,requiere_auditoria",
    [("estandar", False), ("revision_humana", True)],
)
def test_ruta_no_urgente_no_alerta(monkeypatch, webhook_configurado, destino, requiere_auditoria):
    eventos = []
    post = FakePost(eventos)
    grafo = GrafoFalso({
        "destino_principal": destino,
        "urgente": False,
        "requiere_auditoria_humana": requiere_auditoria,
    })

    respuesta, _ = _enviar_documento(monkeypatch, grafo, eventos, post)

    assert respuesta.status_code == 200
    assert post.llamadas == []


@pytest.mark.parametrize(
    "falla",
    [
        httpx.ConnectError("n8n caído"),
        httpx.ReadTimeout("n8n no responde"),
        RuntimeError("Slack y correo fallaron"),
    ],
    ids=["n8n-caido", "timeout", "inesperado"],
)
def test_falla_de_alertas_no_bloquea_el_procesamiento(monkeypatch, webhook_configurado, falla):
    eventos = []
    post = FakePost(eventos, error=falla)
    grafo = GrafoFalso({
        "destino_principal": "urgente",
        "urgente": True,
        "requiere_auditoria_humana": False,
    })

    respuesta, storage = _enviar_documento(monkeypatch, grafo, eventos, post)

    # Se intentó alertar, pero la respuesta y la persistencia son normales.
    assert len(post.llamadas) == 1
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "procesado"
    assert cuerpo["estado"] == "urgente"
    assert cuerpo["persistencia_ok"] is True
    assert cuerpo["historial_ok"] is True
    assert len(storage.resultados_subidos) == 1
    assert len(storage.historial_subido) == 1


def test_ruta_sin_webhook_configurado_procesa_normalmente(monkeypatch):
    monkeypatch.delenv(alertas_n8n.ENV_WEBHOOK_URL, raising=False)
    eventos = []
    post = FakePost(eventos)
    grafo = GrafoFalso({
        "destino_principal": "urgente",
        "urgente": True,
        "requiere_auditoria_humana": False,
    })

    respuesta, storage = _enviar_documento(monkeypatch, grafo, eventos, post)

    assert respuesta.status_code == 200
    assert respuesta.json()["persistencia_ok"] is True
    assert post.llamadas == []
