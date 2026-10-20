"""
frontend.estilo

Tema visual de MediFlow y responsividad (de ~240 px de ancho, una pantalla de ~3",
hasta 3840 px, un televisor/monitor de ~56").

Paleta (muestreada de la interfaz original):
    fondo principal   #0a0f23     fondo barra lateral  #090c1d
    tarjetas/métricas #121a3e     botón principal      #426ee5
    acento (radios/pestañas) #ff4b4b   gráficos        #0068c9
    estado OK #368560 · urgente #dc2626 · revisión #d97706 · error técnico #6b7280

Uso: llamar `aplicar_estilo()` justo después de `st.set_page_config(...)`.
Los colores base se fijan en `.streamlit/config.toml`; aquí van los detalles que el
tema nativo no cubre (tarjetas, botones, escalado y apilado en pantallas pequeñas).
"""
from __future__ import annotations

import streamlit as st

PALETA = {
    "fondo": "#0a0f23",
    "barra_lateral": "#090c1d",
    "tarjeta": "#121a3e",
    "boton": "#426ee5",
    "acento": "#ff4b4b",
    "grafico": "#0068c9",
    "ok": "#368560",
    "urgente": "#dc2626",
    "revision": "#d97706",
    "error": "#6b7280",
}

_CSS = f"""
<style>
/* ---------- Escala tipográfica: 13 px en pantallas diminutas -> ~24 px en 4K ---------- */
html {{ font-size: clamp(13px, 0.35vw + 11px, 26px); }}

/* ---------- Contenedor: ancho fluido, con tope en pantallas gigantes ---------- */
.block-container {{
    max-width: min(100%, 3000px);
    padding: clamp(3.6rem, 4vw, 5rem) clamp(0.6rem, 2.5vw, 4rem) 3rem; /* deja libre la barra superior de Streamlit */
}}

/* ---------- Tarjetas de métricas ---------- */
[data-testid="stMetric"] {{
    background: {PALETA['tarjeta']};
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 0.8rem 1rem;
}}
[data-testid="stMetricValue"] {{ font-size: clamp(1.4rem, 1.2rem + 1.2vw, 2.6rem); }}
[data-testid="stMetricLabel"] p {{ white-space: normal; }}

/* ---------- Expanders (casos de la bandeja) ---------- */
[data-testid="stExpander"] {{
    background: {PALETA['tarjeta']};
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
}}
[data-testid="stExpander"] summary p {{ overflow-wrap: anywhere; }}

/* ---------- Botones ---------- */
.stButton > button, [data-testid="stFormSubmitButton"] > button {{
    border-radius: 8px;
    min-height: 2.6rem;          /* área táctil cómoda en pantallas pequeñas */
}}
button[kind="primary"], button[kind="primaryFormSubmit"] {{
    background: {PALETA['boton']}; border-color: {PALETA['boton']}; color: #fff;
}}

/* ---------- Nada debe desbordar horizontalmente ---------- */
[data-testid="stDataFrame"], [data-testid="stJson"], pre {{ max-width: 100%; overflow-x: auto; }}
p, li, h1, h2, h3 {{ overflow-wrap: anywhere; }}

/* ---------- Tablet y móvil: columnas apiladas ---------- */
@media (max-width: 900px) {{
    [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; gap: 0.6rem; }}
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
        min-width: 100% !important; flex: 1 1 100% !important;
    }}
}}

/* ---------- Pantallas diminutas (~3", <= 360 px) ---------- */
@media (max-width: 360px) {{
    h1 {{ font-size: 1.35rem !important; line-height: 1.25; }}
    h2, h3 {{ font-size: 1.1rem !important; }}
    [data-testid="stMetric"] {{ padding: 0.5rem 0.6rem; }}
    .stButton > button, [data-testid="stFormSubmitButton"] > button {{ width: 100%; }}
}}

/* ---------- Pantallas enormes (>= 2560 px, ~56"): más aire entre bloques ---------- */
@media (min-width: 2560px) {{
    [data-testid="stHorizontalBlock"] {{ gap: 2rem; }}
}}
</style>
"""


def aplicar_estilo() -> None:
    """Inyecta el CSS de MediFlow (idempotente en cada rerun de Streamlit)."""
    st.markdown(_CSS, unsafe_allow_html=True)
