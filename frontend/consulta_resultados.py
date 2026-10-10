"""
frontend.consulta_resultados

Sección «Consultar resultado»: dado el ID de un documento ya enviado, muestra cómo quedó su procesamiento
(destino, urgencia, confianza, clasificación, datos extraídos), si tuvo decisión humana y su línea de tiempo.

No agrega nada a la API: usa `GET /documentos/{id}/historial`, que ya devuelve cada corrida con su resultado
completo y las decisiones de revisión humana. La lectura de los eventos reutiliza la misma normalización que
el panel de revisión humana (`utils_frontend._item_desde_evento`), así que ambos paneles muestran lo mismo.

Solo lectura: no modifica ni reprocesa el documento.

Uso:
    streamlit run frontend/panel_consulta.py      (página propia; también está en el menú de mediflow.py)
o, para incrustarlo en otro panel:
    from consulta_resultados import render_consulta_resultados
    render_consulta_resultados()
"""
from __future__ import annotations

from typing import Any

import streamlit as st
import utils_frontend as u
from carga_archivos import ETIQUETA_ESTADO
from utils_frontend import ErrorClienteAPI, MOTIVOS_RECHAZO, aplanar_extraccion, formatear_fecha, item_es_urgente

MAX_LARGO_ID = 200
TIPO_DECISION = "decision_humana"


# --------------------------------------------------------------------------
# Lógica (sin Streamlit)
# --------------------------------------------------------------------------
def validar_id_consulta(documento_id: str) -> str | None:
    """Mensaje de error del ID escrito, o None si se puede consultar."""
    if not documento_id.strip():
        return "Escriba el ID del documento que desea consultar."
    if len(documento_id.strip()) > MAX_LARGO_ID:
        return f"El ID del documento es demasiado largo (máximo {MAX_LARGO_ID} caracteres)."
    return None


def consultar_documento(documento_id: str) -> list[dict[str, Any]]:
    """Eventos del documento (procesamientos y decisiones), del más antiguo al más reciente."""
    ruta = f"/documentos/{u._ruta_documento(documento_id.strip())}/historial"
    return u._solicitar("GET", ruta)["eventos"]


def es_no_encontrado(exc: Exception) -> bool:
    return str(exc).startswith("404:")


def _es_decision(evento: dict[str, Any]) -> bool:
    return evento.get("tipo_evento") == TIPO_DECISION


