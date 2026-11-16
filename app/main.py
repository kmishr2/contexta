import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.connections import router as connections_router
from app.api.health import router as health_router
from app.api.onboarding import router as onboarding_router
from app.core.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    application = FastAPI(title=settings.app_name)
    application.state.settings = settings
    application.include_router(health_router)
    application.include_router(connections_router)
    application.include_router(onboarding_router)

    @application.get("/", include_in_schema=False)
    def onboarding_page():
        return FileResponse(Path(__file__).parent / "web" / "index.html")

    @application.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": {"code": "metadata_unavailable", "message": "Metadata store is unavailable", "request_id": request.state.request_id}})

    return application


app = create_app()
