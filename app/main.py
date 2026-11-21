from fastapi import FastAPI

from app.config import Settings, get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.env != "dev")

    app = FastAPI(title="Order Ops Copilot", version="0.1.0")
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    return app
