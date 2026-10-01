"""
tests/test_mf19_metadata.py

MF-15 (pedido de Kate en el PR de MF-19): trazabilidad de que proveedor y
modelo respondio en cada agente, si hubo fallback y cuantos intentos.

- Clasificador: clasificar_documento(..., metadata=dict) rellena el dict.
- Extractor: el grafo cuenta las llamadas a cada proveedor.
- El grafo lo expone en el estado como metadata_clasificacion y
  metadata_extraccion, sin cambiar los contratos de Classification ni
  de ExtraccionClinica.
"""

from app.agents import classifier, extractor
from app.graph import graph
from app.schemas.clasificacion import Classification, DocumentType
from app.schemas.documento import DocumentoEntrada
from app.schemas.extraccion import ExtraccionClinica
from app.services.errores_llm import ErrorTecnicoProveedor

DOCUMENTO = DocumentoEntrada(
    documento_id="DOC-TEST-MF19-META",
    tipo_archivo="JSON",
    canal_origen="test",
    nombre_archivo="ejemplo_receta_medica.txt",
    mime_type="text/plain",
    documento_texto="Documento clinico de prueba.",
)

CLASIFICACION_OK = Classification(
    tipo_documento=DocumentType.RECETA_MEDICA,
    especialidad="Medicina General",
    nivel_prioridad="Rutina",
    score_confianza_clasificacion=0.9,
    justificacion="Documento con datos suficientes para clasificar.",
)


def _secuencia(*pasos):
    """Generador falso: cada llamada consume un paso (excepcion o resultado)."""
    pasos = list(pasos)

    def _generar(*_args, **_kwargs):
        paso = pasos.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return paso

    return _generar


def _falla():
    return ErrorTecnicoProveedor("503 simulado")


# ---------------------------------------------------------------- Clasificador


def test_clasificador_principal_responde_al_primer_intento(monkeypatch):
    monkeypatch.setattr(classifier, "_generar_con_gemini", _secuencia(CLASIFICACION_OK))
    meta = {}

    resultado = classifier.clasificar_documento(DOCUMENTO, metadata=meta)

    assert resultado is CLASIFICACION_OK
    assert meta == {"origen": "principal", "intentos_principal": 1, "intentos_fallback": 0}


def test_clasificador_principal_responde_tras_reintentos(monkeypatch):
    monkeypatch.setattr(
        classifier, "_generar_con_gemini", _secuencia(_falla(), _falla(), CLASIFICACION_OK)
    )
    meta = {}

    classifier.clasificar_documento(DOCUMENTO, metadata=meta)

    assert meta == {"origen": "principal", "intentos_principal": 3, "intentos_fallback": 0}


def test_clasificador_responde_el_fallback(monkeypatch):
    monkeypatch.setattr(
        classifier, "_generar_con_gemini", _secuencia(_falla(), _falla(), _falla())
    )
    meta = {}

    resultado = classifier.clasificar_documento(
        DOCUMENTO, generador_fallback=_secuencia(CLASIFICACION_OK), metadata=meta
    )

    assert resultado is CLASIFICACION_OK
    assert meta == {"origen": "fallback", "intentos_principal": 3, "intentos_fallback": 1}


def test_clasificador_fallan_ambos_modelos(monkeypatch):
    monkeypatch.setattr(
        classifier, "_generar_con_gemini", _secuencia(_falla(), _falla(), _falla())
    )
    meta = {}

    classifier.clasificar_documento(
        DOCUMENTO, generador_fallback=_secuencia(_falla(), _falla(), _falla()), metadata=meta
    )

    assert meta == {"origen": None, "intentos_principal": 3, "intentos_fallback": 3}


def test_clasificador_sin_metadata_sigue_funcionando(monkeypatch):
    """Compatibilidad: el parametro es opcional y no cambia el retorno."""
    monkeypatch.setattr(classifier, "_generar_con_gemini", _secuencia(CLASIFICACION_OK))

    assert classifier.clasificar_documento(DOCUMENTO) is CLASIFICACION_OK


# ------------------------------------------------------- Grafo: clasificador


def _clasificador_falso(origen, intentos_principal, intentos_fallback):
    def _falso(_documento, generador_fallback=None, metadata=None):
        metadata.update(
            origen=origen,
            intentos_principal=intentos_principal,
            intentos_fallback=intentos_fallback,
        )
        return CLASIFICACION_OK

    return _falso


def test_nodo_clasificador_metadata_principal(monkeypatch):
    monkeypatch.setattr(graph, "clasificar_documento", _clasificador_falso("principal", 1, 0))

    resultado = graph.nodo_clasificador({"documento": DOCUMENTO})

    assert resultado["metadata_clasificacion"] == {
        "proveedor_usado": "gemini",
        "modelo_usado": graph._MODELO_GEMINI_CLASIFICADOR,
        "fallback_utilizado": False,
        "intentos_principal": 1,
        "intentos_fallback": 0,
    }


def test_nodo_clasificador_metadata_fallback(monkeypatch):
    monkeypatch.setattr(graph, "clasificar_documento", _clasificador_falso("fallback", 3, 1))

    meta = graph.nodo_clasificador({"documento": DOCUMENTO})["metadata_clasificacion"]

    assert meta["proveedor_usado"] == "groq"
    assert meta["modelo_usado"] == graph._MODELO_CLASIFICADOR_FALLBACK
    assert meta["fallback_utilizado"] is True
    assert (meta["intentos_principal"], meta["intentos_fallback"]) == (3, 1)


