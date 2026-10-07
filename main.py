from fastapi import FastAPI

from app.api.routes import router
from app.api.rutas_auditoria import router as router_auditoria


app = FastAPI(
    title="MediFlow API",
    description="API para procesamiento y triaje de documentos clínicos",
    version="0.1.0"
)

app.include_router(router)
app.include_router(router_auditoria)
