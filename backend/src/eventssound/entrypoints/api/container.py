"""Composition root: the only place where concrete adapters are bound to ports.

The chat pieces are built here once per process. Nothing touches the network or the
database at import or startup: the agent (which needs the catalog) is built on its first
request, and a configuration that cannot serve chat simply leaves the endpoint disabled.
"""

import dataclasses
import logging
import secrets
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.auth.hasher import Argon2Hasher
from eventssound.adapters.auth.tokens import JwtTokenIssuer
from eventssound.adapters.db.agent_config_repository import SqlAlchemyAgentConfigRepository
from eventssound.adapters.db.booking_repository import SqlAlchemyBookingRepository
from eventssound.adapters.db.catalog_repository import SqlAlchemyCatalogRepository
from eventssound.adapters.db.catalog_writer import SqlAlchemyCatalogWriter
from eventssound.adapters.db.embedding_store import SqlAlchemyEmbeddingStore
from eventssound.adapters.db.health import SqlAlchemyDatabaseHealth
from eventssound.adapters.db.portfolio_repository import SqlAlchemyPortfolioStore
from eventssound.adapters.db.quote_repository import SqlAlchemyBookingLister, SqlAlchemyQuoteStore
from eventssound.adapters.db.security_repository import SqlAlchemySecurityLog
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
from eventssound.application.agent_config import ActiveConfigProvider
from eventssound.application.auth import AuthService
from eventssound.application.availability import check_event_availability
from eventssound.application.catalog_admin import CatalogAdmin
from eventssound.application.confirmation import ConfirmationTokens, derive_confirmation_key
from eventssound.application.embedding_index import refresh_embeddings
from eventssound.application.embeddings import EmbeddingProvider
from eventssound.application.llm import LlmProvider
from eventssound.application.portfolio import PortfolioStore
from eventssound.application.ports import (
    AgentConfigRepository,
    CatalogRepository,
    DatabaseHealthPort,
)
from eventssound.application.pricing import price_quote
from eventssound.application.quote_chat import AgentInput, AgentOutcome, ChatLimits, QuoteAgent
from eventssound.application.quotes import BookingLister, QuoteStore
from eventssound.application.security import (
    REFUSED_LIMIT_BY_POLICY,
    AbuseGate,
    SecurityLog,
    derive_key,
)
from eventssound.application.usage import CapsSource, RateLimiter, UsageBudget
from eventssound.config import Settings
from eventssound.domain.availability import default_availability_rules
from eventssound.domain.catalog import Catalog
from eventssound.domain.model_prices import price_for
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


def make_agent_config_repository(
    settings: Settings, factory: sessionmaker[Session]
) -> AgentConfigRepository:
    return SqlAlchemyAgentConfigRepository(factory, settings.allowed_llm_models)


def make_agent_config(
    settings: Settings,
    factory: sessionmaker[Session],
    repository: AgentConfigRepository | None = None,
) -> ActiveConfigProvider:
    """The active agent config, read through a short TTL cache and never failing: with an empty
    table or any storage error it is exactly the Settings defaults (today's behavior)."""
    repository = repository or make_agent_config_repository(settings, factory)
    return ActiveConfigProvider(repository, settings)


def make_confirmation_tokens(settings: Settings) -> ConfirmationTokens | None:
    """Confirmation tokens signed with a key derived from the JWT secret. None without a secret:
    the admin config endpoints then refuse to preview or apply (fail closed)."""
    secret = settings.jwt_secret
    if secret is None:
        return None
    return ConfirmationTokens(derive_confirmation_key(secret.get_secret_value()))


def make_admin_limiter() -> RateLimiter:
    """Preview and apply per admin user: 10 per minute, in this process only."""
    return FailClosedLimiter(InMemoryRateLimiter(10, per_hour=600))


def make_chat_limits(settings: Settings) -> ChatLimits:
    return ChatLimits(
        input_price_micro_usd=settings.llm_input_price_micro_usd_per_mtok,
        output_price_micro_usd=settings.llm_output_price_micro_usd_per_mtok,
    )