def test_nodo_clasificador_metadata_fallo_total(monkeypatch):
    monkeypatch.setattr(graph, "clasificar_documento", _clasificador_falso(None, 3, 3))

    meta = graph.nodo_clasificador({"documento": DOCUMENTO})["metadata_clasificacion"]

    assert meta["proveedor_usado"] is None
    assert meta["modelo_usado"] is None
    assert meta["fallback_utilizado"] is True


# ---------------------------------------------------------- Grafo: extractor


def _proveedor_falso(modelo, falla):
    class _Falso:
        def __init__(self, *args, **kwargs):
            self.modelo = modelo
            self.api_key = kwargs.get("api_key")

        def generar(self, *_args, **_kwargs):
            if falla:
                raise ErrorTecnicoProveedor("503 simulado")
            return "{}"

    return _Falso


def _agente_extractor_falso(*, documento, clasificacion, proveedor, proveedor_fallback=None):
    """Imita extraer_datos_clinicos: 3 intentos con el principal, luego el fallback."""
    for _ in range(3):
        try:
            proveedor.generar("sistema", "usuario")
            return ExtraccionClinica.model_construct()
        except ErrorTecnicoProveedor:
            pass
    if proveedor_fallback is not None:
        for _ in range(3):
            try:
                proveedor_fallback.generar("sistema", "usuario")
                return ExtraccionClinica.model_construct()
            except ErrorTecnicoProveedor:
                pass
    return extractor._extraccion_vacia(clasificacion, "falla simulada")


def _preparar_extractor(monkeypatch, gemini_falla, groq_falla, con_groq=True):
    monkeypatch.setattr(graph, "_GROQ_API_KEY", "clave-de-prueba" if con_groq else None)
    monkeypatch.setattr(graph, "ProveedorGemini", _proveedor_falso("gemini-prueba", gemini_falla))
    monkeypatch.setattr(
        graph.groq_client, "ProveedorGroq", _proveedor_falso("groq-prueba", groq_falla)
    )
    monkeypatch.setattr(graph, "extraer_datos_clinicos", _agente_extractor_falso)


def _estado():
    return {"documento": DOCUMENTO, "clasificacion": CLASIFICACION_OK}


def test_nodo_extractor_metadata_principal_responde(monkeypatch):
    _preparar_extractor(monkeypatch, gemini_falla=False, groq_falla=False)

    resultado = graph.nodo_extractor(_estado())

    assert resultado["metadata_extraccion"] == {
        "proveedor_usado": "gemini",
        "modelo_usado": "gemini-prueba",
        "fallback_utilizado": False,
        "intentos_principal": 1,
        "intentos_fallback": 0,
    }
    assert "fallos_tecnicos" not in resultado


def test_nodo_extractor_metadata_responde_el_fallback(monkeypatch):
    _preparar_extractor(monkeypatch, gemini_falla=True, groq_falla=False)

    meta = graph.nodo_extractor(_estado())["metadata_extraccion"]

    assert meta["proveedor_usado"] == "groq"
    assert meta["modelo_usado"] == graph._MODELO_EXTRACTOR_FALLBACK
    assert meta["fallback_utilizado"] is True
    assert (meta["intentos_principal"], meta["intentos_fallback"]) == (3, 1)


def test_nodo_extractor_metadata_fallo_total(monkeypatch):
    _preparar_extractor(monkeypatch, gemini_falla=True, groq_falla=True)

    resultado = graph.nodo_extractor(_estado())

    meta = resultado["metadata_extraccion"]
    assert meta["proveedor_usado"] is None
    assert meta["modelo_usado"] is None
    assert meta["fallback_utilizado"] is True
    assert (meta["intentos_principal"], meta["intentos_fallback"]) == (3, 3)
    assert resultado["fallos_tecnicos"]  # sigue sin marcarse como exitoso


def test_nodo_extractor_sin_groq_no_hay_fallback(monkeypatch):
    _preparar_extractor(monkeypatch, gemini_falla=True, groq_falla=False, con_groq=False)

    meta = graph.nodo_extractor(_estado())["metadata_extraccion"]

    assert meta["proveedor_usado"] is None
    assert meta["fallback_utilizado"] is False
    assert (meta["intentos_principal"], meta["intentos_fallback"]) == (3, 0)


def test_nodo_extractor_omitido_no_genera_metadata():
    estado = {**_estado(), "fallos_tecnicos": ["Clasificador: fallo total"]}

    assert graph.nodo_extractor(estado) == {}


# ------------------------------------------------------------ Grafo completo


def test_grafo_completo_expone_la_metadata_en_el_estado(monkeypatch):
    _preparar_extractor(monkeypatch, gemini_falla=False, groq_falla=False, con_groq=False)
    monkeypatch.setattr(graph, "clasificar_documento", _clasificador_falso("principal", 1, 0))

    resultado = graph.grafo_mediflow.invoke({"documento": DOCUMENTO})

    assert resultado["metadata_clasificacion"]["proveedor_usado"] == "gemini"
    assert resultado["metadata_extraccion"]["proveedor_usado"] == "gemini"
    assert resultado["validacion_ok"] is True
