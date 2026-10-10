"""
frontend.panel_consulta

Página independiente para consultar el resultado de un documento ya enviado. No toca el panel de revisión
humana (panel_hitl.py) ni la API: solo lee `GET /documentos/{id}/historial`.

Arranque local (desde la raíz del proyecto, para que cargue .streamlit/config.toml):

    uvicorn main:app --port 8000
    streamlit run frontend/panel_consulta.py --server.port 8503
"""
from __future__ import annotations

import streamlit as st
from consulta_resultados import render_consulta_resultados
from estilo import aplicar_estilo

st.set_page_config(page_title="MediFlow - Consulta de resultados", page_icon="🔎", layout="wide")
aplicar_estilo()

st.title("🔎 MediFlow — Consulta de resultados")
st.caption("Consulte cómo quedó el procesamiento de un documento ya enviado, a partir de su ID.")

render_consulta_resultados()
