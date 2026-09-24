"""Script manual para probar el Agente Clasificador contra Gemini real.

Requiere GEMINI_CLASSIFIER_API_KEY en tu .env (copia .env.example a .env
primero). Uso:

    python samples/probar_clasificador.py samples/ejemplo_informe_radiologico.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.classifier import clasificar_documento  # noqa: E402
from app.schemas.document import DocumentoEntrada  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("Uso: python samples/probar_clasificador.py <ruta_al_texto>")
        raise SystemExit(1)

    ruta = Path(sys.argv[1])
    documento = DocumentoEntrada(
        nombre_archivo=ruta.name,
        mime_type="text/plain",
        texto=ruta.read_text(encoding="utf-8"),
    )

    resultado = clasificar_documento(documento)
    print(resultado.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