def resumir_documento(eventos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Estado actual del documento a partir de su línea de tiempo.
    Se usa el procesamiento MÁS RECIENTE; una decisión humana solo cuenta si es posterior a él (si el documento
    se reprocesó después de decidir, el ciclo de revisión empieza de nuevo).
    situacion: 'automatico' | 'pendiente' | 'resuelto' | 'error_tecnico'
    """
    indices = [i for i, e in enumerate(eventos) if not _es_decision(e)]
    if not indices:
        return None
    pos = indices[-1]
    ultimo = eventos[pos]
    decision = next((e for e in reversed(eventos[pos + 1:]) if _es_decision(e)), None)
    estado = ultimo.get("estado")
    if estado == "revision_humana":
        situacion = "resuelto" if decision else "pendiente"
    elif estado == "error_tecnico":
        situacion = "error_tecnico"
    else:
        situacion = "automatico"
    return {
        "item": u._item_desde_evento(ultimo),
        "situacion": situacion,
        "decision": decision,
        "procesamientos": len(indices),
    }


def filas_linea_tiempo(eventos: list[dict[str, Any]]) -> list[dict[str, str]]:
    filas = []
    for e in eventos:
        if _es_decision(e):
            motivo = MOTIVOS_RECHAZO.get(e.get("motivo") or "", "")
            detalle = f"{e.get('decision')} por {e.get('auditor')}" + (f" · {motivo}" if motivo else "") + (
                f" — {e['notas']}" if e.get("notas") else "")
            etiqueta = "Decisión humana"
        else:
            conf = (e.get("resumen") or {}).get("categoria_confianza")
            etiqueta = "Procesamiento"
            detalle = f"estado: {e.get('estado')}" + (f" · confianza {conf}" if conf else "")
        filas.append({"evento": etiqueta, "fecha": formatear_fecha(e.get("timestamp")), "detalle": detalle})
    return filas


# --------------------------------------------------------------------------
# Presentación
# --------------------------------------------------------------------------
def _mostrar_situacion(resumen: dict[str, Any]) -> None:
    situacion, item, decision = resumen["situacion"], resumen["item"], resumen["decision"]
    if situacion == "pendiente":
        st.warning("⏳ **Pendiente de revisión humana.** Un auditor debe aprobarlo o rechazarlo en «Revisión humana».")
    elif situacion == "resuelto":
        cuando = formatear_fecha(decision.get("timestamp"))
        if decision.get("decision") == "APROBADO":
            st.success(f"✅ **Aprobado** por {decision.get('auditor')} el {cuando}.")
        else:
            motivo = MOTIVOS_RECHAZO.get(decision.get("motivo") or "", decision.get("motivo") or "sin motivo")
            notas = f" — {decision['notas']}" if decision.get("notas") else ""
            st.error(f"❌ **Rechazado** por {decision.get('auditor')} el {cuando}. Motivo: {motivo}{notas}")
    elif situacion == "error_tecnico":
        st.error("⚠️ **Error técnico:** el pipeline no pudo completar el procesamiento de este documento.")
    elif item.get("estado") == "urgente":
        st.error("🚨 **Alerta urgente:** procesado automáticamente y marcado como urgente.")
    else:
        st.success("✅ **Procesado automáticamente.**")


def _mostrar_documento(documento_id: str, eventos: list[dict[str, Any]], clave: str) -> None:
    resumen = resumir_documento(eventos)
    st.subheader(f"Documento {documento_id}")
    if resumen is None:
        st.info("Este documento solo tiene decisiones registradas, sin un procesamiento asociado.")
        return
    item = resumen["item"]
    _mostrar_situacion(resumen)
    if resumen["procesamientos"] > 1:
        st.caption(f"Este documento se procesó {resumen['procesamientos']} veces; se muestra la más reciente.")

    score = item["score_confianza_final"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Destino", ETIQUETA_ESTADO.get(item["estado"], str(item["estado"] or "—")))
    m2.metric("Nivel de urgencia", str(item["nivel_urgencia"] or "—"))
    m3.metric(
        "Confianza final",
        f"{score:.2f}" + (f" · {item['categoria_confianza']}" if item["categoria_confianza"] else "")
        if isinstance(score, (int, float)) else "—",
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"**Tipo de documento:** {item['tipo_documento']}")
        if item["timestamp"]:
            st.markdown(f"**Procesado:** {formatear_fecha(item['timestamp'])}")
        if item["validacion_ok"] is not None:
            st.markdown(f"**Validación:** {'✅ correcta' if item['validacion_ok'] else '⚠️ con errores'}")
        clas = item["clasificacion"]
        if isinstance(clas.get("score_confianza_clasificacion"), (int, float)):
            st.markdown(f"**Autoevaluación del clasificador:** {clas['score_confianza_clasificacion']:.2f}")
        if item["justificacion_enrutamiento"]:
            st.markdown(f"**Por qué se enrutó así:** {item['justificacion_enrutamiento']}")
        for motivo in item["motivos_confianza"]:
            st.markdown(f"- {motivo}")
        for error in item["errores_validacion"] + item["inconsistencias"]:
            st.markdown(f"- ⚠️ {error}")
        if clas.get("especialidad"):
            st.markdown(f"**Especialidad:** {clas['especialidad']}")
        if clas.get("nivel_prioridad"):
            st.markdown(f"**Prioridad (clasificador):** {clas['nivel_prioridad']}")
        if clas.get("justificacion"):
            st.markdown(f"**Justificación:** {clas['justificacion']}")
        for agente, meta in item["metadata"].items():
            if isinstance(meta, dict):
                extra = " (con fallback)" if meta.get("fallback_utilizado") else ""
                st.caption(f"{agente}: {meta.get('proveedor_usado')} / {meta.get('modelo_usado')}{extra}")
            else:
                st.caption(f"{agente}: {meta}")
        if item_es_urgente(item) and item["estado"] == "revision_humana":
            st.caption("Marcado como urgente por el pipeline, aunque se derivó a revisión humana.")

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
        if st.checkbox("Ver datos técnicos (JSON)", key=f"{clave}_json"):
            st.json({"clasificacion": item["clasificacion"], "extraccion": item["extraccion"]}, expanded=False)

    with st.expander("Línea de tiempo del documento", expanded=True):
        st.dataframe(filas_linea_tiempo(eventos), hide_index=True, width="stretch")
        fallos = item["recorrido"].get("fallos_tecnicos")
        if fallos:
            st.warning("Fallos técnicos: " + "; ".join(map(str, fallos)))


def render_consulta_resultados(clave: str = "consulta") -> None:
    """Dibuja la sección «Consultar resultado». El ID del último documento enviado desde Carga viene precargado."""
    with st.container(border=True):
        st.subheader("Consultar resultado")
        with st.form(f"{clave}_form"):
            documento_id = st.text_input(
                "ID del documento",
                value=st.session_state.get("ultimo_documento_id", ""),
                placeholder="ej. DOC-CLIN-2026-0001",
            )
            consultar = st.form_submit_button("Consultar", type="primary")

        if consultar:
            error = validar_id_consulta(documento_id)
            if error:
                st.error(error)
                st.session_state.pop(f"{clave}_estado", None)
            else:
                try:
                    with st.spinner("Consultando el documento…"):
                        eventos = consultar_documento(documento_id)
                    st.session_state[f"{clave}_estado"] = {"id": documento_id.strip(), "eventos": eventos}
                except ErrorClienteAPI as exc:
                    st.session_state[f"{clave}_estado"] = {
                        "id": documento_id.strip(), "error": str(exc), "no_encontrado": es_no_encontrado(exc),
                    }

    estado = st.session_state.get(f"{clave}_estado")
    if not estado:
        return
    if estado.get("no_encontrado"):
        st.warning(
            f"No se encontró ningún documento con el ID «{estado['id']}». Verifique el ID "
            "(se distingue entre mayúsculas y minúsculas) o que el documento ya se haya enviado."
        )
    elif estado.get("error"):
        st.error(f"No se pudo consultar el documento: {estado['error']}")
    else:
        _mostrar_documento(estado["id"], estado["eventos"], clave)
