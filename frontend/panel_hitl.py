"""
frontend.panel_hitl  (MF-12)

Panel Streamlit de revisión humana (HITL) para los documentos que el pipeline derivó a `revision_humana`.

El revisor SOLO decide APROBAR o RECHAZAR. El documento es de un tercero y NO se edita: no hay campos ni
botones para corregir datos clínicos. Al rechazar es obligatorio elegir un motivo y escribir notas.
Cada decisión se guarda como un evento `decision_humana` en la línea de tiempo del documento (historial/).

Pestañas: Pendientes · Resueltos recientemente.

Datos: solo vía la API de MediFlow (MEDIFLOW_API_URL). Sin autenticación en el MVP: el nombre del auditor
es texto libre y queda registrado tal cual en cada decisión.

Arranque local (desde la raíz del proyecto, para que cargue .streamlit/config.toml):

    uvicorn main:app --port 8000
    streamlit run frontend/panel_hitl.py --server.port 8502
"""
from __future__ import annotations

import streamlit as st
from estilo import aplicar_estilo
from utils_frontend import (
    DECISIONES_AUDITORIA,
    MOTIVOS_RECHAZO,
    TIPOS_DOCUMENTO_MF02,
    aplanar_extraccion,
    es_conflicto,
    formatear_fecha,
    item_es_urgente,
    obtener_bandeja,
    obtener_linea_tiempo,
    registrar_decision_auditoria,
)

ETIQUETA_DECISION = {"APROBADO": "Aprobado", "RECHAZADO": "Rechazado"}

st.set_page_config(page_title="MediFlow - Revisión humana", page_icon="🧑‍⚕️", layout="wide")
aplicar_estilo()


@st.cache_data(ttl=30, show_spinner=False)
def _bandeja_cacheada() -> dict:
    return obtener_bandeja()


@st.cache_data(ttl=60, show_spinner=False)
def _linea_tiempo_cacheada(documento_id: str) -> list:
    return obtener_linea_tiempo(documento_id)


st.title("🧑‍⚕️ MediFlow — Revisión humana")
st.caption("Documentos que el pipeline derivó a revisión humana. Solo se puede **aprobar** o **rechazar** (con motivo).")

with st.sidebar:
    st.header("Auditor")
    auditor = st.text_input("Su nombre o usuario", key="auditor", placeholder="ej. kimberlyn.r")
    st.caption("Queda registrado en cada decisión. Sin autenticación en el MVP: se guarda el nombre escrito.")

if st.button("🔄 Actualizar bandeja"):
    _bandeja_cacheada.clear()
    _linea_tiempo_cacheada.clear()
    st.rerun()

try:
    bandeja = _bandeja_cacheada()
except Exception as exc:
    st.error(f"No se pudo obtener la bandeja de revisión humana ({exc}).")
    bandeja = {"pendientes": [], "total_pendientes": 0, "resueltos": [], "avisos": []}

for aviso in bandeja["avisos"]:
    st.warning(aviso)

pendientes = bandeja["pendientes"]

with st.sidebar:
    st.header("Filtros")
    filtro_tipos = st.multiselect("Tipo de documento", TIPOS_DOCUMENTO_MF02, placeholder="Todos los tipos")
    niveles = sorted({str(i["nivel_urgencia"]) for i in pendientes if i["nivel_urgencia"]})
    filtro_niveles = st.multiselect("Nivel de urgencia", niveles, placeholder="Todos los niveles")

visibles = [
    i for i in pendientes
    if (not filtro_tipos or i["tipo_documento"] in filtro_tipos)
    and (not filtro_niveles or str(i["nivel_urgencia"]) in filtro_niveles)
]
# Urgentes primero (el orden previo, más reciente primero, se conserva dentro de cada grupo).
visibles.sort(key=lambda i: not item_es_urgente(i))

m1, m2 = st.columns(2)
m1.metric("Pendientes de revisión", bandeja["total_pendientes"])
m2.metric("Urgentes (en pantalla)", sum(item_es_urgente(i) for i in pendientes))

tab_pend, tab_res = st.tabs([f"Pendientes ({bandeja['total_pendientes']})", "Resueltos recientemente"])

