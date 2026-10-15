"""Composition root: the only place where concrete adapters are bound to ports.

The chat pieces are built here once per process. Nothing touches the network or the
database at import or startup: the agent (which needs the catalog) is built on its first
request, and a configuration that cannot serve chat simply leaves the endpoint disabled.
"""

import logging
import secrets
import threading
from collections.abc import Callable, Iterator
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.auth.hasher import Argon2Hasher
from eventssound.adapters.auth.tokens import JwtTokenIssuer
from eventssound.adapters.db.booking_repository import SqlAlchemyBookingRepository
from eventssound.adapters.db.catalog_repository import SqlAlchemyCatalogRepository
from eventssound.adapters.db.catalog_writer import SqlAlchemyCatalogWriter
from eventssound.adapters.db.embedding_store import SqlAlchemyEmbeddingStore
from eventssound.adapters.db.health import SqlAlchemyDatabaseHealth
from eventssound.adapters.db.quote_repository import SqlAlchemyBookingLister, SqlAlchemyQuoteStore
from eventssound.adapters.db.session import build_engine, build_session_factory
from eventssound.adapters.db.user_repository import SqlAlchemyUserRepository
from eventssound.adapters.embeddings.fake import FakeEmbeddingProvider
from eventssound.adapters.embeddings.openrouter import OpenRouterEmbeddingProvider
from eventssound.adapters.llm.openrouter import OpenRouterProvider
from eventssound.adapters.llm.replay import ReplayProvider
from eventssound.adapters.search.hybrid import HybridSearch
from eventssound.adapters.search.keyword import KeywordSearch
from eventssound.adapters.search.vector import VectorSearch
from eventssound.adapters.usage.memory import InMemoryUsageBudget
from eventssound.adapters.usage.postgres import PostgresUsageBudget
from eventssound.adapters.usage.rate_limit import InMemoryRateLimiter
from eventssound.application.auth import AuthService
from eventssound.application.availability import check_event_availability
from eventssound.application.catalog_admin import CatalogAdmin
from eventssound.application.embedding_index import refresh_embeddings
from eventssound.application.embeddings import EmbeddingProvider
from eventssound.application.llm import LlmProvider
from eventssound.application.ports import CatalogRepository, DatabaseHealthPort
from eventssound.application.pricing import price_quote
from eventssound.application.quote_chat import AgentInput, AgentOutcome, ChatLimits, QuoteAgent
from eventssound.application.quotes import BookingLister, QuoteStore
from eventssound.application.usage import RateLimiter, UsageBudget
from eventssound.config import Settings
from eventssound.domain.availability import default_availability_rules
from eventssound.domain.catalog import Catalog
from eventssound.domain.pricing_rules import default_pricing_rules
from eventssound.entrypoints.api.auth_kit import AuthKit
from eventssound.entrypoints.api.guards import FailClosedLimiter

SessionProvider = Callable[[], Iterator[Session]]

logger = logging.getLogger(__name__)
FAKE_EMBEDDING_MODEL = "fake-embedding"
TIMEZONE = "America/Bogota"


def build_session_factory_from(settings: Settings) -> sessionmaker[Session]:
    return build_session_factory(build_engine(settings.database_url.get_secret_value()))


def make_session_provider(factory: sessionmaker[Session]) -> SessionProvider:
    def provide() -> Iterator[Session]:
        with factory() as session:
            yield session

    return provide


def make_database_health(factory: sessionmaker[Session]) -> DatabaseHealthPort:
    return SqlAlchemyDatabaseHealth(factory)


def make_catalog_repository(factory: sessionmaker[Session]) -> CatalogRepository:
    return SqlAlchemyCatalogRepository(factory)


def make_chat_limits(settings: Settings) -> ChatLimits:
    return ChatLimits(
        input_price_micro_usd=settings.llm_input_price_micro_usd_per_mtok,
        output_price_micro_usd=settings.llm_output_price_micro_usd_per_mtok,
    )


def make_rate_limiter(settings: Settings) -> RateLimiter:
    return InMemoryRateLimiter(settings.chat_rate_limit_per_minute)


def make_usage_budget(settings: Settings, factory: sessionmaker[Session]) -> UsageBudget:
    """Postgres whenever the chat can spend real money; in-memory otherwise.

    Explicit rule: an active OpenRouter chat (real money) ALWAYS uses the persistent budget, in
    any APP_ENV; the in-memory one serves only the replay provider, which spends nothing. The
    engine behind `factory` is lazy, so no connection is opened here.
    """
    if (
        settings.llm_provider == "openrouter"
        and settings.llm_daily_cost_cap_micro_usd > 0
        and not (
            settings.llm_input_price_micro_usd_per_mtok
            or settings.llm_output_price_micro_usd_per_mtok
        )
    ):
        # Fine for a free model; for a paid one the cost cap never binds (only the token cap).
        logger.warning("LLM prices are 0: the daily cost cap cannot bind, only the token cap")
    if settings.chat_active and settings.llm_provider == "openrouter":
        logger.info("daily LLM budget: postgres (persistent)")
        return PostgresUsageBudget(
            factory,
            token_cap=settings.llm_daily_token_cap,
            cost_cap_micro_usd=settings.llm_daily_cost_cap_micro_usd,
        )
    logger.info("daily LLM budget: in-memory (resets on restart; replay provider only)")
    return InMemoryUsageBudget(
        token_cap=settings.llm_daily_token_cap,
        cost_cap_micro_usd=settings.llm_daily_cost_cap_micro_usd,
    )


