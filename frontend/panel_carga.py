"""
frontend.panel_carga

Página independiente para cargar documentos al pipeline de MediFlow. No toca el panel de revisión humana
(panel_hitl.py): es otra aplicación Streamlit que reutiliza el mismo tema (estilo.py).

Arranque local (desde la raíz del proyecto, para que cargue .streamlit/config.toml):

    uvicorn main:app --port 8000
    streamlit run frontend/panel_carga.py --server.port 8501
"""
from __future__ import annotations

import streamlit as st
from carga_archivos import render_carga_archivos
from estilo import aplicar_estilo

st.set_page_config(page_title="MediFlow - Carga de documentos", page_icon="📤", layout="wide")
aplicar_estilo()

st.title("📤 MediFlow — Carga de documentos")
st.caption("Envíe un documento clínico al pipeline de triaje (clasificación y extracción por LLM).")

render_carga_archivos()
