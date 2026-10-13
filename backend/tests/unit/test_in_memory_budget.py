"""InMemoryUsageBudget: per-UTC-day reserve/settle with the same semantics as the DB."""

from datetime import UTC, date, datetime, timedelta

from eventssound.adapters.usage.memory import InMemoryUsageBudget


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make_budget(clock=None, token_cap=100_000, cost_cap=1_000_000):
    return InMemoryUsageBudget(
        token_cap=token_cap,
        cost_cap_micro_usd=cost_cap,
        now=clock or (lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC)),
    )


class TestReserve:
    def test_reserve_within_the_cap(self) -> None:
        b = make_budget()
        r = b.reserve(8_000, 40_000)
        assert r is not None
        assert r.tokens == 8_000
        assert r.cost_micro_usd == 40_000
        assert r.day == date(2026, 10, 12)

    def test_reserve_exhausting_the_token_cap(self) -> None:
        b = make_budget(token_cap=10_000)
        assert b.reserve(10_000, 0) is not None
        assert b.reserve(1, 0) is None

    def test_reserve_exhausting_the_cost_cap(self) -> None:
        b = make_budget(cost_cap=50_000)
        assert b.reserve(0, 50_000) is not None
        assert b.reserve(0, 1) is None

    def test_reserve_larger_than_the_cap_is_rejected(self) -> None:
        b = make_budget(token_cap=10_000)
        assert b.reserve(10_001, 0) is None
        # and nothing was consumed
        assert b.reserve(10_000, 0) is not None

    def test_a_zero_cap_blocks_any_real_reserve(self) -> None:
        b = make_budget(token_cap=0)
        assert b.reserve(1, 0) is None


class TestSettle:
    def test_settle_releases_the_unused_part(self) -> None:
        b = make_budget(token_cap=10_000)
        r = b.reserve(8_000, 0)
        b.settle(r, 3_000, 0)
        # 3,000 now consumed -> 7,000 of headroom left
        assert b.reserve(5_000, 0) is not None
        assert b.reserve(2_000, 0) is not None
        assert b.reserve(1, 0) is None

    def test_settle_after_a_total_failure_frees_everything(self) -> None:
        b = make_budget(token_cap=10_000)
        r = b.reserve(8_000, 0)
        b.settle(r, 0, 0)
        assert b.reserve(8_000, 0) is not None

    def test_settle_never_goes_negative(self) -> None:
        b = make_budget(token_cap=10_000)
        r = b.reserve(8_000, 0)
        b.settle(r, 0, 0)
        b.settle(r, 0, 0)  # double settle: idempotent-safe floor at zero
        assert b.reserve(8_000, 0) is not None

    def test_cost_settle_is_independent_of_tokens(self) -> None:
        b = make_budget(cost_cap=100_000)
        r = b.reserve(0, 90_000)
        b.settle(r, 0, 40_000)
        assert b.reserve(0, 50_000) is not None
        assert b.reserve(0, 51_000) is None


class TestDayRoll:
    def test_a_new_day_starts_with_a_fresh_budget(self) -> None:
        clock = FakeClock(datetime(2026, 10, 12, 23, 59, tzinfo=UTC))
        b = make_budget(clock=clock, token_cap=10_000)
        assert b.reserve(10_000, 0) is not None
        clock.now += timedelta(days=1)
        assert b.reserve(10_000, 0) is not None

    def test_uses_the_utc_day_not_the_local_one(self) -> None:
        from zoneinfo import ZoneInfo

        # 23:00 Bogota (UTC-5, no DST) on the 11th is 04:00 UTC on the 12th:
        # the day must be the UTC one, not the local one.
        b = InMemoryUsageBudget(
            token_cap=10_000,
            cost_cap_micro_usd=1,
            now=lambda: datetime(2026, 10, 11, 23, 0, tzinfo=ZoneInfo("America/Bogota")),
        )
        r = b.reserve(1, 0)
        assert r.day == date(2026, 10, 12)
