from fastapi import FastAPI

from app import auth_api, health
from app.config import Settings, get_settings
from app.errors import register_exception_handlers
from app.lifespan import make_lifespan
from app.logging_config import configure_logging
from app.middleware import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.env != "dev")

    app = FastAPI(
        title="Order Ops Copilot",
        version="0.1.0",
        lifespan=make_lifespan(settings),
    )
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    app.include_router(auth_api.router)
    return app
