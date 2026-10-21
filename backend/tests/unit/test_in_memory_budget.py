"""InMemoryUsageBudget: per-UTC-day reserve/settle with the same semantics as the DB."""

from datetime import UTC, date, datetime, timedelta

import pytest

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


class TestLiveCaps:
    """`caps` is asked on every reserve; the constructor caps are only the fallback."""

    @staticmethod
    def with_caps(source, token_cap=100_000, cost_cap=1_000_000):
        return InMemoryUsageBudget(
            token_cap=token_cap,
            cost_cap_micro_usd=cost_cap,
            now=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
            caps=source,
        )

    def test_a_lowered_cap_applies_to_the_next_reserve(self) -> None:
        live = [(10_000, 100_000)]
        b = self.with_caps(lambda: live[0])
        assert b.reserve(6_000, 0) is not None
        live[0] = (6_000, 100_000)  # lowered below today's usage plus one more token
        assert b.reserve(1, 0) is None
        assert b.reserve(0, 1) is not None  # the other cap is independent

    def test_a_raised_cap_applies_to_the_next_reserve(self) -> None:
        live = [(10, 10)]
        b = self.with_caps(lambda: live[0], token_cap=10, cost_cap=10)
        assert b.reserve(10, 10) is not None
        assert b.reserve(1, 0) is None
        live[0] = (500, 500)
        assert b.reserve(400, 400) is not None

    def test_a_source_equal_to_the_constructor_caps_behaves_like_no_source(self) -> None:
        plain = make_budget(token_cap=1_000, cost_cap=5_000)
        live = self.with_caps(lambda: (1_000, 5_000), token_cap=1_000, cost_cap=5_000)
        for tokens, cost in [(600, 0), (401, 0), (400, 5_000), (0, 1), (1_001, 0)]:
            assert (plain.reserve(tokens, cost) is None) == (live.reserve(tokens, cost) is None)

    def test_zero_from_the_source_refuses_everything_like_a_zero_constructor_cap(self) -> None:
        assert self.with_caps(lambda: (0, 0)).reserve(1, 0) is None
        assert make_budget(token_cap=0, cost_cap=0).reserve(1, 0) is None

    @pytest.mark.parametrize(
        "source",
        [
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            lambda: (-1, 5),
            lambda: (5, 1.5),
            lambda: None,
        ],
        ids=["raises", "negative", "not-int", "not-a-pair"],
    )
    def test_a_broken_source_falls_back_to_the_constructor_caps(self, source) -> None:
        b = self.with_caps(source, token_cap=100, cost_cap=100)
        assert b.reserve(100, 0) is not None
        assert b.reserve(1, 0) is None

    def test_lowering_a_cap_below_the_usage_refuses_new_reserves_and_keeps_the_usage(self) -> None:
        live = [(10_000, 100_000)]
        b = self.with_caps(lambda: live[0])
        assert b.reserve(6_000, 0) is not None
        live[0] = (3_000, 100_000)  # below what is already used today
        assert b.reserve(1, 0) is None and b.reserve(0, 1) is None  # over the cap blocks all
        live[0] = (10_000, 100_000)  # the usage was kept: exactly 4_000 tokens are left
        assert b.reserve(4_001, 0) is None
        assert b.reserve(4_000, 0) is not None
