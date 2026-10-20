import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _sin_alertas_reales(monkeypatch):
    """Las pruebas nunca deben enviar alertas reales a n8n/Slack.

    Si N8N_ALERT_WEBHOOK_URL esta definida en el entorno de quien ejecuta
    pytest, los tests con un grafo simulado (urgente=True) enviarian
    alertas con datos de prueba al webhook real (MF-24). Las pruebas del
    modulo de alertas definen su propia URL con monkeypatch.
    """
    monkeypatch.delenv("N8N_ALERT_WEBHOOK_URL", raising=False)