"""
Prueba manual de MF-14: envía un evento SINTÉTICO de caso urgente al webhook
de n8n, para comprobar que llegan las alertas por Slack y por correo.

Requiere N8N_ALERT_WEBHOOK_URL (y N8N_ALERT_WEBHOOK_TOKEN si el webhook usa
autenticación) en el .env. El workflow de n8n debe estar activo y usar la URL
de producción del webhook. Uso:

    python samples/probar_alerta_n8n.py
    python samples/probar_alerta_n8n.py --estado revision_humana
    python samples/probar_alerta_n8n.py --estado error_tecnico

No usa datos reales: el documento_id y el contenido son ficticios.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from app.services.alertas_n8n import notificar_caso_urgente  # noqa: E402

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--estado",
        choices=["urgente", "revision_humana", "error_tecnico"],
        default="urgente",
        help="Destino del documento que se simula (cambia el texto de la alerta).",
    )
    args = parser.parse_args()

    evento = {
        "documento_id": f"PRUEBA-ALERTA-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}",
        "estado": args.estado,
        "urgente": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nivel_urgencia": "urgente",
        "tipo_documento": "Informe de Estudio de Diagnostico por Imagenes/Laboratorio",
        "especialidad": "Radiologia / Neumologia",
        "categoria_confianza": "Alta" if args.estado == "urgente" else "Media",
        "score_confianza_final": 0.97 if args.estado == "urgente" else 0.7,
        "requiere_auditoria_humana": args.estado == "revision_humana",
        "senales_gravedad": ["hallazgo compatible con TEP agudo (dato sintetico)"],
        "justificacion_enrutamiento": "Evento de prueba manual.",
    }

    enviado = notificar_caso_urgente(evento)
    if enviado:
        print(f"Evento enviado a n8n ({evento['documento_id']}, estado={args.estado}).")
        print("Revisa el canal de Slack y la bandeja de correo configurados en el workflow.")
        return 0

    print("No se pudo enviar el evento. Revisa N8N_ALERT_WEBHOOK_URL, el token y que el")
    print("workflow esté activo (los detalles quedan en el log de arriba).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
