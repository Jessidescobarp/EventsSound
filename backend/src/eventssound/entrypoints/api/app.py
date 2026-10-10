from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eventssound.application.ports import DatabaseHealthPort
from eventssound.config import Settings
from eventssound.entrypoints.api import container
from eventssound.entrypoints.api.routes import health


def create_app(
    settings: Settings | None = None,
    session_provider: container.SessionProvider | None = None,
    database_health: DatabaseHealthPort | None = None,
) -> FastAPI:
    """Build an isolated FastAPI app. Tests override settings and adapters."""
    settings = settings or Settings()  # type: ignore[call-arg]
    production = settings.is_production

    app = FastAPI(
        title="EventSoundDR API",
        debug=not production and settings.app_env == "local",
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    app.state.settings = settings

    # The engine is created lazily; no database connection is opened here.
    factory = container.build_session_factory_from(settings)
    app.state.session_provider = session_provider or container.make_session_provider(factory)
    app.state.database_health = database_health or container.make_database_health(factory)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.include_router(health.router)
    return app
