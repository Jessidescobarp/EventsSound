"""Persistent daily LLM budget over `llm_usage_daily`: the real money control.

Reserve is ONE atomic upsert whose WHERE enforces both caps, so concurrent requests serialize on
the row lock and the total can never pass a cap. A database error in reserve raises (the guard in
the entrypoint turns it into a refusal: fail closed). Settle never raises: the answer already
exists, and an unsettled reservation only over-counts. Nothing here logs SQL, URLs or user text.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.models import LlmUsageDailyModel as Usage
from eventssound.application.usage import Reservation

logger = logging.getLogger(__name__)

MAX_AMOUNT = 2**62  # far below BIGINT, so a sum of bounded amounts cannot overflow


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
        now: Callable[[], datetime] | None = None,
    ) -> None:
        _check(token_cap, cost_cap_micro_usd)
        self._factory = factory
        self._token_cap = token_cap
        self._cost_cap = cost_cap_micro_usd
        self._now = now or (lambda: datetime.now(UTC))

    def reserve(self, tokens: int, cost_micro_usd: int) -> Reservation | None:
        _check(tokens, cost_micro_usd)
        # The insert path of an upsert has no WHERE, so an oversized request is refused here.
        if tokens > self._token_cap or cost_micro_usd > self._cost_cap:
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
            where=(Usage.tokens + statement.excluded.tokens <= self._token_cap)
            & (Usage.cost_micro_usd + statement.excluded.cost_micro_usd <= self._cost_cap),
        ).returning(Usage.day)
        try:
            with self._factory.begin() as session:
                granted = session.execute(statement).first() is not None
        except SQLAlchemyError as exc:
            logger.error("usage reserve failed: %s", type(exc).__name__)
            raise UsageStoreError("usage store unavailable") from None
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
                session.execute(statement)
        except SQLAlchemyError as exc:
            logger.error("usage settle failed: %s", type(exc).__name__)