def _active_model(settings: Settings, active: ActiveConfigProvider) -> str:
    # Replay never calls a model, so an edit of the model must not change what it runs.
    if settings.llm_provider != "openrouter":
        return settings.llm_model
    return active.current().config.llm_model


def make_chat_limits_source(
    settings: Settings, active: ActiveConfigProvider | None = None
) -> Callable[[], ChatLimits]:
    """The limits of the next request, priced for the ACTIVE model (an admin may switch it).

    A free model costs 0, so the daily cost cap does not bind for it (the token cap still does).
    A model without a price or any failure resolving it keeps the environment pair (today's
    behavior), never a made-up one.
    """
    base = make_chat_limits(settings)
    if active is None:
        return lambda: base

    def limits() -> ChatLimits:
        # ONE read of the active model per request: the same model is priced here and pinned
        # for the agent run, so a refresh in between cannot run a model priced as another.
        try:
            model = _active_model(settings, active)
            price = price_for(model, settings)
        except Exception as error:  # noqa: BLE001  (pricing must never fail a chat request)
            logger.warning(
                "model price unavailable, using the environment prices: %s", type(error).__name__
            )
            return base
        pinned = dataclasses.replace(base, model=model)
        if price is None:
            return pinned
        return dataclasses.replace(
            pinned,
            input_price_micro_usd=price.input_micro_usd_per_mtok,
            output_price_micro_usd=price.output_micro_usd_per_mtok,
        )

    return limits


def make_rate_limiter(
    settings: Settings, active: ActiveConfigProvider | None = None
) -> RateLimiter:
    """One limiter for the process: an edit of the per-minute limit changes the threshold of the
    next hit, never the recorded hits. The hourly and global limits are not editable."""
    source = None if active is None else lambda: active.current().config.chat_rate_limit_per_minute
    return InMemoryRateLimiter(settings.chat_rate_limit_per_minute, per_minute_source=source)


def _budget_caps(active: ActiveConfigProvider | None) -> CapsSource | None:
    if active is None:
        return None

    def caps() -> tuple[int, int]:
        config = active.current().config
        return config.daily_token_cap, config.daily_cost_cap_micro_usd

    return caps


def make_usage_budget(
    settings: Settings,
    factory: sessionmaker[Session],
    active: ActiveConfigProvider | None = None,
) -> UsageBudget:
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
    caps = _budget_caps(active)
    if settings.chat_active and settings.llm_provider == "openrouter":
        logger.info("daily LLM budget: postgres (persistent)")
        return PostgresUsageBudget(
            factory,
            token_cap=settings.llm_daily_token_cap,
            cost_cap_micro_usd=settings.llm_daily_cost_cap_micro_usd,
            caps=caps,
        )
    logger.info("daily LLM budget: in-memory (resets on restart; replay provider only)")
    return InMemoryUsageBudget(
        token_cap=settings.llm_daily_token_cap,
        cost_cap_micro_usd=settings.llm_daily_cost_cap_micro_usd,
        caps=caps,
    )


def make_llm_provider(settings: Settings, model: str | None = None) -> LlmProvider:
    """`model` is the active config's model; the provider kind and the API key stay in Settings."""
    if settings.llm_provider == "openrouter":
        return OpenRouterProvider(settings.openrouter_api_key, model or settings.llm_model)
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


def _build_agent(
    settings: Settings,
    factory: sessionmaker[Session],
    model: str | None = None,
    active: ActiveConfigProvider | None = None,
) -> QuoteAgent:
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
            provider=make_llm_provider(settings, model),
            search=search,
            load_catalog=catalog_repository.get_catalog,
            check_availability=lambda request: check_event_availability(
                request, catalog_repository, booking_repository, availability_rules
            ),
            price=lambda request: price_quote(request, catalog_repository, pricing_rules),
            limits=make_chat_limits(settings),
            timezone=ZoneInfo(TIMEZONE),
            config_source=None if active is None else lambda: active.current().config,
        )
    )


