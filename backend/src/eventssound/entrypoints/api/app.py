from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eventssound.config import Settings
from eventssound.entrypoints.api.routes import health


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an isolated FastAPI app. Tests pass their own settings."""
    settings = settings or Settings()  # type: ignore[call-arg]
    production = settings.is_production

    app = FastAPI(
        title="EventsSound API",
        debug=not production and settings.app_env == "local",
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.include_router(health.router)
    return app