# --------------------------------------------------------------------------
# Pestaña 1 — Pendientes
# --------------------------------------------------------------------------
with tab_pend:
    if not pendientes:
        st.success("No hay documentos pendientes de revisión humana. 🎉")
    elif not visibles:
        st.info("Ningún pendiente coincide con los filtros.")

    for item in visibles:
        doc_id = item["documento_id"]
        nivel = str(item["nivel_urgencia"] or "DESCONOCIDO")
        urgente = item_es_urgente(item)
        color = "red" if urgente else "orange"

        with st.expander(f"{'🚨' if urgente else '📄'} {doc_id} — {item['tipo_documento']} ({nivel})"):
            col_a, col_b = st.columns(2)

            with col_a:
                st.markdown(f"**Tipo de documento:** {item['tipo_documento']}")
                st.markdown(f"**Nivel de urgencia:** :{color}[{nivel}]" + (" · **prioritario**" if item["urgente"] else ""))
                if item["validacion_ok"] is not None:
                    st.markdown(f"**Validación:** {'✅ correcta' if item['validacion_ok'] else '⚠️ con errores'}")
                if item["timestamp"]:
                    st.markdown(f"**Procesado:** {formatear_fecha(item['timestamp'])}")
                clas = item["clasificacion"]
                if isinstance(clas.get("score_confianza_clasificacion"), (int, float)):
                    st.markdown(f"**Autoevaluación del clasificador:** {clas['score_confianza_clasificacion']:.2f}")
                if item["score_confianza_final"] is not None:
                    st.markdown(
                        f"**Confianza final:** {item['score_confianza_final']:.2f} ({item['categoria_confianza'] or 's/d'})"
                    )
                if item["justificacion_enrutamiento"]:
                    st.markdown(f"**Por qué está aquí:** {item['justificacion_enrutamiento']}")
                for motivo in item["motivos_confianza"]:   # tal como los deja MF-10 / MF-21
                    st.markdown(f"- {motivo}")
                for error in item["errores_validacion"]:
                    st.markdown(f"- ⚠️ {error}")
                for inconsistencia in item["inconsistencias"]:
                    st.markdown(f"- ⚠️ {inconsistencia}")
                if clas.get("especialidad"):
                    st.markdown(f"**Especialidad:** {clas['especialidad']}")
                if clas.get("nivel_prioridad"):
                    st.markdown(f"**Prioridad (clasificador):** {clas['nivel_prioridad']}")
                if clas.get("justificacion"):
                    st.markdown(f"**Justificación:** {clas['justificacion']}")
                # proveedor/modelo por agente: dict (MF-19) o el texto "no_disponible (...)".
                for agente, meta in item["metadata"].items():
                    if isinstance(meta, dict):
                        extra = " (con fallback)" if meta.get("fallback_utilizado") else ""
                        st.caption(f"{agente}: {meta.get('proveedor_usado')} / {meta.get('modelo_usado')}{extra}")
                    else:
                        st.caption(f"{agente}: {meta}")

            with col_b:
                st.markdown("**Datos extraídos del documento** (solo lectura)")
                filas = aplanar_extraccion({k: v for k, v in item["extraccion"].items() if k != "campos_no_encontrados"})
                if filas:
                    st.dataframe(filas, hide_index=True, width="stretch")
                else:
                    st.caption("No se extrajeron datos.")
                faltantes = item["extraccion"].get("campos_no_encontrados") or []
                if faltantes:
                    st.warning("**Campos no encontrados:** " + ", ".join(map(str, faltantes)))
                if st.checkbox("Ver datos técnicos (JSON)", key=f"json_{doc_id}"):
                    st.json({"clasificacion": clas, "extraccion": item["extraccion"]}, expanded=False)

            if st.checkbox("Ver línea de tiempo del documento", key=f"linea_{doc_id}"):
                try:
                    linea = _linea_tiempo_cacheada(doc_id)
                except Exception as exc:
                    st.error(f"No se pudo leer la línea de tiempo ({exc}).")
                    linea = []
                if linea:
                    st.dataframe(linea, hide_index=True, width="stretch")
                else:
                    st.caption("Sin eventos de historial para este documento.")
                if item["recorrido"].get("fallos_tecnicos"):
                    st.warning("Fallos técnicos: " + "; ".join(map(str, item["recorrido"]["fallos_tecnicos"])))

            # ---- Decisión: aprobar o rechazar (nunca se edita el documento) ----
            with st.form(f"form_{doc_id}"):
                notas = st.text_area(
                    "Notas del auditor (obligatorias al rechazar)",
                    placeholder="Observaciones sobre la revisión del documento…",
                )
                motivo = st.selectbox(
                    "Motivo del rechazo (obligatorio si rechaza)",
                    list(MOTIVOS_RECHAZO),
                    format_func=MOTIVOS_RECHAZO.get,
                    index=None,
                    placeholder="Seleccione un motivo",
                    key=f"motivo_{doc_id}",
                )
                c_ok, c_no = st.columns(2)
                aprobar = c_ok.form_submit_button("✅ Aprobar", type="primary", width="stretch")
                rechazar = c_no.form_submit_button("❌ Rechazar", width="stretch")

            if aprobar or rechazar:
                decision = "APROBADO" if aprobar else "RECHAZADO"
                assert decision in DECISIONES_AUDITORIA
                error = None
                notas_finales = notas.strip()
                if not auditor.strip():
                    error = "Escriba su nombre en la barra lateral antes de decidir."
                elif decision == "RECHAZADO" and not motivo:
                    error = "Seleccione el motivo del rechazo."
                elif decision == "RECHAZADO" and not notas_finales:
                    error = "Las notas son obligatorias al rechazar."
                if error:
                    st.error(error)
                else:
                    try:
                        registrar_decision_auditoria(
                            item, decision, notas_finales, auditor.strip(),
                            motivo=motivo if decision == "RECHAZADO" else None,
                        )
                    except Exception as exc:
                        if es_conflicto(exc):
                            # Sin st.rerun(): un rerun borraría este aviso antes de que el auditor lo lea.
                            st.warning(
                                "Este documento ya no está pendiente (otro auditor decidió o se reprocesó). "
                                "Pulse «Actualizar bandeja» para ver el estado actual."
                            )
                            _bandeja_cacheada.clear()
                        else:
                            st.error(f"No se pudo guardar la decisión ({exc}).")
                    else:
                        _bandeja_cacheada.clear()
                        _linea_tiempo_cacheada.clear()
                        st.rerun()

# --------------------------------------------------------------------------
# Pestaña 2 — Resueltos recientemente
# --------------------------------------------------------------------------
with tab_res:
    if not bandeja["resueltos"]:
        st.info("Todavía no hay decisiones resueltas.")
    else:
        st.dataframe(
            [
                {
                    "Documento": r["documento_id"],
                    "Decisión": ETIQUETA_DECISION.get(r["decision"], r["decision"]),
                    "Motivo": MOTIVOS_RECHAZO.get(r["motivo"] or "") or "—",
                    "Notas": r["notas"] or "—",
                    "Tipo de documento": r["tipo_documento"],
                    "Auditor": r["auditor"],
                    "Fecha": formatear_fecha(r["timestamp"]),
                }
                for r in bandeja["resueltos"]
            ],
            hide_index=True,
            width="stretch",
        )