class LazyQuoteAgent:
    """Builds the real agent on the first request, once, so startup never needs the database.

    With a `model_source` (the active config's model) the agent is rebuilt, once, when the model
    differs from the one it was built with, and `build` receives that model. A failing source
    keeps the agent already built.
    """

    def __init__(
        self,
        build: Callable[..., QuoteAgent],
        model_source: Callable[[], str] | None = None,
    ) -> None:
        self._build = build
        self._model_source = model_source
        self._built: tuple[QuoteAgent, str | None] | None = None  # the agent and its model
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Drop the built agent: the next request rebuilds it, and its search index, from the
        current catalog. Requests already running keep the agent they started with."""
        with self._lock:
            self._built = None

    def _wanted_model(self, pinned: str | None = None) -> str | None:
        if pinned is not None:  # the model the request was priced for always wins
            return pinned
        if self._model_source is not None:
            try:
                return self._model_source()
            except Exception:  # noqa: BLE001  (fail-safe: keep what is built)
                built = self._built
                return built[1] if built else None
        return None

    def run(self, data: AgentInput) -> AgentOutcome:
        pinned = getattr(data, "model", None)
        model = self._wanted_model(pinned)
        built = self._built
        if built is None or built[1] != model:
            built = self._rebuild(pinned)
        return built[0].run(data)

    def _rebuild(self, pinned: str | None = None) -> tuple[QuoteAgent, str | None]:
        with self._lock:
            # Re-read inside the lock: a request that read the model before a switch must not
            # rebuild the old model over the newer one (a pinned model is the exception: it is
            # what the request was priced for).
            model = self._wanted_model(pinned)
            built = self._built
            if built is not None and built[1] == model:
                return built
            try:
                agent = self._build() if self._model_source is None else self._build(model)
            except Exception as error:  # noqa: BLE001
                if built is None:
                    raise  # nothing to fall back to: same as the first build always was
                # Keep serving the previous working agent (and retry on the next request).
                logger.warning(
                    "agent rebuild failed, keeping the previous one: %s", type(error).__name__
                )
                return built
            self._built = (agent, model)
            return self._built


def make_quote_agent(
    settings: Settings,
    factory: sessionmaker[Session],
    active: ActiveConfigProvider | None = None,
) -> QuoteAgent:
    if active is None:
        return LazyQuoteAgent(lambda: _build_agent(settings, factory))

    def model_source() -> str:
        return _active_model(settings, active)

    return LazyQuoteAgent(
        lambda model: _build_agent(settings, factory, model, active), model_source
    )


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


def make_security_log(factory: sessionmaker[Session]) -> SecurityLog:
    return SqlAlchemySecurityLog(factory)


def make_abuse_gate(
    settings: Settings, log: SecurityLog, active: ActiveConfigProvider | None = None
) -> AbuseGate:
    """Client pseudonyms are keyed by a purpose-bound key derived from the JWT secret, or by a
    random per-process one when it is unset. The block needs a trustworthy client address:
    in production with TRUSTED_PROXY_HOPS=0 every visitor shares the proxy's address, so the
    block stays off rather than lock everyone out."""
    secret = settings.jwt_secret
    key = derive_key(secret.get_secret_value()) if secret else secrets.token_bytes(32)
    enabled = not (settings.is_production and settings.trusted_proxy_hops == 0)
    if not enabled:
        logger.warning("abuse block disabled: set TRUSTED_PROXY_HOPS so clients can be told apart")
    source = (
        None
        if active is None
        else lambda: REFUSED_LIMIT_BY_POLICY[active.current().config.off_topic_policy]
    )
    return AbuseGate(log, key, lambda: datetime.now(UTC), enabled=enabled, limit_source=source)


def make_booking_lister(factory: sessionmaker[Session]) -> BookingLister:
    return SqlAlchemyBookingLister(factory)


def make_portfolio_store(factory: sessionmaker[Session]) -> PortfolioStore:
    return SqlAlchemyPortfolioStore(factory)
