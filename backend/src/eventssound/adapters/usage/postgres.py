"""Persistent daily LLM budget over `llm_usage_daily`: the real money control.

Reserve is ONE atomic upsert whose WHERE enforces both caps, so concurrent requests serialize on
the row lock and the total can never pass a cap. A database error in reserve raises (the guard in
the entrypoint turns it into a refusal: fail closed). Settle never raises: the answer already
exists, and an unsettled reservation only over-counts. Nothing here logs SQL, URLs or user text.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.models import LlmUsageDailyModel as Usage
from eventssound.application.usage import CapsSource, Reservation, resolve_caps

logger = logging.getLogger(__name__)

MAX_AMOUNT = 2**53  # exactly representable even in a float client; sums stay far below BIGINT


class UsageStoreError(Exception):
    """The budget store failed; the message never carries driver details."""


def _check(*values: object) -> None:
    for value in values:
        if type(value) is not int:
            raise TypeError("usage amounts must be int")
        if value < 0 or value > MAX_AMOUNT:
            raise ValueError("usage amount out of range")


class PostgresUsageBudget:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        token_cap: int,
        cost_cap_micro_usd: int,
        statement_timeout_ms: int = 5_000,
        lock_timeout_ms: int = 3_000,
        now: Callable[[], datetime] | None = None,
        caps: CapsSource | None = None,
    ) -> None:
        """`token_cap` and `cost_cap_micro_usd` are the defaults; `caps`, when given, is asked on
        every reserve (the admin-editable config) and falls back to them if it fails."""
        _check(token_cap, cost_cap_micro_usd, statement_timeout_ms, lock_timeout_ms)
        self._factory = factory
        self._token_cap = token_cap
        self._cost_cap = cost_cap_micro_usd
        self._caps = caps
        self._now = now or (lambda: datetime.now(UTC))
        self._timeouts = (statement_timeout_ms, lock_timeout_ms)

    def _bound_the_wait(self, session: Session) -> None:
        # SET LOCAL semantics (is_local=true): scoped to this transaction, safe behind a pooler.
        for name, milliseconds in zip(
            ("statement_timeout", "lock_timeout"), self._timeouts, strict=True
        ):
            session.execute(select(func.set_config(name, f"{milliseconds}ms", True)))

    def reserve(self, tokens: int, cost_micro_usd: int) -> Reservation | None:
        _check(tokens, cost_micro_usd)
        # The insert path of an upsert has no WHERE, so an oversized request is refused here.
        token_cap, cost_cap = resolve_caps(self._caps, (self._token_cap, self._cost_cap))
        if tokens > token_cap or cost_micro_usd > cost_cap:
            return None
        day = self._now().astimezone(UTC).date()
        statement = insert(Usage).values(day=day, tokens=tokens, cost_micro_usd=cost_micro_usd)
        statement = statement.on_conflict_do_update(
            index_elements=[Usage.day],
            set_={
                "tokens": Usage.tokens + statement.excluded.tokens,
                "cost_micro_usd": Usage.cost_micro_usd + statement.excluded.cost_micro_usd,
                "updated_at": func.now(),
            },
            where=(Usage.tokens + statement.excluded.tokens <= token_cap)
            & (Usage.cost_micro_usd + statement.excluded.cost_micro_usd <= cost_cap),
        ).returning(Usage.day)
        failure: str | None = None
        granted = False
        try:
            with self._factory.begin() as session:
                self._bound_the_wait(session)
                granted = session.execute(statement).first() is not None
        except SQLAlchemyError as exc:
            failure = type(exc).__name__
        if failure is not None:
            # Raised outside the except block: no driver error (DSN, SQL) stays in the context.
            logger.error("usage reserve failed: %s", failure)
            raise UsageStoreError("usage store unavailable")
        return Reservation(day, tokens, cost_micro_usd) if granted else None

    def settle(
        self, reservation: Reservation, actual_tokens: int, actual_cost_micro_usd: int
    ) -> None:
        _check(actual_tokens, actual_cost_micro_usd)
        statement = (
            update(Usage)
            .where(Usage.day == reservation.day)
            .values(
                tokens=func.greatest(0, Usage.tokens + (actual_tokens - reservation.tokens)),
                cost_micro_usd=func.greatest(
                    0, Usage.cost_micro_usd + (actual_cost_micro_usd - reservation.cost_micro_usd)
                ),
                updated_at=func.now(),
            )
        )
        try:
            with self._factory.begin() as session:
                self._bound_the_wait(session)
                session.execute(statement)
        except SQLAlchemyError as exc:
            logger.error("usage settle failed: %s", type(exc).__name__)
