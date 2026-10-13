"""
frontend.mediflow

Punto de entrada único: menú lateral que une las pantallas, sin modificar las ya existentes.

    Carga de documentos    ->  panel_carga.py     (nuevo)
    Consulta de resultados ->  panel_consulta.py  (nuevo)
    Revisión humana        ->  panel_hitl.py      (sin cambios)

Arranque local (desde la raíz del proyecto):

    uvicorn main:app --port 8000
    streamlit run frontend/mediflow.py
"""
import streamlit as st

navegacion = st.navigation(
    [
        st.Page("panel_carga.py", title="Carga de documentos", icon="📤", url_path="carga", default=True),
        st.Page("panel_consulta.py", title="Consulta de resultados", icon="🔎", url_path="consulta"),
        st.Page("panel_hitl.py", title="Revisión humana", icon="🧑‍⚕️", url_path="revision"),
    ]
)
navegacion.run()
