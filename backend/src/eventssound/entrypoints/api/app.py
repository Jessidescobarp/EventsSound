import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from eventssound.application.catalog_admin import CatalogAdmin
from eventssound.application.portfolio import PortfolioStore
from eventssound.application.ports import (
    AgentConfigRepository,
    CatalogRepository,
    DatabaseHealthPort,
)
from eventssound.application.quote_chat import QuoteAgent
from eventssound.application.quotes import BookingLister, QuoteStore
from eventssound.application.security import SecurityLog
from eventssound.application.usage import RateLimiter, UsageBudget
from eventssound.config import Settings
from eventssound.entrypoints.api import container
from eventssound.entrypoints.api.auth_kit import AuthKit, AuthRefusal, refusal_handler
from eventssound.entrypoints.api.guards import (
    ChatBodyGuard,
    ChatRefusal,
    FailClosedBudget,
    FailClosedLimiter,
)
from eventssound.entrypoints.api.routes import (
    admin_catalog,
    auth,
    catalog,
    health,
    portfolio,
    quote,
    records,
    security,
)
from eventssound.entrypoints.api.routes.quote import chat_refusal_handler, validation_handler

DESCRIPTION = (
    "Backend of EventSoundDR, a sound, lights and DJ events company. This public API exposes "
    "the equipment catalog, the ready-made packages and a quote assistant. All data is "
    "synthetic."
)
TAGS = [
    {
        "name": "Catalog",
        "description": "Equipment the company rents out and the packages built from it.",
    },
    {
        "name": "Auth",
        "description": "Login with email and password; returns a bearer token.",
    },
    {
        "name": "Quote agent",
        "description": "Describe an event in Spanish and get a priced quote. Prices come from "
        "the company's pricing rules, not from the AI.",
    },
]


def _configure_logging(level: str) -> None:
    """Uvicorn leaves application loggers unconfigured, so INFO lines would be dropped."""
    logger = logging.getLogger("eventssound")
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
        logger.addHandler(handler)


def create_app(
    settings: Settings | None = None,
    session_provider: container.SessionProvider | None = None,
    database_health: DatabaseHealthPort | None = None,
    catalog_repository: CatalogRepository | None = None,
    quote_agent: QuoteAgent | None = None,
    usage_budget: UsageBudget | None = None,
    rate_limiter: RateLimiter | None = None,
    auth_kit: AuthKit | None = None,
    quote_store: QuoteStore | None = None,
    booking_lister: BookingLister | None = None,
    catalog_admin: CatalogAdmin | None = None,
    portfolio_store: PortfolioStore | None = None,
    security_log: SecurityLog | None = None,
    agent_config_repository: AgentConfigRepository | None = None,
) -> FastAPI:
    """Build an isolated FastAPI app. Tests override settings and adapters."""
    settings = settings or Settings()  # type: ignore[call-arg]
    _configure_logging(settings.log_level)
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

    # The admin-editable agent config: cached, and exactly today's behavior when none is stored.
    app.state.agent_config = container.make_agent_config(settings, factory, agent_config_repository)

    # Quote chat. Limiter and budget are wrapped so that an error in either refuses the request.
    app.state.chat_agent = quote_agent or container.make_quote_agent(
        settings, factory, app.state.agent_config
    )
    app.state.usage_budget = FailClosedBudget(
        usage_budget or container.make_usage_budget(settings, factory, app.state.agent_config)
    )
    app.state.rate_limiter = FailClosedLimiter(
        rate_limiter or container.make_rate_limiter(settings, app.state.agent_config)
    )
    app.state.chat_limits = container.make_chat_limits(settings)
    # Login. None means auth is not configured (production without JWT_SECRET): its routes
    # answer 503 and the rest of the app keeps serving.
    app.state.auth = auth_kit or container.make_auth_kit(settings, factory)
    app.state.quote_store = quote_store or container.make_quote_store(factory)
    app.state.booking_lister = booking_lister or container.make_booking_lister(factory)
    app.state.portfolio_store = portfolio_store or container.make_portfolio_store(factory)
    app.state.security_log = security_log or container.make_security_log(factory)
    app.state.abuse_gate = container.make_abuse_gate(
        settings, app.state.security_log, app.state.agent_config
    )
    app.state.catalog_admin = catalog_admin or container.make_catalog_admin(
        settings, factory, app.state.chat_agent
    )
    app.add_exception_handler(AuthRefusal, refusal_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ChatRefusal, chat_refusal_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_handler)  # type: ignore[arg-type]

    # Added before CORS so the CORS layer wraps it and its 413/503 answers carry CORS headers.
    app.add_middleware(ChatBodyGuard, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.include_router(health.router)
    app.include_router(catalog.router)
    app.include_router(quote.router)
    app.include_router(auth.router)
    app.include_router(records.me_router)
    app.include_router(records.admin_router)
    app.include_router(admin_catalog.router)
    app.include_router(security.router)
    app.include_router(portfolio.public_router)
    app.include_router(portfolio.admin_router)
    return app
