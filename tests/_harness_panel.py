"""Lanzador del panel HITL con datos simulados (lo usa AppTest). Manual: streamlit run tests/_harness_panel.py"""
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _mocks_panel as mocks  # noqa: E402,F401  (parchea utils_frontend)

runpy.run_path(os.path.join(mocks.RAIZ, "frontend", "panel_hitl.py"), run_name="__main__")
