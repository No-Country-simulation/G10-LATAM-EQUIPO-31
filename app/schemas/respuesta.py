from pydantic import BaseModel, Field

from app.schemas.clasificacion import Classification
from app.schemas.extraccion import ExtraccionClinica


class ResultadoValidacion(BaseModel):
    """
    Resultado de la validación estructural del procesamiento.
    """

    validacion_ok: bool
    errores_validacion: list[str] = Field(default_factory=list)


class RespuestaProcesamiento(BaseModel):
    """
    Contrato común de salida del procesamiento de un documento
    clínico en MediFlow.
    """

    status: str
    documento_id: str
    clasificacion: Classification
    extraccion: ExtraccionClinica
    validacion: ResultadoValidacion