def make_llm_provider(settings: Settings) -> LlmProvider:
    if settings.llm_provider == "openrouter":
        return OpenRouterProvider(settings.openrouter_api_key, settings.llm_model)
    # Only reachable outside production (`Settings.chat_active`). Without fixtures it answers
    # nothing, so a local chat call fails loudly instead of inventing quotes.
    return ReplayProvider({})


def _make_search(
    settings: Settings, factory: sessionmaker[Session], catalog: Catalog
) -> HybridSearch:
    keyword = KeywordSearch(catalog)
    built = _make_embedder(settings)
    if built is None:
        return HybridSearch(keyword, None)
    embedder, model = built
    vector = VectorSearch(embedder, SqlAlchemyEmbeddingStore(factory), catalog, model)
    return HybridSearch(keyword, vector)


def _make_embedder(settings: Settings) -> tuple[EmbeddingProvider, str] | None:
    """The embedder and its model name, or None when embeddings are off."""
    if settings.embedding_provider == "off":
        return None
    if settings.embedding_provider == "fake":
        return (
            FakeEmbeddingProvider(settings.embedding_dimensions, FAKE_EMBEDDING_MODEL),
            FAKE_EMBEDDING_MODEL,
        )
    embedder = OpenRouterEmbeddingProvider(
        settings.openrouter_api_key, settings.embedding_model, settings.embedding_dimensions
    )
    return embedder, settings.embedding_model


def _build_agent(settings: Settings, factory: sessionmaker[Session]) -> QuoteAgent:
    # Imported here: LangGraph costs import time and memory that /health must not pay.
    from eventssound.adapters.agent.graph import GraphQuoteAgent
    from eventssound.adapters.agent.nodes import AgentDeps

    catalog_repository = SqlAlchemyCatalogRepository(factory)
    booking_repository = SqlAlchemyBookingRepository(factory)
    availability_rules = default_availability_rules()
    pricing_rules = default_pricing_rules()
    # The search index is a snapshot of the catalog taken here; a reseed needs a restart.
    search = _make_search(settings, factory, catalog_repository.get_catalog())
    return GraphQuoteAgent(
        AgentDeps(
            provider=make_llm_provider(settings),
            search=search,
            load_catalog=catalog_repository.get_catalog,
            check_availability=lambda request: check_event_availability(
                request, catalog_repository, booking_repository, availability_rules
            ),
            price=lambda request: price_quote(request, catalog_repository, pricing_rules),
            limits=make_chat_limits(settings),
            timezone=ZoneInfo(TIMEZONE),
        )
    )


class LazyQuoteAgent:
    """Builds the real agent on the first request, once, so startup never needs the database."""

    def __init__(self, build: Callable[[], QuoteAgent]) -> None:
        self._build = build
        self._agent: QuoteAgent | None = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Drop the built agent: the next request rebuilds it, and its search index, from the
        current catalog. Requests already running keep the agent they started with."""
        with self._lock:
            self._agent = None

    def run(self, data: AgentInput) -> AgentOutcome:
        agent = self._agent
        if agent is None:
            with self._lock:
                if self._agent is None:
                    self._agent = self._build()
                agent = self._agent
        return agent.run(data)


def make_quote_agent(settings: Settings, factory: sessionmaker[Session]) -> QuoteAgent:
    return LazyQuoteAgent(lambda: _build_agent(settings, factory))


def make_catalog_admin(
    settings: Settings, factory: sessionmaker[Session], agent: QuoteAgent
) -> CatalogAdmin:
    return CatalogAdmin(
        SqlAlchemyCatalogWriter(factory), make_catalog_change_hook(settings, factory, agent)
    )


def make_catalog_change_hook(
    settings: Settings, factory: sessionmaker[Session], agent: QuoteAgent
) -> Callable[[], None]:
    """The follow-up of a catalog edit: re-embed what changed, then make the agent rebuild its
    search index. Without it the agent would not see an edit until the process restarts. The
    agent is reset even when embedding fails (keyword search still needs the new catalog)."""
    repository = SqlAlchemyCatalogRepository(factory)

    def on_changed() -> None:
        try:
            built = _make_embedder(settings)
            if built is not None:
                embedder, model = built
                refresh_embeddings(
                    repository.get_catalog(), embedder, SqlAlchemyEmbeddingStore(factory), model
                )
        finally:
            if isinstance(agent, LazyQuoteAgent):
                agent.reset()

    return on_changed


def make_auth_kit(settings: Settings, factory: sessionmaker[Session]) -> AuthKit | None:
    """The login pieces, or None when production has no usable JWT secret.

    Outside production an unset secret becomes a random per-process one (tokens die on restart),
    so local development needs no setup. In production None keeps the app booting while the
    auth routes answer 503.
    """
    secret = settings.jwt_secret
    if secret is None:
        if settings.is_production:
            logger.warning("JWT_SECRET is missing or weak: auth routes are disabled")
            return None
        secret = SecretStr(secrets.token_urlsafe(48))
    hasher = Argon2Hasher()
    tokens = JwtTokenIssuer(secret, settings.jwt_access_ttl_minutes)
    service = AuthService(
        SqlAlchemyUserRepository(factory),
        hasher,
        tokens,
        dummy_hash=hasher.hash(secrets.token_urlsafe(16)),
    )
    per_minute = settings.login_rate_limit_per_minute
    return AuthKit(
        service,
        tokens,
        FailClosedLimiter(InMemoryRateLimiter(per_minute)),
        FailClosedLimiter(InMemoryRateLimiter(per_minute)),
    )


def make_quote_store(factory: sessionmaker[Session]) -> QuoteStore:
    return SqlAlchemyQuoteStore(factory)


def make_booking_lister(factory: sessionmaker[Session]) -> BookingLister:
    return SqlAlchemyBookingLister(factory)
