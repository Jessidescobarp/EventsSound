from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eventssound.application.ports import CatalogRepository, DatabaseHealthPort
from eventssound.config import Settings
from eventssound.entrypoints.api import container
from eventssound.entrypoints.api.routes import catalog, health

DESCRIPTION = (
    "Backend of EventSoundDR, a sound, lights and DJ events company. This public, read-only API "
    "exposes the equipment catalog and the ready-made packages. All data is synthetic."
)
TAGS = [
    {
        "name": "Catalog",
        "description": "Equipment the company rents out and the packages built from it.",
    },
]


def create_app(
    settings: Settings | None = None,
    session_provider: container.SessionProvider | None = None,
    database_health: DatabaseHealthPort | None = None,
    catalog_repository: CatalogRepository | None = None,
) -> FastAPI:
    """Build an isolated FastAPI app. Tests override settings and adapters."""
    settings = settings or Settings()  # type: ignore[call-arg]
    production = settings.is_production

    app = FastAPI(
        title="EventSoundDR API",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        debug=not production and settings.app_env == "local",
        # Public in every environment: the API is read-only and its data is synthetic.
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    # The engine is created lazily; no database connection is opened here.
    factory = container.build_session_factory_from(settings)
    app.state.session_provider = session_provider or container.make_session_provider(factory)
    app.state.database_health = database_health or container.make_database_health(factory)
    app.state.catalog_repository = catalog_repository or container.make_catalog_repository(factory)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.include_router(health.router)
    app.include_router(catalog.router)
    return app
