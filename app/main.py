from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    application = FastAPI(title=settings.app_name)
    application.include_router(health_router)
    return application


app = create_app()
